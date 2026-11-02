"""Postgres storage for bulk label batches. The API creates batches; the label worker claims and runs them."""

from decimal import Decimal

from app.billing.plans import labels_left
from app.labels.batch import BOUGHT, BatchItem, plan_batch
from app.labels.live import orders_with_live_labels
from app.labels.rates import Rate

# A running batch whose worker hasn't checked in for this long is picked up again. Its bought items are saved,
# and every purchase uses an idempotency key that is stable for the order and the batch, so resuming is safe.
STALE_HEARTBEAT = "5 minutes"


def create_label_batch(conn, merchant_id: str, selections: list[dict]) -> dict:
    """Queue a bulk buy. `selections` are what the merchant approved on the confirm screen, in the order shown:
    {order_id, carrier, service, rate_id, price, quoted_at}."""
    plan, used = conn.execute("SELECT plan, labels_this_month FROM merchants WHERE id = %s", (merchant_id,)).fetchone()
    owned = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM orders WHERE merchant_id = %s AND id = ANY(%s)",
            (merchant_id, [s["order_id"] for s in selections]),
        ).fetchall()
    }
    items = [
        BatchItem(
            order_id=s["order_id"],
            position=position,
            rate=Rate(s["carrier"], s["service"], Decimal(str(s["price"])), s["quoted_at"], s["rate_id"]),
            shown_price=Decimal(str(s["price"])),
        )
        for position, s in enumerate(selections)
        if s["order_id"] in owned
    ]
    live = orders_with_live_labels(conn, [item.order_id for item in items])
    plan_batch(items, live_order_ids=live, plan=plan, used_this_month=used)
    (batch_id,) = conn.execute(
        "INSERT INTO label_batches (merchant_id) VALUES (%s) RETURNING id", (merchant_id,)
    ).fetchone()
    for item in items:
        conn.execute(
            "INSERT INTO label_batch_items (batch_id, order_id, position, carrier, service, rate_id, shown_price, "
            "quoted_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                batch_id,
                item.order_id,
                item.position,
                item.rate.carrier,
                item.rate.service,
                item.rate.rate_id,
                item.shown_price,
                item.rate.quoted_at,
                item.status,
            ),
        )
    return {"batch_id": batch_id, "items": [_item_json(item) for item in items]}


def get_label_batch(conn, merchant_id: str, batch_id: int) -> dict | None:
    row = conn.execute(
        "SELECT status FROM label_batches WHERE id = %s AND merchant_id = %s", (batch_id, merchant_id)
    ).fetchone()
    if row is None:
        return None
    return {"batch_id": batch_id, "status": row[0], "items": [_item_json(item) for item in load_items(conn, batch_id)]}


def claim_next_batch(conn):
    """Claim the oldest queued batch, or a running one whose worker stopped checking in. None if there is none."""
    row = conn.execute(
        "SELECT id, merchant_id FROM label_batches "
        "WHERE status = 'queued' OR (status = 'running' AND heartbeat_at < now() - %s::interval) "
        "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED",
        (STALE_HEARTBEAT,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE label_batches SET status = 'running', heartbeat_at = now() WHERE id = %s", (row[0],))
    return row[0], row[1]


def labels_left_now(conn, merchant_id: str):
    plan, used = conn.execute("SELECT plan, labels_this_month FROM merchants WHERE id = %s", (merchant_id,)).fetchone()
    return labels_left(plan, used)


def load_items(conn, batch_id: int) -> list[BatchItem]:
    rows = conn.execute(
        "SELECT order_id, position, carrier, service, rate_id, shown_price, quoted_at, status, tracking_number, error "
        "FROM label_batch_items WHERE batch_id = %s ORDER BY position",
        (batch_id,),
    ).fetchall()
    return [
        BatchItem(
            order_id=r[0],
            position=r[1],
            rate=Rate(r[2], r[3], Decimal(r[5]), r[6], r[4]),
            shown_price=Decimal(r[5]),
            status=r[7],
            tracking_number=r[8] or "",
            error=r[9] or "",
        )
        for r in rows
    ]


def save_item(conn, batch_id: int, merchant_id: str, item: BatchItem, label, *, idempotency_key: str) -> None:
    """Save one item's outcome. For a bought label, record it and count it against this month's allowance."""
    if item.status == BOUGHT and label is not None:
        conn.execute(
            "INSERT INTO labels (order_id, carrier, tracking_number, price, pdf_url, idempotency_key) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
            (label.order_id, label.carrier, label.tracking_number, label.price, label.pdf_url, idempotency_key),
        )
        conn.execute("UPDATE merchants SET labels_this_month = labels_this_month + 1 WHERE id = %s", (merchant_id,))
    conn.execute(
        "UPDATE label_batch_items SET status = %s, tracking_number = %s, error = %s WHERE batch_id = %s AND order_id = %s",
        (item.status, item.tracking_number or None, item.error or None, batch_id, item.order_id),
    )
    conn.execute("UPDATE label_batches SET heartbeat_at = now() WHERE id = %s", (batch_id,))


def finish_batch(conn, batch_id: int) -> None:
    conn.execute("UPDATE label_batches SET status = 'done', finished_at = now() WHERE id = %s", (batch_id,))


def _item_json(item: BatchItem) -> dict:
    return {
        "orderId": item.order_id,
        "position": item.position,
        "carrier": item.rate.carrier,
        "service": item.rate.service,
        "price": str(item.shown_price),
        "status": item.status,
        "trackingNumber": item.tracking_number,
        "error": item.error,
    }
