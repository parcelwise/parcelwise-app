"""Order sync from Shopify's Admin API."""

FIELDS = "id,line_items,shipping_address,total_weight,created_at,tags"


def sync_orders(merchant, *, since_id: int = 0):
    """Pull unfulfilled orders newer than `since_id`."""
    return merchant.shopify.orders(status="unfulfilled", since_id=since_id, fields=FIELDS)
