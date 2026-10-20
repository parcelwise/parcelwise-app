# Architecture

Parcelwise buys shipping labels for Shopify merchants. A merchant connects their shop, we pull unfulfilled
orders, quote rates from their carrier accounts, and buy labels when they click **Buy label**. The assistant
answers questions about their orders, labels and plan from the same data.

```
Shopify ──webhooks──▶ app/shopify ──▶ orders (Postgres) ──▶ web/orders (Next.js)
                                                     │
                                         Buy label   ▼
                                  app/labels/purchase.py ──▶ carrier APIs (USPS, UPS)
                                                     │
                                                     ▼
                                       labels (Postgres) + label PDFs (S3)

Ask ──▶ app/assistant ──▶ model                 purchases, answers ──▶ usage_events ──nightly──▶ usage_daily
                                                                                                    │
                                                                            app/billing/nightly.py  ▼
                                                                          charges ──▶ Stripe invoice items
```

## Services

| Service | What it does | Owner |
| --- | --- | --- |
| `app/api` | HTTP API for the dashboard and webhooks | Platform |
| `app/labels` | Rates, purchases, voids, PDFs | Labels |
| `app/orders` | Orders as we store them | Labels, Dashboard |
| `app/shopify` | Order sync, webhooks, install source | Integrations |
| `app/assistant` | The Parcelwise Assistant: one question in, one answer out | Assistant (Maya) |
| `app/usage` | Usage events and the daily counts everyone reads | Labels (Jordan) |
| `app/billing` | Plans, allowances, charges, the nightly billing job, Stripe | Revenue (plans), Platform (charges) |
| `web/` | Merchant dashboard | Dashboard |

## Rules that hold everywhere

- Money is `Decimal`, never `float`.
- Every label purchase goes through `purchase_label()` (see [ADR 0002](adr/0002-carrier-clients-behind-a-registry.md)).
- A merchant sees the price before we buy ([ADR 0003](adr/0003-merchant-sees-the-price-first.md)).
- Usage is counted in `usage_events` and read from `usage_daily`, by cursor ([ADR 0005](adr/0005-usage-events-and-daily-counts.md)).
- Charges post through the nightly billing job, as Stripe invoice items; nothing charges at purchase time
  ([ADR 0006](adr/0006-charges-post-through-the-nightly-job.md)).
- Every charge is idempotent ([ADR 0007](adr/0007-every-charge-is-idempotent.md)).

## Background work

Shopify sync runs on a five-minute cron. Shipping confirmation emails go out through Postmark right after a
purchase. Stripe webhooks update the merchant's plan. The usage rollup runs at 08:00 UTC and the billing job
at 09:00 UTC (`infra/deploy.yaml`); the billing job posts the closed month's charges on the first and anything
left behind on the nights after.
