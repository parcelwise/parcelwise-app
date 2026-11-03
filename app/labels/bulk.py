"""Buying labels for many orders at once.

Each order is bought on its own through purchase_label() with its own idempotency key (ADR 0004; Raven
decision 97997109cd96, Jordan Okafor): a batch call can't be retried per order, and one bad address would fail
the whole batch.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from decimal import Decimal

from app.billing.plans import PLANS, monthly_allowance
from app.labels.carriers import CarrierError
from app.labels.purchase import Label, StaleRateError, purchase_label


@dataclass(frozen=True)
class BulkLine:
    """One selected order, the rate the merchant was shown for it, and the price they approved."""

    order: object
    rate: object
    shown_price: Decimal


# Carrier ops limits (Raven decision dd18542dfb3e, Ana Ruiz): at most 200 orders per bulk buy, bought one at a
# time, at most 40 purchases a minute per merchant. 200 at 40 a minute is 5 minutes, inside the 10-minute quote.
MAX_ORDERS = 200
PURCHASES_PER_MINUTE = 40

# USPS only in the first version; UPS comes later (Raven decision d3e93c523639, Ana Ruiz).
BULK_CARRIERS = {"usps"}


@dataclass
class BulkOutcome:
    order_id: str
    status: str  # "bought", or why it was not bought
    label: Label | None = None
    reason: str = ""


class BulkTooLarge(Exception):
    pass


class CarrierNotSupported(Exception):
    """A line uses a carrier bulk buy doesn't cover yet. Nothing was bought."""


class BulkAlreadyRunning(Exception):
    """This merchant already has a bulk buy running. Nothing was bought."""

    def __init__(self):
        super().__init__("A bulk label buy is already running for your shop. Try again when it finishes.")


@contextmanager
def one_bulk_buy_per_merchant(conn, merchant_id: str) -> Iterator[None]:
    """Hold a Postgres advisory lock for the merchant while their bulk buy runs; refuse if one already is.

    One bulk buy per merchant at a time, and a second one is refused, not queued (Raven decision af32723a4431,
    Ana Ruiz). This also keeps the 40-a-minute pace and the allowance check true across batches.
    """
    key = f"bulk-labels:{merchant_id}"
    if not conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (key,)).fetchone()[0]:
        raise BulkAlreadyRunning()
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))


class AllowanceExceeded(Exception):
    """The batch would pass a plan's allowance on a plan that stops there. Nothing was bought."""

    def __init__(self, remaining: int):
        super().__init__(f"{remaining} labels left this month")
        self.remaining = remaining


def check_allowance(plan: str, used_this_month: int, count: int) -> None:
    """Refuse the whole batch up front if it would pass the allowance; never buy part of a request.

    Raven decision b587e27675e9 (Priya Shah, rule from f899fd2228ff). Plans with an extra per-label price keep
    buying past the allowance (app/billing/plans.py), so only plans that stop are refused here.
    """
    allowance = monthly_allowance(plan)
    if allowance is None or PLANS[plan]["extra_label_price"] is not None:
        return
    remaining = max(0, allowance - used_this_month)
    if count > remaining:
        raise AllowanceExceeded(remaining)


def check_carriers(lines: list[BulkLine]) -> None:
    """Refuse a selection with any carrier bulk buy doesn't cover yet. Nothing is bought."""
    other = sorted({line.rate.carrier for line in lines} - BULK_CARRIERS)
    if other:
        raise CarrierNotSupported(f"bulk buy covers {', '.join(sorted(BULK_CARRIERS))} only, not {', '.join(other)}")


def idempotency_key(batch_id: str, order_id: str) -> str:
    """Stable for the order and this bulk attempt, so a retry of the same batch never buys twice."""
    return f"bulk:{batch_id}:{order_id}"


def total_price(lines: list[BulkLine]) -> Decimal:
    """The carrier total: the sum of the prices the merchant was shown."""
    return sum((line.shown_price for line in lines), Decimal(0))


@dataclass(frozen=True)
class BulkQuote:
    """What the confirm step shows before anything is bought."""

    carrier_total: Decimal
    labels_past_allowance: int
    extra_charge: Decimal
    total: Decimal


def quote_batch(lines: list[BulkLine], *, plan: str, used_this_month: int) -> BulkQuote:
    """Each order's price adds up to the carrier total. On a plan that pays per label past its allowance, the
    confirm step also shows how many labels go past it and the extra charge, inside the total (Raven decision
    da4c0386cf19, Priya Shah). The charge itself still posts through the nightly job (ADR 0006).
    """
    check_carriers(lines)  # a batch that will be refused is refused here too, before the confirm step
    check_allowance(plan, used_this_month, len(lines))
    carrier_total = total_price(lines)
    allowance = monthly_allowance(plan)
    extra_price = PLANS[plan]["extra_label_price"]
    past = 0
    if allowance is not None and extra_price is not None:
        past = min(len(lines), max(0, used_this_month + len(lines) - allowance))
    extra_charge = (extra_price or Decimal(0)) * past
    return BulkQuote(carrier_total, past, extra_charge, carrier_total + extra_charge)


def _buy_one(line: BulkLine, batch_id: str) -> BulkOutcome:
    # The merchant approved each order's price and the total before this ran. A quote that went stale or changed
    # since is skipped with the reason, never bought at a price they didn't see (Raven decision 69b44f8e307c,
    # Jordan Okafor; ADR 0003).
    try:
        label = purchase_label(
            line.order,
            line.rate,
            idempotency_key=idempotency_key(batch_id, line.order.id),
            shown_price=line.shown_price,
        )
    except StaleRateError:
        return BulkOutcome(line.order.id, "stale", None, "price expired or changed; get a new quote")
    except CarrierError as error:
        # One order failing at the carrier doesn't stop the batch: keep what bought, list what failed
        # (Raven decision 73523ae6ecc8, Jordan Okafor).
        return BulkOutcome(line.order.id, "failed", None, str(error))
    return BulkOutcome(line.order.id, "bought", label)


def buy_labels(
    lines: list[BulkLine],
    *,
    batch_id: str,
    plan: str,
    used_this_month: int,
    live_label: Callable[[object], Label | None],
    merchant_lock: AbstractContextManager,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[BulkOutcome]:
    """Buy a label for each line, one at a time through purchase_label(). Outcomes come back in input order.

    `live_label(order)` returns the order's label that hasn't been voided, or None. `merchant_lock` is held for the
    whole batch; pass one_bulk_buy_per_merchant(conn, merchant_id). Purchases are spaced so the carrier sees at most
    PURCHASES_PER_MINUTE from the merchant.
    """
    if len(lines) > MAX_ORDERS:
        raise BulkTooLarge(f"{len(lines)} orders; at most {MAX_ORDERS} per bulk buy")
    check_carriers(lines)
    with merchant_lock:
        check_allowance(plan, used_this_month, len(lines))
        return _buy_in_order(lines, batch_id, live_label, clock, sleep)


def _buy_in_order(lines, batch_id, live_label, clock, sleep) -> list[BulkOutcome]:
    gap = 60 / PURCHASES_PER_MINUTE
    outcomes = []
    last_call = None
    for line in lines:
        # An order with a label that hasn't been voided gets that label reprinted, never a second one (Raven
        # decision 28805ba43290, Jordan Okafor, rule from 27fca17c0708): USPS won't refund a double charge.
        existing = live_label(line.order)
        if existing is not None:
            reason = "already has a label; reprint it or void it first"
            outcomes.append(BulkOutcome(line.order.id, "reprint", existing, reason))
            continue
        if last_call is not None:
            wait = last_call + gap - clock()
            if wait > 0:
                sleep(wait)
        last_call = clock()
        outcomes.append(_buy_one(line, batch_id))
    return outcomes
