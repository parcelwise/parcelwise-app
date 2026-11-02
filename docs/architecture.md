# Architecture

Parcelwise buys shipping labels for Shopify merchants. A merchant connects their shop, we pull unfulfilled
orders, quote rates from their carrier accounts, and buy labels when they click **Buy label**.

```
Shopify ──webhooks──▶ app/shopify ──▶ orders (Postgres) ──▶ web/orders (Next.js)
                                                     │
                                         Buy label   ▼
                                  app/labels/purchase.py ──▶ carrier APIs (USPS, UPS)
                                                     │
                                                     ▼
                                       labels (Postgres) + label PDFs (S3)
```

## Services

| Service | What it does | Owner |
| --- | --- | --- |
| `app/api` | HTTP API for the dashboard and webhooks | Platform |
| `app/labels` | Rates, purchases, voids, PDFs | Labels |
| `app/orders` | Orders as we store them | Labels, Dashboard |
| `app/shopify` | Order sync and webhooks | Integrations |
| `app/billing` | Plans, allowances, Stripe | Revenue, Platform |
| `web/` | Merchant dashboard | Dashboard |

## Rules that hold everywhere

- Money is `Decimal`, never `float`.
- Every label purchase goes through `purchase_label()` (see [ADR 0002](adr/0002-carrier-clients-behind-a-registry.md)).
- A merchant sees the price before we buy ([ADR 0003](adr/0003-merchant-sees-the-price-first.md)).

## Background work

Shopify sync runs on a five-minute cron. Shipping confirmation emails go out through Postmark right after a
purchase. Stripe webhooks update the merchant's plan.

Buying labels for many orders at once (up to 500) is a job in Postgres (`label_batches`, `label_batch_items`).
The `label-worker` service (`app/labels/worker.py`, one instance) buys each order through `purchase_label()`,
at most 40 USPS purchases a minute per merchant account (on startup the worker counts the last minute's attempts
from the database, so a restart doesn't reset the limit). Before queuing, the whole batch is refused if it would go
over the plan's monthly allowance. Orders that already have a live label are skipped for reprint. Orders whose
quote expires or changes are returned for the merchant to approve the new price, and failures are reported for
retry; labels that bought are kept. Orders fulfilled or cancelled after they were selected, or while the batch
runs, are left out and listed. If the carrier times out, a retry reuses the same idempotency key at the original
price, so a label the carrier already issued is returned rather than bought again; if that quote has expired, the
merchant approves a new price.
