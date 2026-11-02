"""Which orders already have a label that hasn't been voided."""


def orders_with_live_labels(conn, order_ids: list[str]) -> set[str]:
    """The subset of `order_ids` that already have a live (not voided) label."""
    if not order_ids:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT order_id FROM labels WHERE order_id = ANY(%s) AND voided_at IS NULL",
        (list(order_ids),),
    ).fetchall()
    return {row[0] for row in rows}
