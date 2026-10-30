"""Runs bulk label batches (ADR 0005). One batch at a time per process, and one running batch per merchant.

A batch whose worker died is picked up again once its heartbeat is two minutes old. Items still `queued` are
bought again with the same idempotency key, so one that reached the carrier comes back instead of being bought
twice.
"""

import logging
import time

from app.core.db import transaction
from app.labels.batch import Pacer, load_items, run_items, save_item

log = logging.getLogger(__name__)

IDLE_SECONDS = 2

CLAIM_SQL = """
UPDATE label_batches SET status = 'running', heartbeat_at = now()
WHERE id = (
    SELECT b.id FROM label_batches b
    WHERE (b.status = 'queued' OR (b.status = 'running' AND b.heartbeat_at < now() - interval '2 minutes'))
      AND NOT EXISTS (
          SELECT 1 FROM label_batches r WHERE r.merchant_id = b.merchant_id AND r.status = 'running' AND r.id <> b.id
      )
    ORDER BY b.created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING id
"""


def work_once(load_order, *, pacer: Pacer) -> bool:
    """Run the next batch, if there is one. `load_order(order_id)` returns an Order with its merchant."""
    with transaction() as conn:
        row = conn.execute(CLAIM_SQL).fetchone()
        if row is None:
            return False
        batch_id = row[0]
        items = load_items(conn, batch_id)

    def save(item):
        with transaction() as conn:
            save_item(conn, item)
            conn.execute("UPDATE label_batches SET heartbeat_at = now() WHERE id = %s", (batch_id,))

    run_items(items, load_order, pacer=pacer, on_item=save)
    with transaction() as conn:
        conn.execute("UPDATE label_batches SET status = 'done' WHERE id = %s", (batch_id,))
    return True


def main(load_order):
    # One pacer for the process: batches run one after another, so the cap also holds across batch boundaries.
    pacer = Pacer()
    while True:
        try:
            if not work_once(load_order, pacer=pacer):
                time.sleep(IDLE_SECONDS)
        except Exception:
            log.exception("label batch failed; it will be picked up again")
            time.sleep(IDLE_SECONDS)
