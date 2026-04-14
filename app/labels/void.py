"""Voiding. Carriers refund an unused label if it is voided within a day of purchase."""

from datetime import datetime, timedelta, timezone

VOID_WINDOW = timedelta(hours=24)


class VoidWindowClosed(Exception):
    pass


def void_label(label, carrier, *, bought_at: datetime, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    if now - bought_at > VOID_WINDOW:
        raise VoidWindowClosed(label.tracking_number)
    return carrier.void(label.tracking_number)
