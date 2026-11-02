"""The Postgres side of app/usage. Everything else in this package takes a store and never writes SQL."""

from datetime import date

from app.core.db import transaction
from app.usage.daily import ASSISTANT_ANSWERED, Cursor, DailyCount


class UsageStore:
    def record(self, event) -> None:
        with transaction() as cur:
            cur.execute(
                "INSERT INTO usage_events (merchant_id, feature, request_id, at, status, attempt) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (event.merchant_id, event.feature, event.request_id, event.at, event.status, event.attempt),
            )

    def rollup_day(self, day: date) -> int:
        """Fold one day of usage_events into usage_daily. Re-running a day replaces its rows.

        Two assistant counts per day: `assistant`, every attempt (the cost, #216), and `assistant_answered`, one per
        request id that completed (what is billed). Returns the rows written.
        """
        with transaction() as cur:
            cur.execute("DELETE FROM usage_daily WHERE day = %s", (day,))
            cur.execute(
                "INSERT INTO usage_daily (day, merchant_id, feature, count) "
                "SELECT %s, merchant_id, feature, COUNT(*) FROM usage_events "
                "WHERE at >= %s AND at < %s + INTERVAL '1 day' AND status <> 'voided' "
                "GROUP BY merchant_id, feature",
                (day, day, day),
            )
            rows = cur.rowcount
            cur.execute(
                "INSERT INTO usage_daily (day, merchant_id, feature, count) "
                "SELECT %s, merchant_id, %s, COUNT(DISTINCT request_id) FROM usage_events "
                "WHERE at >= %s AND at < %s + INTERVAL '1 day' AND feature = 'assistant' AND status = 'completed' "
                "GROUP BY merchant_id",
                (day, ASSISTANT_ANSWERED, day, day),
            )
            return rows + cur.rowcount

    def daily_after(self, feature: str, period: str, after: Cursor | None, limit: int) -> list[DailyCount]:
        """One page of usage_daily for a feature and a period, ordered by (day, merchant_id, feature)."""
        with transaction() as cur:
            if after is None:
                cur.execute(
                    "SELECT day, merchant_id, feature, count FROM usage_daily "
                    "WHERE feature = %s AND to_char(day, 'YYYY-MM') = %s "
                    "ORDER BY day, merchant_id, feature LIMIT %s",
                    (feature, period, limit),
                )
            else:
                cur.execute(
                    "SELECT day, merchant_id, feature, count FROM usage_daily "
                    "WHERE feature = %s AND to_char(day, 'YYYY-MM') = %s "
                    "AND (day, merchant_id, feature) > (%s, %s, %s) "
                    "ORDER BY day, merchant_id, feature LIMIT %s",
                    (feature, period, after.day, after.merchant_id, after.feature, limit),
                )
            return [DailyCount(*row) for row in cur.fetchall()]
