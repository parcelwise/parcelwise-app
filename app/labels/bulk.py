"""Buy many labels in one go. Each label still goes through purchase_label(), one order at a time.

Decisions (Raven task 1825e7bdb96f): USPS only, behind a per-merchant flag; one at a time, in order, at most
40 purchases a minute per merchant; skip orders that already have a live label; keep going after a failure and
report every order; refuse the whole batch up front if it would pass the monthly allowance; no retries beyond purchase_label()'s own single retry.
"""

import time
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.labels.purchase import Label, StaleRateError, purchase_label

MAX_PER_MINUTE = 40
BULK_CARRIER = "usps"


@dataclass
class BulkItem:
    """One order, the rate the merchant was shown, and the price they approved."""

    order: object
    rate: object
    shown_price: Decimal


@dataclass
class BulkResult:
    order_id: str
    status: str  # "bought" | "skipped" | "failed"
    label: Label | None = None
    reason: str = ""


class BulkNotEnabled(Exception):
    pass


class AllowanceExceeded(Exception):
    """The batch would pass the plan's monthly allowance. Nothing is bought (a batch is one request)."""

    def __init__(self, remaining: int):
        super().__init__(f"{remaining} labels left this month")
        self.remaining = remaining


def bulk_enabled(merchant) -> bool:
    return getattr(merchant, "id", None) in settings.bulk_labels_merchants


def live_label_order_ids(conn, order_ids: list[str]) -> set[str]:
    """Orders that already have a label that has not been voided."""
    rows = conn.execute(
        "SELECT DISTINCT order_id FROM labels WHERE order_id = ANY(%s) AND voided_at IS NULL", (order_ids,)
    ).fetchall()
    return {row[0] for row in rows}


def buy_labels_bulk(
    items: list[BulkItem],
    *,
    batch_id: str,
    live_label_ids: set[str],
    labels_remaining: int,
    max_per_minute: int = MAX_PER_MINUTE,
    sleep=time.sleep,
    clock=time.monotonic,
) -> list[BulkResult]:
    if items and not bulk_enabled(items[0].order.merchant):
        raise BulkNotEnabled(items[0].order.id)
    # Priya Shah: refuse the whole batch before buying anything if it would pass the monthly allowance.
    would_buy = sum(1 for i in items if i.order.id not in live_label_ids and i.rate.carrier == BULK_CARRIER)
    if would_buy > labels_remaining:
        raise AllowanceExceeded(labels_remaining)
    interval = 60.0 / max_per_minute
    results: list[BulkResult] = []
    last_started: float | None = None
    for item in items:
        order = item.order
        if order.id in live_label_ids:
            results.append(BulkResult(order.id, "skipped", reason="order already has a label"))
            continue
        if item.rate.carrier != BULK_CARRIER:
            results.append(BulkResult(order.id, "skipped", reason="bulk buying is USPS only"))
            continue
        if last_started is not None:
            wait = interval - (clock() - last_started)
            if wait > 0:
                sleep(wait)
        last_started = clock()
        try:
            label = purchase_label(
                order, item.rate, idempotency_key=f"{order.id}:bulk:{batch_id}", shown_price=item.shown_price
            )
        except StaleRateError:
            results.append(BulkResult(order.id, "failed", reason="price changed or quote expired; re-quote"))
        except Exception as error:  # a carrier failure must not stop the rest of the batch
            results.append(BulkResult(order.id, "failed", reason=str(error) or type(error).__name__))
        else:
            results.append(BulkResult(order.id, "bought", label=label))
    return results
