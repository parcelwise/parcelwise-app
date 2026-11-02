"""Bulk label buying as a background job (Raven task 051ffb8e9c2d).

The API validates a request and writes a batch (create_batch); one worker process claims batches from Postgres
and buys them serially (work_next_batch). Everything goes through a store so the rules can be tested without a
database; PostgresStore is the real one.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.db import transaction
from app.labels.bulk import (
    ALREADY_LABELED,
    BatchItem,
    Pacer,
    check_allowance,
    check_batch_size,
    order_ids_with_live_label,
    run_item,
    split_already_labeled,
)
from app.labels.rates import Rate


class BulkNotEnabled(Exception):
    """Bulk buying is switched off for this merchant (it is on for Bloom & Co only, decision 3e6a1ad56569)."""


class UnknownOrders(Exception):
    """Some selected orders are not this merchant's unfulfilled orders."""

    def __init__(self, order_ids):
        super().__init__(f"not your unfulfilled orders: {sorted(order_ids)}")
        self.order_ids = set(order_ids)


@dataclass(frozen=True)
class Quote:
    """The rate and price the merchant saw for one order on the confirm screen."""

    order_id: str
    carrier: str
    service: str
    rate_id: str
    price: Decimal
    quoted_at: datetime


def idempotency_key(batch_id, order_id: str) -> str:
    """Stable for the order and the batch, so a worker restart never buys twice (ADR 0004)."""
    return f"batch{batch_id}:{order_id}"


def create_batch(store, merchant_id: str, quotes: list[Quote]) -> dict:
    """Validate a request and queue it. Refuses the whole request before anything is bought or written.

    Order of checks: flag, size (200), the orders are the merchant's, allowance (on orders that will be bought),
    then orders that already have a live label are recorded as skipped.
    """
    merchant = store.get_merchant(merchant_id)
    if not merchant["bulk_labels_enabled"]:
        raise BulkNotEnabled(merchant_id)
    order_ids = [q.order_id for q in quotes]
    check_batch_size(order_ids)
    unknown = set(order_ids) - store.unfulfilled_order_ids(merchant_id, order_ids)
    if unknown:
        raise UnknownOrders(unknown)
    to_buy_ids, skipped = split_already_labeled(order_ids, store.live_label_order_ids(order_ids))
    check_allowance(merchant["plan"], merchant["labels_this_month"], len(to_buy_ids))
    skipped_reasons = dict(skipped)
    batch_id = store.create_batch(merchant_id, quotes, skipped_reasons)
    return {
        "batch_id": batch_id,
        "to_buy": len(to_buy_ids),
        "skipped": [{"order_id": o, "reason": r} for o, r in skipped],
    }


def work_next_batch(store, load_order, *, pacer: Pacer | None = None) -> bool:
    """Claim one batch and buy its pending items serially. Returns False when there is nothing to do.

    A batch left running by a crashed worker is claimed again and only its still-pending items are bought; each
    item uses the same idempotency key, so the carrier will not charge twice.
    """
    batch = store.claim_next_batch()
    if batch is None:
        return False
    pacer = pacer or Pacer()
    for row in store.pending_items(batch["id"]):
        order_id = row["order_id"]
        if store.live_label_order_ids([order_id]):
            store.record_skipped(batch["id"], order_id, ALREADY_LABELED)
            continue
        pacer.wait()
        rate = Rate(row["carrier"], row["service"], row["price"], row["quoted_at"], row["rate_id"])
        item = BatchItem(load_order(order_id), rate, row["price"], idempotency_key(batch["id"], order_id))
        result = run_item(item)
        if result.bought:
            store.record_bought(batch["id"], batch["merchant_id"], result.label, item.idempotency_key)
        else:
            store.record_skipped(batch["id"], order_id, result.reason)
    store.finish_batch(batch["id"])
    return True


def batch_progress(store, merchant_id: str, batch_id) -> dict:
    """What the merchant watches: batch status plus one row per order (bought, skipped with why, or pending)."""
    batch, items = store.batch_with_items(merchant_id, batch_id)
    counts = {"bought": 0, "skipped": 0, "pending": 0}
    for item in items:
        counts[item["status"]] += 1
    return {"batch_id": batch_id, "status": batch["status"], "counts": counts, "items": items}


class PostgresStore:
    def __init__(self, tx=transaction):
        self._tx = tx

    def get_merchant(self, merchant_id):
        with self._tx() as conn:
            row = conn.execute(
                "SELECT plan, labels_this_month, bulk_labels_enabled FROM merchants WHERE id = %s", (merchant_id,)
            ).fetchone()
        return {"plan": row[0], "labels_this_month": row[1], "bulk_labels_enabled": row[2]}

    def unfulfilled_order_ids(self, merchant_id, order_ids):
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT id FROM orders WHERE merchant_id = %s AND status = 'unfulfilled' AND id = ANY(%s)",
                (merchant_id, list(order_ids)),
            ).fetchall()
        return {r[0] for r in rows}

    def live_label_order_ids(self, order_ids):
        with self._tx() as conn:
            return order_ids_with_live_label(conn, order_ids)

    def create_batch(self, merchant_id, quotes, skipped):
        """`quotes` are in the order the merchant selected; `skipped` maps order id to why it will not be bought."""
        with self._tx() as conn:
            batch_id = conn.execute(
                "INSERT INTO label_batches (merchant_id) VALUES (%s) RETURNING id", (merchant_id,)
            ).fetchone()[0]
            for position, q in enumerate(quotes):
                order_id = q.order_id
                status, reason = ("skipped", skipped[order_id]) if order_id in skipped else ("pending", "")
                conn.execute(
                    "INSERT INTO label_batch_items (batch_id, order_id, position, carrier, service, rate_id, price,"
                    " quoted_at, status, reason) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (batch_id, order_id, position, q.carrier, q.service, q.rate_id, q.price, q.quoted_at,
                     status, reason),
                )
        return batch_id

    def claim_next_batch(self):
        with self._tx() as conn:
            row = conn.execute(
                "UPDATE label_batches SET status = 'running', started_at = COALESCE(started_at, now()) "
                "WHERE id = (SELECT id FROM label_batches WHERE status IN ('pending', 'running') "
                "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id, merchant_id"
            ).fetchone()
        return {"id": row[0], "merchant_id": row[1]} if row else None

    def pending_items(self, batch_id):
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT order_id, carrier, service, rate_id, price, quoted_at FROM label_batch_items "
                "WHERE batch_id = %s AND status = 'pending' ORDER BY position",
                (batch_id,),
            ).fetchall()
        keys = ("order_id", "carrier", "service", "rate_id", "price", "quoted_at")
        return [dict(zip(keys, r)) for r in rows]

    def record_bought(self, batch_id, merchant_id, label, key):
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO labels (order_id, carrier, tracking_number, price, pdf_url, idempotency_key) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (label.order_id, label.carrier, label.tracking_number, label.price, label.pdf_url, key),
            )
            conn.execute(
                "UPDATE merchants SET labels_this_month = labels_this_month + 1 WHERE id = %s", (merchant_id,)
            )
            conn.execute(
                "UPDATE label_batch_items SET status = 'bought', tracking_number = %s "
                "WHERE batch_id = %s AND order_id = %s",
                (label.tracking_number, batch_id, label.order_id),
            )

    def record_skipped(self, batch_id, order_id, reason):
        with self._tx() as conn:
            conn.execute(
                "UPDATE label_batch_items SET status = 'skipped', reason = %s WHERE batch_id = %s AND order_id = %s",
                (reason, batch_id, order_id),
            )

    def finish_batch(self, batch_id):
        with self._tx() as conn:
            conn.execute("UPDATE label_batches SET status = 'done', finished_at = now() WHERE id = %s", (batch_id,))

    def batch_with_items(self, merchant_id, batch_id):
        with self._tx() as conn:
            batch = conn.execute(
                "SELECT status FROM label_batches WHERE id = %s AND merchant_id = %s", (batch_id, merchant_id)
            ).fetchone()
            rows = conn.execute(
                "SELECT order_id, status, reason, tracking_number FROM label_batch_items WHERE batch_id = %s "
                "ORDER BY position",
                (batch_id,),
            ).fetchall()
        if batch is None:
            raise LookupError(batch_id)
        keys = ("order_id", "status", "reason", "tracking_number")
        return {"status": batch[0]}, [dict(zip(keys, r)) for r in rows]
