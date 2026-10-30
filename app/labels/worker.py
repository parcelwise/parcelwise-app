"""The label worker: runs queued bulk label batches from Postgres (ADR 0005). One instance, one batch at a time."""

import time

from app.core import db
from app.labels.bulk import BulkItem, buy_labels
from app.labels.rates import Rate

IDLE_SECONDS = 2


class BatchStore:
    """The label_batches tables. Each call commits on its own, so the Orders page sees progress as it happens."""

    def __init__(self, transaction):
        self.transaction = transaction

    def requeue_running(self) -> None:
        # Only one worker runs, so a batch still marked running was cut off by a restart. Items already bought
        # are not pending any more, and the rest reuse their idempotency keys, so nothing is bought twice.
        with self.transaction() as conn:
            conn.execute("UPDATE label_batches SET status = 'queued', started_at = NULL WHERE status = 'running'")

    def claim(self):
        with self.transaction() as conn:
            row = conn.execute(
                "UPDATE label_batches SET status = 'running', started_at = now() WHERE id = ("
                "  SELECT b.id FROM label_batches b WHERE b.status = 'queued' AND NOT EXISTS ("
                "    SELECT 1 FROM label_batches r WHERE r.merchant_id = b.merchant_id AND r.status = 'running')"
                "  ORDER BY b.created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                ") RETURNING id",
            ).fetchone()
        return row[0] if row else None

    def pending_items(self, batch_id: str) -> list[tuple]:
        with self.transaction() as conn:
            return conn.execute(
                "SELECT order_id, carrier, service, price, quoted_at, rate_id, shown_price FROM label_batch_items "
                "WHERE batch_id = %s AND status = 'pending' ORDER BY position",
                (batch_id,),
            ).fetchall()

    def record(self, batch_id: str, order_id: str, status: str, label_or_error) -> None:
        with self.transaction() as conn:
            if status == "bought":
                label = label_or_error
                conn.execute(
                    "INSERT INTO labels (order_id, carrier, tracking_number, price, pdf_url, idempotency_key) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
                    (order_id, label.carrier, label.tracking_number, label.price, label.pdf_url, f"{batch_id}:{order_id}"),
                )
                tracking, error = label.tracking_number, None
            else:
                tracking, error = None, label_or_error
            conn.execute(
                "UPDATE label_batch_items SET status = %s, tracking_number = %s, error = %s "
                "WHERE batch_id = %s AND order_id = %s",
                (status, tracking, error, batch_id, order_id),
            )

    def finish(self, batch_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE label_batches SET status = 'done', finished_at = now() WHERE id = %s", (batch_id,))


def run_batch(store, batch_id: str, *, load_order, sleep=time.sleep, clock=time.monotonic):
    """`load_order(order_id)` returns the order with its merchant's carrier accounts, as the single-label route does."""
    items = [
        BulkItem(load_order(order_id), Rate(carrier, service, price, quoted_at, rate_id), shown_price)
        for order_id, carrier, service, price, quoted_at, rate_id, shown_price in store.pending_items(batch_id)
    ]
    result = buy_labels(
        items,
        batch_id=batch_id,
        record=lambda order_id, status, detail: store.record(batch_id, order_id, status, detail),
        sleep=sleep,
        clock=clock,
    )
    store.finish(batch_id)
    return result


def run_forever(*, load_order) -> None:
    store = BatchStore(db.transaction)
    store.requeue_running()
    while True:
        batch_id = store.claim()
        if batch_id is None:
            time.sleep(IDLE_SECONDS)
            continue
        run_batch(store, batch_id, load_order=load_order)


if __name__ == "__main__":
    # The single-label route loads an order with its merchant's carrier accounts outside this repo; the worker
    # needs the same loader passed to run_forever() before this service can start.
    raise SystemExit("label-worker: pass load_order to run_forever() before deploying")
