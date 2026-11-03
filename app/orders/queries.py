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


MAX_BULK_SELECT = 200


def matching_unfulfilled(conn, merchant_id: str):
    """'Select all N matching' for bulk actions: the total, and the first MAX_BULK_SELECT order ids.

    Labels cost real money, so selecting all matching stops at MAX_BULK_SELECT (Lena Park).
    """
    total = conn.execute(
        "SELECT count(*) FROM orders WHERE merchant_id = %s AND status = 'unfulfilled'", (merchant_id,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id FROM orders WHERE merchant_id = %s AND status = 'unfulfilled' ORDER BY created_at LIMIT %s",
        (merchant_id, MAX_BULK_SELECT),
    ).fetchall()
    return total, [row[0] for row in rows]
