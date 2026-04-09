from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.labels.rates import Rate, cheapest, quote_is_fresh


def test_quote_expires_after_ten_minutes():
    old = Rate("ups", "ground", Decimal(7), datetime.now(timezone.utc) - timedelta(minutes=11))
    assert not quote_is_fresh(old)


def test_cheapest_skips_stale_quotes():
    now = datetime.now(timezone.utc)
    stale = Rate("ups", "ground", Decimal(4), now - timedelta(minutes=20))
    fresh = Rate("ups", "2day", Decimal(9), now)
    assert cheapest([stale, fresh]) is fresh
