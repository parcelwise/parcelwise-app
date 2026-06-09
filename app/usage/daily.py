"""Daily counts per merchant and feature: what billing and the dashboard read. Never the raw table (ADR 0005).

Reads page by cursor (the last row's day, merchant and feature), never by offset: the nightly rollup inserts
rows while a reader walks the table, and offset pages skip or repeat. A reader that wants a total for a period
walks every page.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

PAGE = 500


@dataclass(frozen=True, order=True)
class Cursor:
    day: date
    merchant_id: str
    feature: str


@dataclass(frozen=True)
class DailyCount:
    day: date
    merchant_id: str
    feature: str
    count: int

    @property
    def cursor(self) -> Cursor:
        return Cursor(self.day, self.merchant_id, self.feature)


def read_page(usage, feature: str, period: str, *, after: Cursor | None = None, limit: int = PAGE):
    """One page of usage_daily for a feature and a period ("2026-06"), and the cursor for the next page or None."""
    rows = usage.daily_after(feature, period, after, limit)
    return rows, (rows[-1].cursor if len(rows) == limit else None)


def period_totals(usage, period: str, *, features) -> dict[tuple[str, str], int]:
    """{(merchant_id, feature): count} for a period, walking every page of each feature."""
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for feature in sorted(features):
        after = None
        while True:
            rows, after = read_page(usage, feature, period, after=after)
            for row in rows:
                totals[(row.merchant_id, feature)] += row.count
            if after is None:
                break
    return dict(totals)


def rollup(usage, day: date) -> int:
    """Fold usage_events for `day` into usage_daily. Idempotent: re-running a day replaces its rows."""
    return usage.rollup_day(day)
