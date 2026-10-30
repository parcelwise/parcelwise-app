# 0005: Bulk label purchases run as jobs in Postgres

- Status: accepted
- Date: 2026-10-30
- Deciders: Marcus Lee; Ana Ruiz decided the job and the rate cap

## Context

Bloom & Co buys about 200 USPS labels every morning, one click at a time. Merchants want to select orders and buy
them all at once. A request can't do that: gunicorn times out at 30 seconds, and USPS throttles us past 40
purchases a minute and has suspended an account for bursts. Ana Ruiz decided purchases run as a background job,
one at a time, at no more than 40 a minute. [ADR 0001](0001-postgres-for-everything.md) asks anything that needs a
queue to make its case in its own ADR. This is that case.

## Decision

A batch is a row in `label_batches` with one `label_batch_items` row per order (migration 0007). A `label-worker`
process (`app/labels/batch_worker.py`) claims queued batches with `FOR UPDATE SKIP LOCKED` and buys each item
through `purchase_label()` with its own idempotency key ([ADR 0004](0004-one-purchase-path.md)), paced to 40 a
minute. A unique partial index allows one running batch per merchant, so the cap holds per carrier account however
many workers run. A worker that dies leaves a stale heartbeat; another picks the batch up after two minutes and
re-runs the unfinished items with the same keys.

No Redis and no queue service: Postgres only, as ADR 0001 wants.

## Consequences

One more process to deploy and watch (`label-worker`, one instance to start). Merchants can close the tab while a
batch runs. At 40 a minute a 200-label batch takes five minutes, inside the ten-minute quote window; if a price goes
stale anyway the batch stops and the merchant confirms new prices ([ADR 0003](0003-merchant-sees-the-price-first.md)).
