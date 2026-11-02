"""Per-account purchase rate limits. One limiter per process; the label-worker runs as a single instance."""

import time
from collections import defaultdict, deque
from collections.abc import Iterable

from app.labels.carriers import PURCHASES_PER_MINUTE

WINDOW_SECONDS = 60.0


class PurchaseRateLimiter:
    def __init__(self, limits: dict[str, int] | None = None, *, clock=time.monotonic):
        self.limits = PURCHASES_PER_MINUTE if limits is None else limits
        self.clock = clock
        self._sent: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def wait_seconds(self, merchant_id: str, carrier: str) -> float:
        """How long until this merchant's account for this carrier may send another purchase. 0 means now."""
        limit = self.limits.get(carrier)
        if limit is None:
            return 0.0
        sent = self._sent[(merchant_id, carrier)]
        now = self.clock()
        while sent and now - sent[0] >= WINDOW_SECONDS:
            sent.popleft()
        if len(sent) < limit:
            return 0.0
        return WINDOW_SECONDS - (now - sent[0])

    def seed(self, merchant_id: str, carrier: str, seconds_ago: Iterable[float]) -> None:
        """Purchases sent before this process started, so a restart doesn't reset the limit (Ana Ruiz, Raven
        6e7bb36f0dd0)."""
        if carrier not in self.limits:
            return
        now = self.clock()
        sent = self._sent[(merchant_id, carrier)]
        for age in sorted(seconds_ago, reverse=True):
            if 0 <= age < WINDOW_SECONDS:
                sent.append(now - age)

    def record(self, merchant_id: str, carrier: str) -> None:
        if carrier in self.limits:
            self._sent[(merchant_id, carrier)].append(self.clock())
