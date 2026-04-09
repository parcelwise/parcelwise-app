"""Rate quotes. A quote is only good for ten minutes; carriers reprice after that."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

RATE_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class Rate:
    carrier: str
    service: str
    price: Decimal
    quoted_at: datetime
    rate_id: str = ""


def quote_is_fresh(rate: Rate, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now - rate.quoted_at < RATE_TTL


def cheapest(rates: list[Rate]) -> Rate:
    """The cheapest fresh rate. Ties go to the faster service, which carriers list first."""
    fresh = [r for r in rates if quote_is_fresh(r)]
    if not fresh:
        raise LookupError("no fresh rates")
    return min(fresh, key=lambda r: r.price)
