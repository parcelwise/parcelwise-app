"""Read queries for the Orders page."""

PAGE_SIZE = 50


def unfulfilled_orders(conn, merchant_id: str, *, page: int = 0):
    return conn.execute(
        "SELECT * FROM orders WHERE merchant_id = %s AND status = 'unfulfilled' ORDER BY created_at LIMIT %s OFFSET %s",
        (merchant_id, PAGE_SIZE, page * PAGE_SIZE),
    ).fetchall()


def search_orders(conn, merchant_id: str, query: str):
    like = f"%{query}%"
    return conn.execute(
        "SELECT * FROM orders WHERE merchant_id = %s AND (sku ILIKE %s OR customer_name ILIKE %s) "
        "ORDER BY created_at DESC LIMIT %s",
        (merchant_id, like, like, PAGE_SIZE),
    ).fetchall()


SELECT_ALL_LIMIT = 200  # "select all matching" stops here for bulk label buying (Raven decision 86e92e31bc0d)


def unfulfilled_order_ids(conn, merchant_id: str, *, limit: int = SELECT_ALL_LIMIT):
    """Ids behind "select all N matching": the oldest `limit` unfulfilled orders, plus the total count."""
    limit = min(limit, SELECT_ALL_LIMIT)
    ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM orders WHERE merchant_id = %s AND status = 'unfulfilled' ORDER BY created_at LIMIT %s",
            (merchant_id, limit),
        ).fetchall()
    ]
    total = conn.execute(
        "SELECT count(*) FROM orders WHERE merchant_id = %s AND status = 'unfulfilled'", (merchant_id,)
    ).fetchone()[0]
    return {"ids": ids, "total": total, "limit": limit}
