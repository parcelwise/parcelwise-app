# 0003: The merchant sees the price before we buy

- Status: accepted
- Date: 2026-06-04
- Deciders: Jordan Okafor, Marcus Lee

## Context

On June 2 we bought $4,100 of labels at a stale rate ([postmortem](../postmortems/2026-06-02-stale-rate-labels.md)).
The dashboard showed a quote from the night before; the carrier charged that day's price.

## Decision

`purchase_label()` takes the price the merchant saw (`shown_price`) and refuses the purchase with
`StaleRateError` if the quote is older than ten minutes or the price changed.

## Consequences

The dashboard re-quotes on 409. Anything that buys labels without a person looking (imports, jobs) has to show
the merchant the total first.
