# Postmortem: labels bought at a stale rate (2026-06-02)

- Severity: SEV-2
- Duration: 3h 40m
- Author: Marcus Lee
- Impact: 1,312 labels across 9 merchants bought at yesterday's rates; $4,100 refunded to merchants.

## What happened

A UPS rate change took effect at midnight. Orders pages left open overnight still showed the old quotes, and
`purchase_label()` bought at whatever the carrier charged. Merchants were billed the difference.

## What we changed

- `purchase_label()` refuses a quote older than ten minutes or a price the merchant did not see (#94).
- Point-in-time recovery on the production database (#119).

## Rule from here on

Never buy a label before the merchant sees the price.
