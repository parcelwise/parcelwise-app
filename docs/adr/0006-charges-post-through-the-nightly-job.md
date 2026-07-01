# 0006: Charges post through the nightly billing job, as Stripe invoice items

- Status: accepted
- Date: 2026-06-30
- Deciders: Marcus Lee, Priya Shah

## Context

Starter shops that run past 1,000 labels in a month should keep shipping and pay for the extra labels instead
of hitting a wall. That is our first charge beyond the subscription, and the assistant will want the same path.

## Decision

All charges post through the nightly billing job (`app/billing/nightly.py`). Nothing charges at purchase time.
The job reads `usage_daily` for the period that closed, asks the plan what is included and what the extra costs,
and posts one charge per merchant and feature as a Stripe invoice item on the merchant's next invoice.

We did not use a Stripe metered price. Usage records on a metered price cannot be taken back when a label is
voided within 24 hours, and the invoice item posted when the period closes is computed net of voids.

A new metered feature is a plan entry and a usage feature; it gets no code path of its own in billing.

## Consequences

Billing stays off the purchase path, so a slow Stripe never slows a label. A merchant sees extra charges on
the invoice they already get, in arrears. A double charge is one bug away until every charge is idempotent
(ADR 0007).
