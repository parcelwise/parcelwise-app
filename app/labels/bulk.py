"""Buying labels for many orders at once.

Each order is bought on its own through purchase_label() with its own idempotency key (ADR 0004; Raven
decision 97997109cd96, Jordan Okafor): a batch call can't be retried per order, and one bad address would fail
the whole batch.
"""

import time
from collections.abc import Callable
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


# Orders on a carrier bulk buy doesn't cover are skipped with this reason and the rest are bought (Raven decision
# af045e508e3d, Jordan Okafor).
NOT_COVERED_REASON = "bulk buy covers USPS only for now; buy this label from the order's row"


def covered(line: BulkLine) -> bool:
    return line.rate.carrier in BULK_CARRIERS


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
    skipped: list[str]  # order ids on a carrier bulk buy doesn't cover; they are listed, not bought or charged


def quote_batch(lines: list[BulkLine], *, plan: str, used_this_month: int) -> BulkQuote:
    """Each order's price adds up to the carrier total. On a plan that pays per label past its allowance, the
    confirm step also shows how many labels go past it and the extra charge, inside the total (Raven decision
    da4c0386cf19, Priya Shah). The charge itself still posts through the nightly job (ADR 0006).
    """
    check_batch(lines, plan=plan, used_this_month=used_this_month)  # refused here too, before the confirm step
    buying = [line for line in lines if covered(line)]
    skipped = [line.order.id for line in lines if not covered(line)]
    carrier_total = total_price(buying)
    allowance = monthly_allowance(plan)
    extra_price = PLANS[plan]["extra_label_price"]
    past = 0
    if allowance is not None and extra_price is not None:
        past = min(len(buying), max(0, used_this_month + len(buying) - allowance))
    extra_charge = (extra_price or Decimal(0)) * past
    return BulkQuote(carrier_total, past, extra_charge, carrier_total + extra_charge, skipped)


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


def check_batch(lines: list[BulkLine], *, plan: str, used_this_month: int) -> None:
    """Everything that refuses a whole batch before anything is bought."""
    if len(lines) > MAX_ORDERS:
        raise BulkTooLarge(f"{len(lines)} orders; at most {MAX_ORDERS} per bulk buy")
    check_allowance(plan, used_this_month, sum(1 for line in lines if covered(line)))


def buy_labels(
    lines: list[BulkLine],
    *,
    batch_id: str,
    plan: str,
    used_this_month: int,
    live_label: Callable[[object], Label | None],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[BulkOutcome]:
    """Buy a label for each line, one at a time through purchase_label(). Outcomes come back in input order.

    Runs in the background job (app/labels/bulk_jobs.py), which also keeps it to one per merchant at a time.
    `live_label(order)` returns the order's label that hasn't been voided, or None. Purchases are spaced so the
    carrier sees at most PURCHASES_PER_MINUTE from the merchant.
    """
    check_batch(lines, plan=plan, used_this_month=used_this_month)
    return _buy_in_order(lines, batch_id, live_label, clock, sleep)


def _buy_in_order(lines, batch_id, live_label, clock, sleep) -> list[BulkOutcome]:
    gap = 60 / PURCHASES_PER_MINUTE
    outcomes = []
    last_call = None
    for line in lines:
        if not covered(line):
            outcomes.append(BulkOutcome(line.order.id, "skipped", None, NOT_COVERED_REASON))
            continue
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
