"""HTTP routes for the merchant app. Handlers stay thin and call into app/*."""

ROUTES = {
    ("GET", "/api/orders"): "app.orders.queries:unfulfilled_orders",
    ("POST", "/api/orders/{order_id}/label"): "app.labels.purchase:purchase_label",
    ("POST", "/api/labels/{tracking}/void"): "app.labels.void:void_label",
    ("POST", "/webhooks/stripe"): "app.billing.stripe_webhooks:handle_event",
    ("POST", "/webhooks/shopify"): "app.shopify.webhooks:verify",
    ("GET", "/api/orders/search"): "app.orders.queries:search_orders",
    ("GET", "/api/orders/unfulfilled/ids"): "app.orders.queries:unfulfilled_order_ids",
    ("POST", "/api/labels/bulk"): "app.labels.bulk:start_bulk_purchase",
    ("GET", "/api/labels/bulk/{batch_id}"): "app.labels.bulk:batch_status",
}
