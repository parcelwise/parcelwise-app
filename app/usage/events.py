"""Usage events: one row per thing a merchant did that we may ever count. Append-only.

Nothing bills or displays from this table: it has replays and our own test shops in it. Readers use the
daily counts (app/usage/daily.py, from #96). Platform data for Parcelwise is Labels: this directory is Jordan's.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

FEATURES = {"labels"}


@dataclass(frozen=True)
class UsageEvent:
    merchant_id: str
    feature: str
    request_id: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def record(usage, event: UsageEvent) -> None:
    """Append one event. `usage` is a UsageStore (app/usage/store.py) or a test fake with record()."""
    if event.feature not in FEATURES:
        raise ValueError(f"unknown usage feature {event.feature!r}")
    usage.record(event)
