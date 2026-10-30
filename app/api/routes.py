"""HTTP routes for the merchant app. Handlers stay thin and call into app/*."""

ROUTES = {
    ("GET", "/api/orders"): "app.orders.queries:unfulfilled_orders",
    ("POST", "/api/orders/{order_id}/label"): "app.labels.purchase:purchase_label",
    ("POST", "/api/labels/{tracking}/void"): "app.labels.void:void_label",
    ("POST", "/api/labels/batches"): "app.labels.batch:create_batch",
    ("GET", "/api/labels/batches/{batch_id}"): "app.labels.batch:batch_status",
    ("POST", "/api/labels/batches/{batch_id}/retry"): "app.labels.batch:retry_batch",
    ("POST", "/webhooks/stripe"): "app.billing.stripe_webhooks:handle_event",
    ("POST", "/webhooks/shopify"): "app.shopify.webhooks:verify",
    ("GET", "/api/orders/search"): "app.orders.queries:search_orders",
}
