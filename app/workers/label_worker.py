"""The label worker: claims bulk label batches from Postgres and buys them one order at a time.

Run one instance (infra/deploy.yaml, service label-worker). The USPS limit of 40 purchases a minute per merchant is
enforced in this process, so scaling it past one instance would need a shared limiter first.
"""

import time

from app.core.db import transaction
from app.labels import batch_store
from app.labels.batch import PerMinuteLimiter, idempotency_key, run_batch

IDLE_SECONDS = 2


def run_once(*, load_order, limiter: PerMinuteLimiter, tx=transaction) -> bool:
    """Run one batch if there is one. Returns False when the queue is empty."""
    with tx() as conn:
        claimed = batch_store.claim_next_batch(conn)
    if claimed is None:
        return False
    batch_id, merchant_id = claimed
    with tx() as conn:
        items = batch_store.load_items(conn, batch_id)
        labels_left = batch_store.labels_left_now(conn, merchant_id)

    def save(item, label):
        # One transaction per order, so a crash loses at most the order in flight; its idempotency key covers that.
        with tx() as conn:
            batch_store.save_item(
                conn, batch_id, merchant_id, item, label, idempotency_key=idempotency_key(batch_id, item.order_id)
            )

    run_batch(
        batch_id,
        merchant_id,
        items,
        load_order=load_order,
        labels_left=labels_left,
        limiter=limiter,
        on_item=save,
    )
    with tx() as conn:
        batch_store.finish_batch(conn, batch_id)
    return True


def run_forever(*, load_order, sleep=time.sleep) -> None:
    limiter = PerMinuteLimiter()
    while True:
        if not run_once(load_order=load_order, limiter=limiter):
            sleep(IDLE_SECONDS)


if __name__ == "__main__":
    # The worker needs the same order loader the single-purchase route uses (an Order whose merchant carries its
    # carrier accounts). That wiring lives with app.api.wsgi, which is not in this repository.
    raise SystemExit("label-worker: pass load_order to run_forever() from the app's wiring module")
