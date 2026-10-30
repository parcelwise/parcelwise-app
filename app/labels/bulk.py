"""Buying labels for many orders at once. Each order is still one purchase_label() call (ADR 0004)."""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from app.billing.plans import monthly_allowance
from app.labels.carriers import CarrierError
from app.labels.purchase import Label, StaleRateError, purchase_label

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

    def as_dict(self) -> dict:
        return {
            "bought": [
                {"order_id": l.order_id, "tracking_number": l.tracking_number, "price": str(l.price)}
                for l in self.bought
            ],
            "stale": self.stale,
            "failed": self.failed,
        }


def check_allowance(plan: str, used_this_month: int, count: int) -> None:
    """Refuse the whole batch up front rather than buy part of it (Priya Shah, Raven 0f8437429eff)."""
    allowance = monthly_allowance(plan)
    if allowance is not None and used_this_month + count > allowance:
        raise AllowanceExceeded(max(allowance - used_this_month, 0))


def start_bulk_purchase(items: list[BulkItem], *, batch_id: str, plan: str, used_this_month: int, enqueue) -> str:
    """Check the allowance, then hand the batch to the background runner. Never buys in the request."""
    check_allowance(plan, used_this_month, len(items))
    enqueue(buy_labels, items, batch_id=batch_id)
    return batch_id


def buy_labels(items: list[BulkItem], *, batch_id: str, sleep=time.sleep, clock=time.monotonic) -> BulkResult:
    """The background job. Buys one order at a time, at most PURCHASES_PER_MINUTE, and keeps going past failures."""
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
        except CarrierError as error:
            result.failed[item.order.id] = str(error)
        else:
            result.bought.append(label)
    return result
