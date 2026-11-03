"""HTTP routes for the merchant app. Handlers stay thin and call into app/*."""

ROUTES = {
    ("GET", "/api/orders"): "app.orders.queries:unfulfilled_orders",
    ("POST", "/api/orders/{order_id}/label"): "app.labels.purchase:purchase_label",
    ("POST", "/api/labels/{tracking}/void"): "app.labels.void:void_label",
    ("POST", "/api/labels/bulk/quote"): "app.labels.bulk:quote_batch",
    ("POST", "/api/labels/bulk"): "app.labels.bulk_jobs:start_bulk_buy",
    ("GET", "/api/labels/bulk/latest"): "app.labels.bulk_jobs:latest_job",
    ("GET", "/api/labels/bulk/pending-orders"): "app.labels.bulk_jobs:pending_order_ids",
    ("GET", "/api/labels/bulk/{job_id}"): "app.labels.bulk_jobs:get_job",
    ("POST", "/webhooks/stripe"): "app.billing.stripe_webhooks:handle_event",
    ("POST", "/webhooks/shopify"): "app.shopify.webhooks:verify",
    ("GET", "/api/orders/search"): "app.orders.queries:search_orders",
    ("POST", "/api/assistant/ask"): "app.assistant.chat:ask",
    ("GET", "/api/usage"): "app.usage.daily:month_to_date",
}
