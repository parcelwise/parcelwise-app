"""Nightly: fold yesterday's usage_events into usage_daily. Runs at 08:00 UTC, before billing (infra/deploy.yaml)."""

from datetime import date, timedelta

from app.usage.daily import rollup
from app.usage.store import UsageStore


def main(today: date | None = None) -> int:
    day = (today or date.today()) - timedelta(days=1)
    rows = rollup(UsageStore(), day)
    print(f"usage_daily: {rows} rows for {day}")
    return rows


if __name__ == "__main__":
    main()
