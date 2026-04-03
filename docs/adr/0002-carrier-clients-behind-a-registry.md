# 0002: Carrier clients behind a registry

- Status: accepted
- Date: 2026-04-08
- Deciders: Jordan Okafor, Marcus Lee

## Context

UPS is our second carrier and FedEx is next. Each has its own auth, error shapes and retry rules.

## Decision

Each carrier is a client class registered in `app/labels/carriers.py`. Callers use `get_carrier(name, merchant)`
and never import a client directly. All buying goes through `purchase_label()`.

## Consequences

Adding a carrier is one file and one `register()` call. Carrier quirks stay out of the purchase path.
