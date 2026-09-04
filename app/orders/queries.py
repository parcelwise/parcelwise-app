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
