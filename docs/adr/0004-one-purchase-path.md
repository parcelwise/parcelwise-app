# 0004: One path buys labels

- Status: accepted
- Date: 2026-09-09
- Deciders: Jordan Okafor

## Context

A retry in an import script called a carrier client directly, without an idempotency key, and bought 38 labels
twice.

## Decision

Every label purchase goes through `purchase_label()` with an idempotency key that is stable for the order and
the attempt. A test fails the build if anything else calls a carrier's `buy()`.

## Consequences

New ways of buying (imports, scheduled jobs, many orders at once) call `purchase_label()` once per order.
