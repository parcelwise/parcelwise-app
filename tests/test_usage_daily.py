from datetime import date

from app.usage.daily import Cursor, DailyCount, period_totals, read_page


class FakeUsage:
    """usage_daily as a sorted list; pages the way the Postgres store does, by (day, merchant, feature)."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: (r.day, r.merchant_id, r.feature))
        self.reads = 0

    def daily_after(self, feature, period, after, limit):
        self.reads += 1
        rows = [r for r in self.rows if r.feature == feature and r.day.strftime("%Y-%m") == period]
        if after is not None:
            rows = [r for r in rows if r.cursor > after]
        return rows[:limit]


def rows_for(merchants, days, feature="labels", count=3):
    return [DailyCount(date(2026, 6, d), m, feature, count) for d in days for m in merchants]


def test_pages_by_cursor_and_walks_every_page():
    usage = FakeUsage(rows_for(["m1", "m2", "m3"], range(1, 31)))  # 90 rows
    first, cursor = read_page(usage, "labels", "2026-06", limit=40)
    assert len(first) == 40 and cursor == Cursor(date(2026, 6, 14), "m1", "labels")
    second, cursor = read_page(usage, "labels", "2026-06", after=cursor, limit=40)
    assert second[0].cursor > first[-1].cursor and len(second) == 40
    last, cursor = read_page(usage, "labels", "2026-06", after=cursor, limit=40)
    assert len(last) == 10 and cursor is None


def test_period_totals_sum_every_day_per_merchant():
    usage = FakeUsage(rows_for(["m1", "m2"], range(1, 31)) + rows_for(["m1"], [15], feature="assistant", count=7))
    totals = period_totals(usage, "2026-06", features={"labels", "assistant"})
    assert totals == {("m1", "labels"): 90, ("m2", "labels"): 90, ("m1", "assistant"): 7}


def test_rows_inserted_while_walking_are_not_skipped_or_repeated():
    usage = FakeUsage(rows_for(["m1", "m2"], range(1, 31)))
    seen = []
    after = None
    while True:
        rows, after = read_page(usage, "labels", "2026-06", after=after, limit=7)
        seen += rows
        if usage.reads == 2:  # the rollup lands a new day behind the reader's position
            usage.rows = sorted(usage.rows + rows_for(["m0"], [1]), key=lambda r: (r.day, r.merchant_id, r.feature))
        if after is None:
            break
    assert len(seen) == len({r.cursor for r in seen}) == 60


def test_month_to_date_is_one_merchant_this_month():
    from app.usage.daily import month_to_date

    usage = FakeUsage(rows_for(["m1", "m2"], range(1, 7)) + rows_for(["m1"], [3, 4], feature="assistant", count=5))
    assert month_to_date(usage, "m1", date(2026, 6, 6), features={"labels", "assistant"}) == {
        "assistant": 10,
        "labels": 18,
    }
