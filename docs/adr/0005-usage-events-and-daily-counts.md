# 0005: Usage is counted in usage_events and read from usage_daily, by cursor

- Status: accepted
- Date: 2026-06-09
- Deciders: Jordan Okafor, Marcus Lee

## Context

The label allowance was a counter on the merchant row, bumped in place on every purchase. The assistant needs
counting too, and so will anything we meter next. A counter per feature on the merchant row does not scale and
cannot be re-derived when it is wrong.

## Decision

One append-only table, `usage_events`: one row per thing a merchant did that we may ever count, with the
merchant, the feature and the request id. Nothing bills or displays from it: it has replays and our own test
shops in it. A nightly rollup folds it into `usage_daily`, one row per merchant, feature and day, and that is
what billing and the dashboard read.

Reads of `usage_daily` page by cursor, the last row's (day, merchant, feature), never by offset: the rollup
inserts rows while a reader walks the table, and offset pages skip or repeat. A reader that wants a total for a
period walks every page.

## Consequences

A new metered feature is a feature name in `app/usage/events.py` and the events that report it; the counts
follow. `app/usage/` is Jordan's; anyone billing from the counts asks once per feature.
