from datetime import datetime, timezone

import pytest

from app.usage.events import UsageEvent, record


class FakeUsage:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def test_record_appends_one_row():
    usage = FakeUsage()
    event = UsageEvent("m1", "labels", "o1:1", at=datetime(2026, 5, 26, 10, tzinfo=timezone.utc))
    record(usage, event)
    assert usage.events == [event]


def test_unknown_feature_is_refused():
    with pytest.raises(ValueError):
        record(FakeUsage(), UsageEvent("m1", "coffee", "x"))
