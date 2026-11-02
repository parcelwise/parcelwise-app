"""Buying labels for many orders at once (Raven task 56151ce9305d).

The rules, each signed off in Raven:

- Each order is bought on its own through purchase_label(), with its own idempotency key (ADR 0004;
  decision 52a409283ec9, Jordan Okafor).
- An order that already has a live label is left out and listed as already labelled on the confirm step
  (fea8c5c7ec77, Jordan Okafor).
- If the request is bigger than what's left of the monthly allowance, buy as many as fit, in the order shown,
  and offer the upgrade for the rest (41132b3cf392, Priya Shah). This applies to bulk buys only.
- If one order fails, keep what's bought, carry on with the rest and report the failures (9718dafd3bca,
  Priya Shah).
- If a quote went stale or its price changed, skip that order and show the merchant the new price to approve;
  never buy at a price they haven't seen (025d7d7e576a, Priya Shah; ADR 0003).
- USPS purchases go no faster than 40 a minute (2d1b20ad6cb3, Ana Ruiz).
- Prices are the quotes from the merchant's own carrier account, negotiated rates included; nothing special is
  done for them (4fc66e42f250, Ana Ruiz).
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from app.billing.plans import monthly_allowance
from app.labels.carriers import CarrierError
from app.labels.purchase import Label, StaleRateError, purchase_label

USPS_BULK_PER_MINUTE = 40


@dataclass(frozen=True)
class BulkItem:
    order: object
    rate: object
    shown_price: Decimal


@dataclass
class BulkPlan:
    """What the confirm step shows, and what the job will try to buy."""

    to_buy: list[BulkItem]
    already_labelled: list[BulkItem]
    over_allowance: list[BulkItem]
    remaining: int | None  # labels left this month before this buy; None means unlimited

    @property
    def total(self) -> Decimal:
        return sum((item.shown_price for item in self.to_buy), Decimal("0"))


class AlreadyLabelled(Exception):
    """The order got a live label (say, bought on its own) after the bulk job was queued. Not bought again."""


@dataclass
class BulkResult:
    bought: list[Label] = field(default_factory=list)
    failed: list[tuple[str, CarrierError]] = field(default_factory=list)
    needs_approval: list[str] = field(default_factory=list)
    already_labelled: list[str] = field(default_factory=list)


def plan_bulk(
    items: list[BulkItem],
    *,
    has_live_label: Callable[[object], bool],
    plan: str,
    used_this_month: int,
) -> BulkPlan:
    """Split the merchant's selection, kept in the order shown, into what we buy and what we don't."""
    already_labelled, candidates = [], []
    for item in items:
        (already_labelled if has_live_label(item.order) else candidates).append(item)

    allowance = monthly_allowance(plan)
    if allowance is None:
        return BulkPlan(candidates, already_labelled, [], None)
    remaining = max(allowance - used_this_month, 0)
    return BulkPlan(candidates[:remaining], already_labelled, candidates[remaining:], remaining)


def idempotency_key(job_id: str, order_id: str) -> str:
    """Stable for the order within one bulk job, so a retried job never buys the same order twice."""
    return f"bulk:{job_id}:{order_id}"


def per_minute_pacer(
    limit: int,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[], None]:
    """Spaces calls evenly so no more than `limit` start in any minute."""
    interval = 60.0 / limit
    next_allowed: list[float | None] = [None]

    def pace() -> None:
        now = clock()
        if next_allowed[0] is not None and now < next_allowed[0]:
            sleep(next_allowed[0] - now)
            now = next_allowed[0]
        next_allowed[0] = now + interval

    return pace


def carrier_pacer(**pacer_kwargs) -> Callable[[str], None]:
    """USPS is held to USPS_BULK_PER_MINUTE. Other carriers have no agreed limit and are not slowed down."""
    usps = per_minute_pacer(USPS_BULK_PER_MINUTE, **pacer_kwargs)

    def pace(carrier: str) -> None:
        if carrier == "usps":
            usps()

    return pace


def buy_all(
    items: list[BulkItem],
    *,
    job_id: str,
    pace: Callable[[str], None],
    has_live_label: Callable[[object], bool],
    on_result: Callable[[BulkItem, Label | Exception], None] = lambda item, outcome: None,
) -> BulkResult:
    """Buy each item in order. `on_result` is called after every order so progress can be saved as it happens.

    `has_live_label` is checked again right before each purchase: the order may have been labelled since the job
    was queued, and an order with a live label never gets a second one (fea8c5c7ec77)."""
    result = BulkResult()
    for item in items:
        pace(item.rate.carrier)
        if has_live_label(item.order):
            result.already_labelled.append(item.order.id)
            on_result(item, AlreadyLabelled(item.order.id))
            continue
        try:
            label = purchase_label(
                item.order,
                item.rate,
                idempotency_key=idempotency_key(job_id, item.order.id),
                shown_price=item.shown_price,
            )
        except StaleRateError as error:
            result.needs_approval.append(item.order.id)
            on_result(item, error)
            continue
        except CarrierError as error:
            result.failed.append((item.order.id, error))
            on_result(item, error)
            continue
        result.bought.append(label)
        on_result(item, label)
    return result
