# Parcelwise

Shipping labels for Shopify shops. Merchants connect their store, see every unfulfilled order with a live
rate, and buy USPS or UPS labels in a click.

## Layout

| Path | What lives there |
| --- | --- |
| `app/labels/` | Rate quotes, label purchases, voids and PDFs |
| `app/orders/` | Orders synced from Shopify |
| `app/shopify/` | Shopify sync and webhooks |
| `app/billing/` | Plans and Stripe |
| `web/` | The merchant dashboard (Next.js) |
| `infra/` | Deploy config and Terraform |
| `migrations/` | Postgres migrations, applied in order |

## Run it locally

```sh
make setup      # virtualenv, dependencies, local Postgres
make test       # unit tests
make dev        # API on :8000, dashboard on :3000
```
