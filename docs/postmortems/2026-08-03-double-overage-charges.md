# Postmortem: extra-label charges posted twice (2026-08-03)

- Severity: SEV-2
- Duration: 14h (overnight to the first merchant email)
- Author: Marcus Lee
- Impact: 143 Starter merchants charged twice for their July extra labels; $2,860 refunded.

## What happened

The nightly billing job's first full run for July hit a Stripe timeout about two thirds of the way through and
exited non-zero. The deploy runbook said to re-run it; the re-run posted every merchant's charge again, because
nothing recorded which charges the first run had already posted. Stripe finalised 143 invoices overnight with two
"Extra labels, July 2026" lines each.

## What we changed

- Every charge carries an idempotency key of merchant, feature and period, recorded in `posted_charges`;
  `post_charge()` is a no-op when the key is there and passes the same key to Stripe (#140, ADR 0007).
- The job posts in batches of 100, one transaction each, so a failure leaves at most one batch to redo (#148).

## Rule from here on

A charge must be safe to post twice.
