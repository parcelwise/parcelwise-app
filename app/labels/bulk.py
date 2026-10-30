"""Buying labels for many orders at once. Each order is still one purchase_label() call (ADR 0004)."""

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from app.billing.plans import monthly_allowance
from app.labels.carriers import CarrierError
from app.labels.purchase import Label, StaleRateError, purchase_label

log = logging.getLogger(__name__)

# USPS throttles above this and has suspended accounts before (Ana Ruiz, Raven 6c080726bebc).
PURCHASES_PER_MINUTE = 40


class AllowanceExceeded(Exception):
    """The batch would take the merchant past this month's labels. Nothing was bought."""

    def __init__(self, labels_left: int):
        super().__init__(f"{labels_left} labels left this month")
        self.labels_left = labels_left


@dataclass
class BulkItem:
    order: object
    rate: object
    shown_price: Decimal


@dataclass
class BulkResult:
    bought: list[Label] = field(default_factory=list)
    # Quote expired or the price changed. Re-quote and show the merchant the new price before buying.
    stale: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def check_allowance(plan: str, used_this_month: int, count: int) -> None:
    """Refuse the whole batch up front rather than buy part of it (Priya Shah, Raven 0f8437429eff)."""
    allowance = monthly_allowance(plan)
    if allowance is not None and used_this_month + count > allowance:
        raise AllowanceExceeded(max(allowance - used_this_month, 0))


def start_bulk_purchase(
    conn, items: list[BulkItem], *, batch_id: str, merchant_id: str, plan: str, used_this_month: int
) -> str:
    """Check the allowance, then queue the batch for the label worker. Never buys in the request."""
    check_allowance(plan, used_this_month, len(items))
    conn.execute("INSERT INTO label_batches (id, merchant_id) VALUES (%s, %s)", (batch_id, merchant_id))
    for position, item in enumerate(items):
        conn.execute(
            "INSERT INTO label_batch_items (batch_id, position, order_id, carrier, service, rate_id, price, quoted_at, "
            "shown_price) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                batch_id,
                position,
                item.order.id,
                item.rate.carrier,
                item.rate.service,
                item.rate.rate_id,
                item.rate.price,
                item.rate.quoted_at,
                item.shown_price,
            ),
        )
    return batch_id


def batch_status(conn, batch_id: str, merchant_id: str) -> dict:
    """What the Orders page shows while a batch runs and after: which orders were bought, skipped or failed."""
    batch = conn.execute(
        "SELECT status FROM label_batches WHERE id = %s AND merchant_id = %s", (batch_id, merchant_id)
    ).fetchone()
    if batch is None:
        raise LookupError(batch_id)
    rows = conn.execute(
        "SELECT order_id, status, tracking_number, error FROM label_batch_items WHERE batch_id = %s ORDER BY position",
        (batch_id,),
    ).fetchall()
    return {
        "status": batch[0],
        "bought": [{"order_id": r[0], "tracking_number": r[2]} for r in rows if r[1] == "bought"],
        "stale": [r[0] for r in rows if r[1] == "stale"],
        "failed": {r[0]: r[3] for r in rows if r[1] == "failed"},
        "pending": sum(1 for r in rows if r[1] == "pending"),
    }


def buy_labels(
    items: list[BulkItem], *, batch_id: str, record=None, sleep=time.sleep, clock=time.monotonic
) -> BulkResult:
    """Buys one order at a time, at most PURCHASES_PER_MINUTE, and keeps going past failures.

    `record(order_id, status, label_or_error)` is called after each order so progress survives a crash.
    """
    interval = 60 / PURCHASES_PER_MINUTE
    result = BulkResult()
    next_at = clock()
    for item in items:
        wait = next_at - clock()
        if wait > 0:
            sleep(wait)
        next_at = max(next_at, clock()) + interval
        try:
            label = purchase_label(
                item.order,
                item.rate,
                idempotency_key=f"{batch_id}:{item.order.id}",
                shown_price=item.shown_price,
            )
        except StaleRateError:
            result.stale.append(item.order.id)
            outcome = ("stale", None)
        except Exception as error:  # One bad order must not stop the batch (Ana Ruiz, Raven 6c080726bebc).
            if not isinstance(error, CarrierError):
                log.exception("bulk purchase failed for %s in %s", item.order.id, batch_id)
            result.failed[item.order.id] = str(error)
            outcome = ("failed", str(error))
        else:
            result.bought.append(label)
            outcome = ("bought", label)
        if record:
            record(item.order.id, *outcome)
    return result
