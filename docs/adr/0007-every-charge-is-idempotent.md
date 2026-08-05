# 0007: Every charge is idempotent

- Status: accepted
- Date: 2026-08-05
- Deciders: Marcus Lee

## Context

On August 3 the nightly billing job timed out on Stripe and was re-run by hand; both runs had posted. 143
Starter shops were charged twice for their extra July labels
([postmortem](../postmortems/2026-08-03-double-overage-charges.md)).

## Decision

Every charge carries an idempotency key made of the merchant, the feature and the period. `post_charge()` is
the only writer of `posted_charges`, is a no-op when the key is already there, and hands Stripe the same key.
Posting a charge twice, for any reason (a retry, a re-run of the job, a bug), bills once.

## Consequences

The nightly job can be re-run for a period at any time, and runs every night for whatever a failed batch left
behind. Anything that charges in future, for any feature, goes through `post_charge()`.
