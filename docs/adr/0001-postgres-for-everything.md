# 0001: Postgres for everything until it hurts

- Status: accepted
- Date: 2026-03-04
- Deciders: Marcus Lee

## Context

We need a store for merchants, orders and labels, and some background work. We are five engineers.

## Decision

One Postgres database. No queue, cache or search service until a measured problem needs one.

## Consequences

Fewer moving parts to run. Anything that needs a queue later has to make the case in its own ADR.
