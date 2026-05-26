"""The Postgres side of app/usage. Everything else in this package takes a store and never writes SQL."""

from app.core.db import transaction


class UsageStore:
    def record(self, event) -> None:
        with transaction() as cur:
            cur.execute(
                "INSERT INTO usage_events (merchant_id, feature, request_id, at) VALUES (%s, %s, %s, %s)",
                (event.merchant_id, event.feature, event.request_id, event.at),
            )
