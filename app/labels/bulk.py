"""Limits for buying many labels at once (Raven decision a893869c5a46, Jordan Okafor).

Orders are bought serially, one purchase_label() call per order, at most MAX_PER_MINUTE per merchant,
and a batch holds at most MAX_BATCH_SIZE orders. This module holds only the cap and the pacing.
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from app.billing.plans import monthly_allowance
from app.labels.carriers import CarrierError
from app.labels.purchase import StaleRateError, purchase_label

MAX_BATCH_SIZE = 200
MAX_PER_MINUTE = 40


class BatchTooLarge(Exception):
    """The selection is bigger than one batch may be."""

    def __init__(self, size: int):
        super().__init__(f"{size} orders selected; at most {MAX_BATCH_SIZE} can be bought at once")
        self.size = size


def check_batch_size(order_ids) -> None:
    if len(order_ids) > MAX_BATCH_SIZE:
        raise BatchTooLarge(len(order_ids))


ALREADY_LABELED = "already has a label"


def order_ids_with_live_label(conn, order_ids) -> set[str]:
    """Orders that already hold a label that has not been voided (decision 27fca17c0708)."""
    rows = conn.execute(
        "SELECT DISTINCT order_id FROM labels WHERE order_id = ANY(%s) AND voided_at IS NULL",
        (list(order_ids),),
    ).fetchall()
    return {row[0] for row in rows}


def split_already_labeled(order_ids, labeled: set[str]):
    """Returns (to_buy, skipped). Skipped orders are reported to the merchant as ALREADY_LABELED, never bought
    again (decision 5798f83ec250, Jordan Okafor). Order is preserved."""
    to_buy = [o for o in order_ids if o not in labeled]
    skipped = [(o, ALREADY_LABELED) for o in order_ids if o in labeled]
    return to_buy, skipped


class Pacer:
    """Spaces calls so no more than `per_minute` start in any minute. Call wait() before each purchase."""

    def __init__(self, per_minute: int = MAX_PER_MINUTE, *, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60.0 / per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_at = None

    def wait(self) -> None:
        now = self._clock()
        if self._next_at is not None and now < self._next_at:
            self._sleep(self._next_at - now)
            now = self._next_at
        self._next_at = now + self.interval


class AllowanceExceeded(Exception):
    """The batch would take the merchant past their plan's monthly label allowance."""

    def __init__(self, remaining: int, requested: int):
        super().__init__(f"{requested} labels requested; {remaining} left this month")
        self.remaining = remaining
        self.requested = requested


def check_allowance(plan: str, used_this_month: int, requested: int) -> None:
    """Refuse the whole batch before buying anything; never buy part of a request (decision 2e491fb1d4e1)."""
    allowance = monthly_allowance(plan)
    if allowance is None:
        return
    remaining = max(allowance - used_this_month, 0)
    if requested > remaining:
        raise AllowanceExceeded(remaining, requested)


PRICE_OR_QUOTE_CHANGED = "price changed or quote expired"
CARRIER_FAILED = "carrier error"


@dataclass(frozen=True)
class BatchItem:
    """One order to buy, with the exact rate and price the merchant saw and approved."""

    order: object
    rate: object
    shown_price: Decimal
    idempotency_key: str


@dataclass(frozen=True)
class ItemResult:
    order_id: str
    bought: bool
    reason: str = ""
    tracking_number: str = ""
    label: object = field(default=None, compare=False)


def run_item(item: BatchItem) -> ItemResult:
    """Buy one item through purchase_label(). A refusal or carrier failure becomes a skipped result."""
    try:
        label = purchase_label(
            item.order, item.rate, idempotency_key=item.idempotency_key, shown_price=item.shown_price
        )
    except StaleRateError:
        return ItemResult(item.order.id, False, PRICE_OR_QUOTE_CHANGED)
    except CarrierError:
        return ItemResult(item.order.id, False, CARRIER_FAILED)
    return ItemResult(item.order.id, True, tracking_number=label.tracking_number, label=label)


def run_items(items, *, pacer: Pacer | None = None) -> list[ItemResult]:
    """Buy each item serially through purchase_label(), pacing the calls.

    An item that goes stale, changes price or hits a carrier error is skipped and the batch keeps going
    (decision 750a186c3010); nothing is ever bought at a price the merchant did not see, because
    purchase_label() refuses it. One result per item, in order, so the merchant sees what bought and what didn't.
    """
    pacer = pacer or Pacer()
    results = []
    for item in items:
        pacer.wait()
        results.append(run_item(item))
    return results
