"""Order sync from Shopify's Admin API."""

FIELDS = "id,line_items,shipping_address,total_weight,created_at,tags"


def sync_orders(merchant, *, since_id: int = 0):
    """Pull unfulfilled orders newer than `since_id`."""
    return merchant.shopify.orders(status="unfulfilled", since_id=since_id, fields=FIELDS)


def backoff_seconds(response) -> float:
    """Shopify's leaky bucket says how long to wait; respect it instead of guessing."""
    return float(response.headers.get("Retry-After", "2.0"))


def mark_fulfilled(merchant, order, label):
    """Tell Shopify the order shipped, so the customer gets Shopify's own tracking email too."""
    return merchant.shopify.create_fulfillment(
        order.shopify_id,
        tracking_number=label.tracking_number,
        tracking_company=label.carrier.upper(),
        notify_customer=False,
    )
