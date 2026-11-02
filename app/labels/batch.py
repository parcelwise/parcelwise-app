"""Buying labels for many orders at once.

Decisions this follows (Raven task 444e8aaa568e):
- Each order is bought on its own through purchase_label() with its own idempotency key (ADR 0004; 52a409283ec9).
- The merchant approves each order's price and the total. An order whose quote went stale or changed is not bought;
  it comes back for the merchant to approve at the new price (ADR 0003; Priya Shah, 127744d2a249).
- If the batch would go over the plan's monthly allowance, refuse all of it before buying anything and say how many
  labels are left (f899fd2228ff; Marcus Lee, d3832281ff8c).
- An order that already has a label that hasn't been voided is skipped and offered for reprint (27fca17c0708;
  Jordan Okafor, 4c1b3863122b).
- Labels that bought are kept; failures are reported and the merchant can retry them (Jordan Okafor, d0d3c77d4339).
- At most 500 orders per batch (Lena Park, 21777abe92a1).
- An order that is no longer unfulfilled when the batch is created is dropped and listed; the rest are bought
  (Jordan Okafor, fd71f63d5869).
- A merchant retry gets a new idempotency key, except after a carrier timeout, which reuses the last key so a label
  the carrier did issue comes back instead of being bought twice (Priya Shah, 8b0453dcb636; Jordan Okafor,
  271f3d26c255). A timed-out order is retried at its original price; if that quote has expired, the merchant is
  asked for a new price (Priya Shah, e270d6d52253).
- The batch is a job in Postgres, worked by the label-worker service (Marcus Lee, a6f8e89cd82c); see worker.py.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.billing.plans import labels_left
from app.labels.carriers import CarrierError
from app.labels.purchase import Label, StaleRateError, purchase_label
from app.labels.rates import Rate, quote_is_fresh

MAX_BATCH_ORDERS = 500

QUEUED = "queued"
BOUGHT = "bought"
ALREADY_LABELED = "already_labeled"
NEEDS_REQUOTE = "needs_requote"
FAILED = "failed"
# Fulfilled or cancelled between selecting it and clicking Buy. Not bought, not retryable.
NO_LONGER_UNFULFILLED = "no_longer_unfulfilled"
RETRYABLE = (NEEDS_REQUOTE, FAILED)


class BatchRefused(Exception):
    """Nothing was bought. `labels_left` is set when the plan's monthly allowance is the reason."""

    def __init__(self, message: str, *, labels_left: int | None = None):
        super().__init__(message)
        self.labels_left = labels_left


@dataclass(frozen=True)
class BatchItem:
    order: object
    rate: Rate
    # The price the merchant saw for this order on the confirm screen.
    shown_price: Decimal


@dataclass(frozen=True)
class BatchPlan:
    to_buy: list[BatchItem]
    # Orders with a label that hasn't been voided: offered for reprint, never bought again.
    already_labeled: list[BatchItem]
    # Orders that are no longer unfulfilled: dropped and listed, never bought.
    dropped: list[BatchItem]


@dataclass(frozen=True)
class ItemOutcome:
    status: str
    label: Label | None = None
    error: str = ""
    # The carrier timed out (or 5xx'd) after our one retry, so it may have issued the label. The next attempt reuses
    # this attempt's key instead of getting a new one (Jordan Okafor, 271f3d26c255).
    timed_out: bool = False


def batch_idempotency_key(batch_id: str, order_id: str, attempt: int) -> str:
    """Stable for the order and the attempt (ADR 0004). A merchant's retry is a new attempt with a new key, so the
    label is bought at the newly approved price (Priya Shah, Raven 8b0453dcb636). Two cases keep the attempt number,
    and so the key, so the carrier returns a label it already issued instead of buying another: a worker crash before
    the result is saved, and a carrier timeout (Jordan Okafor, 271f3d26c255)."""
    return f"batch:{batch_id}:{order_id}:{attempt}"


def plan_batch(
    items: list[BatchItem],
    *,
    plan: str,
    used_this_month: int,
    labeled_order_ids: set[str],
    closed_order_ids: frozenset[str] | set[str] = frozenset(),
) -> BatchPlan:
    """Decide what a batch will buy, or refuse it whole. Buys nothing.

    `used_this_month` counts labels already bought this month plus labels other batches have queued.
    `closed_order_ids` are orders that are no longer unfulfilled; they are dropped, not bought.
    """
    if not items:
        raise BatchRefused("Select at least one order.")
    if len(items) > MAX_BATCH_ORDERS:
        raise BatchRefused(f"A batch can have at most {MAX_BATCH_ORDERS} orders. Narrow the filter and try again.")
    order_ids = [item.order.id for item in items]
    if len(set(order_ids)) != len(order_ids):
        raise BatchRefused("An order appears more than once.")
    dropped = [item for item in items if item.order.id in closed_order_ids]
    open_items = [item for item in items if item.order.id not in closed_order_ids]
    already = [item for item in open_items if item.order.id in labeled_order_ids]
    to_buy = [item for item in open_items if item.order.id not in labeled_order_ids]
    left = labels_left(plan, used_this_month)
    if left is not None and len(to_buy) > left:
        raise BatchRefused(
            f"This would buy {len(to_buy)} labels, but your plan has {left} left this month. Nothing was bought.",
            labels_left=left,
        )
    return BatchPlan(to_buy=to_buy, already_labeled=already, dropped=dropped)


def timed_out_retry(requested: BatchItem, original: BatchItem) -> BatchItem | None:
    """The item to retry for an order whose last attempt timed out at the carrier.

    It keeps the original rate and price, not the one the merchant just approved: the retry reuses the last key, so a
    label the carrier already issued comes back at what it cost (Priya Shah, Raven e270d6d52253). Returns None if that
    quote has expired; the order then needs a new price, and a new price gets a new key (Jordan Okafor, 271f3d26c255).
    """
    if not quote_is_fresh(original.rate):
        return None
    return BatchItem(requested.order, original.rate, original.shown_price)


def run_item(batch_id: str, item: BatchItem, *, attempt: int, has_live_label: bool) -> ItemOutcome:
    """Buy the label for one order of a batch. The only way a batch buys anything."""
    if has_live_label:
        return ItemOutcome(ALREADY_LABELED)
    try:
        label = purchase_label(
            item.order,
            item.rate,
            idempotency_key=batch_idempotency_key(batch_id, item.order.id, attempt),
            shown_price=item.shown_price,
        )
    except StaleRateError:
        return ItemOutcome(NEEDS_REQUOTE, error="The price changed or the quote expired. Approve the new price.")
    except CarrierError as error:
        return ItemOutcome(FAILED, error=str(error), timed_out=error.retryable)
    return ItemOutcome(BOUGHT, label=label)


# --- Postgres -------------------------------------------------------------------------------------------------------


def _live_label_order_ids(conn, order_ids: list[str]) -> set[str]:
    rows = conn.execute(
        "SELECT order_id FROM labels WHERE order_id = ANY(%s) AND voided_at IS NULL", (order_ids,)
    ).fetchall()
    return {row[0] for row in rows}


def _queued_elsewhere(conn, merchant_id: str, order_ids: list[str], *, batch_id: str | None = None) -> set[str]:
    rows = conn.execute(
        "SELECT order_id FROM label_batch_items WHERE merchant_id = %s AND status = 'queued' "
        "AND order_id = ANY(%s) AND batch_id IS DISTINCT FROM %s",
        (merchant_id, order_ids, batch_id),
    ).fetchall()
    return {row[0] for row in rows}


def _used_this_month(conn, merchant_id: str) -> tuple[str, int]:
    """The merchant's plan and labels used this month, counting labels other batches have queued.

    Locks the merchant row so two batches can't both pass the allowance check.
    """
    plan, bought = conn.execute(
        "SELECT plan, labels_this_month FROM merchants WHERE id = %s FOR UPDATE", (merchant_id,)
    ).fetchone()
    (queued,) = conn.execute(
        "SELECT count(*) FROM label_batch_items WHERE merchant_id = %s AND status = 'queued'", (merchant_id,)
    ).fetchone()
    return plan, bought + queued


def _closed_order_ids(conn, merchant_id: str, order_ids: list[str]) -> set[str]:
    """Selected orders that are no longer unfulfilled. Raises if any isn't this merchant's order at all."""
    rows = conn.execute(
        "SELECT id, status FROM orders WHERE merchant_id = %s AND id = ANY(%s)", (merchant_id, order_ids)
    ).fetchall()
    statuses = dict(rows)
    if len(statuses) != len(set(order_ids)):
        raise BatchRefused("Some of these orders weren't found. Refresh the page and try again.")
    return {order_id for order_id, status in statuses.items() if status != "unfulfilled"}


def _set_item(conn, batch_id: str, item: BatchItem, status: str) -> None:
    conn.execute(
        "UPDATE label_batch_items SET status = %s, carrier = %s, service = %s, rate_id = %s, rate_price = %s, "
        "quoted_at = %s, shown_price = %s, error = NULL, updated_at = now() WHERE batch_id = %s AND order_id = %s",
        (
            status,
            item.rate.carrier,
            item.rate.service,
            item.rate.rate_id,
            item.rate.price,
            item.rate.quoted_at,
            item.shown_price,
            batch_id,
            item.order.id,
        ),
    )


def _needs_new_price(conn, batch_id: str, order_id: str) -> None:
    """A timed-out order whose original quote expired: ask for a new price. That finishes the attempt, so the order is
    bought with a new key at the new price."""
    conn.execute(
        "UPDATE label_batch_items SET status = %s, timed_out = false, attempts = attempts + 1, error = %s, "
        "updated_at = now() WHERE batch_id = %s AND order_id = %s",
        (
            NEEDS_REQUOTE,
            "The carrier didn't answer and the quote has expired. Approve a new price.",
            batch_id,
            order_id,
        ),
    )


def create_batch(conn, merchant_id: str, items: list[BatchItem]) -> str:
    """Queue a batch for the label-worker, or raise BatchRefused having queued nothing."""
    order_ids = [item.order.id for item in items]
    plan_name, used = _used_this_month(conn, merchant_id)
    closed = _closed_order_ids(conn, merchant_id, order_ids) if items else set()
    labeled = _live_label_order_ids(conn, order_ids) | _queued_elsewhere(conn, merchant_id, order_ids)
    plan = plan_batch(items, plan=plan_name, used_this_month=used, labeled_order_ids=labeled, closed_order_ids=closed)
    batch_id = uuid.uuid4().hex
    conn.execute("INSERT INTO label_batches (id, merchant_id) VALUES (%s, %s)", (batch_id, merchant_id))
    for status, group in (
        (QUEUED, plan.to_buy),
        (ALREADY_LABELED, plan.already_labeled),
        (NO_LONGER_UNFULFILLED, plan.dropped),
    ):
        for item in group:
            conn.execute(
                "INSERT INTO label_batch_items (batch_id, order_id, merchant_id, status, carrier, service, rate_id, "
                "rate_price, quoted_at, shown_price) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    batch_id,
                    item.order.id,
                    merchant_id,
                    status,
                    item.rate.carrier,
                    item.rate.service,
                    item.rate.rate_id,
                    item.rate.price,
                    item.rate.quoted_at,
                    item.shown_price,
                ),
            )
    return batch_id


def retry_items(conn, merchant_id: str, batch_id: str, items: list[BatchItem]) -> None:
    """Queue failed or re-priced orders again, each at the fresh price the merchant just approved."""
    order_ids = [item.order.id for item in items]
    rows = conn.execute(
        "SELECT order_id, status, timed_out, carrier, service, rate_id, rate_price, quoted_at, shown_price "
        "FROM label_batch_items WHERE batch_id = %s AND merchant_id = %s AND order_id = ANY(%s)",
        (batch_id, merchant_id, order_ids),
    ).fetchall()
    stored = {row[0]: row for row in rows}
    if len(stored) != len(set(order_ids)) or any(row[1] not in RETRYABLE for row in stored.values()):
        raise BatchRefused("Only failed orders or orders waiting for a new price can be retried.")
    retry, expired = [], []
    for item in items:
        _, _, timed_out, carrier, service, rate_id, rate_price, quoted_at, shown_price = stored[item.order.id]
        if not timed_out:
            retry.append(item)
            continue
        original = BatchItem(item.order, Rate(carrier, service, rate_price, quoted_at, rate_id), shown_price)
        again = timed_out_retry(item, original)
        if again is None:
            expired.append(item.order.id)
        else:
            retry.append(again)
    for order_id in expired:
        _needs_new_price(conn, batch_id, order_id)
    if not retry:
        return
    items, order_ids = retry, [item.order.id for item in retry]
    plan_name, used = _used_this_month(conn, merchant_id)
    labeled = _live_label_order_ids(conn, order_ids) | _queued_elsewhere(
        conn, merchant_id, order_ids, batch_id=batch_id
    )
    closed = _closed_order_ids(conn, merchant_id, order_ids)
    plan = plan_batch(items, plan=plan_name, used_this_month=used, labeled_order_ids=labeled, closed_order_ids=closed)
    for item in plan.to_buy:
        _set_item(conn, batch_id, item, QUEUED)
    for item in plan.already_labeled:
        _set_item(conn, batch_id, item, ALREADY_LABELED)
    for item in plan.dropped:
        _set_item(conn, batch_id, item, NO_LONGER_UNFULFILLED)


def get_batch(conn, merchant_id: str, batch_id: str) -> dict:
    """Batch progress for the Orders page: every order with its status, price and tracking number or error."""
    rows = conn.execute(
        "SELECT order_id, status, carrier, service, rate_id, shown_price, tracking_number, error, timed_out "
        "FROM label_batch_items "
        "WHERE batch_id = %s AND merchant_id = %s ORDER BY order_id",
        (batch_id, merchant_id),
    ).fetchall()
    items = [
        {
            "order_id": order_id,
            "status": status,
            "carrier": carrier,
            "service": service,
            "rate_id": rate_id,
            "price": str(price),
            "tracking_number": tracking,
            "error": error,
            # Retrying it keeps this price and rate (Priya Shah, Raven e270d6d52253).
            "timed_out": timed_out,
        }
        for order_id, status, carrier, service, rate_id, price, tracking, error, timed_out in rows
    ]
    return {"id": batch_id, "done": all(item["status"] != QUEUED for item in items), "items": items}
