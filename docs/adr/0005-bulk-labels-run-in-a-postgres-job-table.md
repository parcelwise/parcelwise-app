# 0005: Bulk label batches run from a job table in Postgres

- Status: accepted
- Date: 2026-10-30
- Deciders: Marcus Lee, Ana Ruiz

## Context

Merchants can now buy labels for many orders at once; Bloom & Co buys about 200 every morning. Each order is
still one `purchase_label()` call ([ADR 0004](0004-one-purchase-path.md)), and USPS throttles above 40 purchases a
minute and has suspended accounts before, so 200 labels take about five minutes. That cannot run inside a request
(gunicorn times out at 30 seconds), and we had no background worker.

## Decision

A batch is a row in `label_batches` with one row per order in `label_batch_items`, holding the price the merchant
saw. One `label-worker` service claims queued batches and buys them one order at a time, at most 40 a minute. No
Redis or queue library ([ADR 0001](0001-postgres-for-everything.md)).

Only one batch per merchant runs at a time (a unique index on running batches), which keeps the merchant's carrier
account under its cap. Each order's result is committed as soon as it is bought, skipped or failed.

## Consequences

- The Orders page reads progress and results straight from Postgres.
- The worker runs as exactly one instance. On start it re-queues batches left running by a restart; orders already
  bought are skipped, and the rest reuse their idempotency keys (`batch_id:order_id`), so nothing is bought twice.
- Orders whose quote went stale or changed are skipped, never bought, and shown to the merchant again with the new
  price ([ADR 0003](0003-merchant-sees-the-price-first.md)).
- Running more than one worker, or more throughput per merchant, needs a new ADR.
