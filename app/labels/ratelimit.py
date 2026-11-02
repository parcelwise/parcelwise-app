"""Per-account purchase rate limits. One limiter per process; the label-worker runs as a single instance."""

import time
from collections import defaultdict, deque

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

    def record(self, merchant_id: str, carrier: str) -> None:
        if carrier in self.limits:
            self._sent[(merchant_id, carrier)].append(self.clock())
