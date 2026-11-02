from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.purchase import StaleRateError, purchase_label
from app.labels.rates import RATE_TTL, Rate
from tests.conftest import FakeCarrier, FakeOrder


def _rate(age: timedelta, price: str = "5.40") -> Rate:
    return Rate("usps", "ground_advantage", Decimal(price), datetime.now(timezone.utc) - age, "rate_1")


def test_quote_older_than_ttl_is_refused_and_nothing_is_bought(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    stale = _rate(RATE_TTL + timedelta(seconds=1))
    with pytest.raises(StaleRateError):
        purchase_label(FakeOrder("o1"), stale, idempotency_key="o1:1", shown_price=Decimal("5.40"))
    assert fake.bought == []


def test_price_different_from_shown_price_is_refused(monkeypatch, fresh_rate):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    with pytest.raises(StaleRateError):
        purchase_label(FakeOrder("o1"), fresh_rate, idempotency_key="o1:1", shown_price=Decimal("5.00"))
    assert fake.bought == []
