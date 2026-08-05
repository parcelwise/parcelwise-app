"""posted_charges: which idempotency keys have been posted (ADR 0007). Only post_charge() writes it."""

from contextlib import contextmanager

from app.core.db import transaction


class PostedCharges:
    def __init__(self):
        self._cur = None

    @contextmanager
    def transaction(self):
        with transaction() as cur:
            self._cur = cur
            try:
                yield
            finally:
                self._cur = None

    def seen(self, key: str) -> bool:
        self._cur.execute("SELECT 1 FROM posted_charges WHERE idempotency_key = %s", (key,))
        return self._cur.fetchone() is not None

    def mark(self, charge, stripe_item_id: str) -> None:
        self._cur.execute(
            "INSERT INTO posted_charges (idempotency_key, merchant_id, feature, period, stripe_item_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (charge.idempotency_key, charge.merchant_id, charge.feature, charge.period, stripe_item_id),
        )
