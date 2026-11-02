"""The label-worker service: works through queued batch items, one order at a time.

Runs as a single instance (infra/deploy.yaml), so the in-process rate limiter covers every batch purchase.
A crash between buying and committing leaves the item queued with its attempt count unchanged, so the next run
reuses that attempt's idempotency key and the carrier returns the same label instead of buying another. A carrier
timeout also keeps the attempt count, so the merchant's retry reuses the key (Jordan Okafor, Raven 271f3d26c255).
"""

import time

from app.labels.batch import BOUGHT, BatchItem, _live_label_order_ids, batch_idempotency_key, run_item
from app.labels.ratelimit import PurchaseRateLimiter
from app.labels.rates import Rate

CANDIDATES = 50
IDLE_SECONDS = 2.0


def _claim(conn, limiter: PurchaseRateLimiter):
    """Lock the oldest queued item whose merchant account isn't at its rate limit. Returns (row, wait_seconds)."""
    rows = conn.execute(
        "SELECT batch_id, order_id, merchant_id, carrier, service, rate_id, rate_price, quoted_at, shown_price, "
        "attempts FROM label_batch_items WHERE status = 'queued' ORDER BY updated_at LIMIT %s FOR UPDATE SKIP LOCKED",
        (CANDIDATES,),
    ).fetchall()
    waits = []
    for row in rows:
        wait = limiter.wait_seconds(row[2], row[3])
        if wait == 0:
            return row, 0.0
        waits.append(wait)
    return None, (min(waits) if waits else IDLE_SECONDS)


def work_once(conn, *, load_order, limiter: PurchaseRateLimiter) -> float:
    """Buy at most one queued item. Returns how long to sleep before the next call (0 means go again now)."""
    row, wait = _claim(conn, limiter)
    if row is None:
        return wait
    batch_id, order_id, merchant_id, carrier, service, rate_id, rate_price, quoted_at, shown_price, attempts = row
    item = BatchItem(load_order(conn, order_id), Rate(carrier, service, rate_price, quoted_at, rate_id), shown_price)
    # `attempts` counts finished attempts and is bumped in this same transaction, so a crash reuses this attempt's key.
    # A timeout doesn't finish the attempt: the carrier may have issued the label, so the retry must reuse the key.
    attempt = attempts + 1
    has_live_label = bool(_live_label_order_ids(conn, [order_id]))
    if not has_live_label:
        limiter.record(merchant_id, carrier)
    outcome = run_item(batch_id, item, attempt=attempt, has_live_label=has_live_label)
    if outcome.status == BOUGHT:
        label = outcome.label
        conn.execute(
            "INSERT INTO labels (order_id, carrier, tracking_number, price, pdf_url, idempotency_key) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
            (
                label.order_id,
                label.carrier,
                label.tracking_number,
                label.price,
                label.pdf_url,
                batch_idempotency_key(batch_id, order_id, attempt),
            ),
        )
        conn.execute("UPDATE merchants SET labels_this_month = labels_this_month + 1 WHERE id = %s", (merchant_id,))
    conn.execute(
        "UPDATE label_batch_items SET status = %s, tracking_number = %s, error = %s, attempts = attempts + %s, "
        "updated_at = now() WHERE batch_id = %s AND order_id = %s",
        (
            outcome.status,
            outcome.label.tracking_number if outcome.label else None,
            outcome.error or None,
            0 if outcome.timed_out else 1,
            batch_id,
            order_id,
        ),
    )
    return 0.0


def run_forever(transaction, *, load_order, limiter: PurchaseRateLimiter | None = None, sleep=time.sleep):
    """`transaction` is app.core.db.transaction; `load_order(conn, order_id)` returns the order with its merchant's
    carrier accounts, the same loader the single "Buy label" route uses."""
    limiter = limiter or PurchaseRateLimiter()
    while True:
        with transaction() as conn:
            wait = work_once(conn, load_order=load_order, limiter=limiter)
        if wait:
            sleep(wait)


def main():
    from psycopg_pool import ConnectionPool

    from app.api.wsgi import load_order  # the order loader the single "Buy label" route uses
    from app.core.config import settings
    from app.core.db import init_pool, transaction

    init_pool(lambda: ConnectionPool(settings.database_url))
    run_forever(transaction, load_order=load_order)


if __name__ == "__main__":
    main()
