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
purchase. Stripe webhooks update the merchant's plan. Bulk label batches run in the `label-worker` service from a
job table in Postgres, one batch per merchant at a time ([ADR 0005](adr/0005-bulk-labels-run-in-a-postgres-job-table.md)).
