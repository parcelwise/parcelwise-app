"""Buying labels for many orders at once.

Decisions this follows (Raven task a54e7ec0dbe6, 2026-11-02):
- One purchase_label() call per order, each with its own idempotency key, run as a background job (Jordan Okafor).
- An order that already has a live label is skipped and shown as already labeled (Jordan Okafor).
- Buy as many as fit in what's left this month, in the order shown; the rest are offered the upgrade (Priya Shah).
- If an order fails, keep going and report it for retry (Jordan Okafor).
- If a quote went stale or changed, skip that order and ask the merchant to approve the new price (Priya Shah).
- At most 40 USPS purchases a minute per merchant, on the merchant's own account (Ana Ruiz).
- UPS gets the same cap of 40 a minute per merchant; UPS hasn't told us its limit (Ana Ruiz).
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal

from app.billing.plans import how_many_fit
from app.labels.purchase import Label, StaleRateError, purchase_label
from app.labels.rates import Rate

# Purchases per minute, per merchant and carrier.
PURCHASES_PER_MINUTE = {"usps": 40, "ups": 40}

QUEUED = "queued"
BOUGHT = "bought"
FAILED = "failed"
ALREADY_LABELED = "already_labeled"
OVER_ALLOWANCE = "over_allowance"
NEEDS_PRICE_APPROVAL = "needs_price_approval"


@dataclass
class BatchItem:
    order_id: str
    position: int
    rate: Rate
    shown_price: Decimal
    status: str = QUEUED
    tracking_number: str = ""
    error: str = ""


def idempotency_key(batch_id, order_id: str) -> str:
    """Stable for the order and this batch, so a resumed batch never buys an order twice."""
    return f"{order_id}:batch:{batch_id}"


def plan_batch(items: list[BatchItem], *, live_order_ids: set[str], plan: str, used_this_month: int) -> list[BatchItem]:
    """Mark what the batch will skip before anything is bought. Items keep the order the merchant saw."""
    items = sorted(items, key=lambda item: item.position)
    to_buy = []
    for item in items:
        if item.order_id in live_order_ids:
            item.status = ALREADY_LABELED
        else:
            to_buy.append(item)
    fits = how_many_fit(plan, used_this_month, len(to_buy))
    for item in to_buy[fits:]:
        item.status = OVER_ALLOWANCE
    return items


class PerMinuteLimiter:
    """Sliding one-minute window per key. One worker process holds it, so it covers every batch that worker runs."""

    def __init__(self, limits: dict[str, int] | None = None, *, clock=time.monotonic, sleep=time.sleep):
        self.limits = PURCHASES_PER_MINUTE if limits is None else limits
        self.clock = clock
        self.sleep = sleep
        self.calls: dict[tuple, deque] = defaultdict(deque)

    def wait(self, merchant_id: str, carrier: str) -> None:
        limit = self.limits.get(carrier)
        if limit is None:
            return
        window = self.calls[(merchant_id, carrier)]
        now = self.clock()
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            self.sleep(window[0] + 60 - now)
            now = self.clock()
            window.popleft()
        window.append(now)


def run_batch(
    batch_id,
    merchant_id: str,
    items: list[BatchItem],
    *,
    load_order,
    labels_left: int | None,
    limiter: PerMinuteLimiter,
    on_item=lambda item, label: None,
    purchase=purchase_label,
) -> list[BatchItem]:
    """Buy each queued item in the order shown. One failure never stops the rest.

    `labels_left` is re-read when the batch starts, since single purchases may have used some since it was planned.
    `on_item(item, label)` is called after every item that was attempted or skipped, so progress is saved as it goes.
    """
    for item in sorted(items, key=lambda i: i.position):
        if item.status != QUEUED:
            continue
        if labels_left is not None and labels_left <= 0:
            item.status = OVER_ALLOWANCE
            on_item(item, None)
            continue
        label: Label | None = None
        try:
            order = load_order(item.order_id)
            limiter.wait(merchant_id, item.rate.carrier)
            label = purchase(
                order, item.rate, idempotency_key=idempotency_key(batch_id, item.order_id), shown_price=item.shown_price
            )
        except StaleRateError:
            item.status = NEEDS_PRICE_APPROVAL
        except Exception as error:  # noqa: BLE001 -- keep going, report it for retry (decision 8581252f5445)
            item.status = FAILED
            item.error = str(error) or type(error).__name__
        else:
            item.status = BOUGHT
            item.tracking_number = label.tracking_number
            if labels_left is not None:
                labels_left -= 1
        on_item(item, label)
    return items


def summary(items: list[BatchItem]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.status] += 1
    return dict(counts)
