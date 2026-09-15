"""Usage events: one row per thing a merchant did that we may ever count. Append-only.

Nothing bills or displays from this table: it has replays, our own test shops and, since #216, every attempt
in it. Readers use the daily counts (app/usage/daily.py). This directory is Jordan's.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

FEATURES = {"labels", "assistant"}
STATUSES = {"completed", "failed", "timed_out", "voided"}


@dataclass(frozen=True)
class UsageEvent:
    merchant_id: str
    feature: str
    request_id: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "completed"
    attempt: int = 1


def record(usage, event: UsageEvent) -> None:
    """Append one event. `usage` is a UsageStore (app/usage/store.py) or a test fake with record()."""
    if event.feature not in FEATURES:
        raise ValueError(f"unknown usage feature {event.feature!r}")
    if event.status not in STATUSES:
        raise ValueError(f"unknown usage status {event.status!r}")
    usage.record(event)
