"""Shared fakes. Tests never touch a real carrier."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.labels.carriers import PurchaseResult
from app.labels.rates import Rate


class FakeCarrier:
    def __init__(self):
        self.bought = []

    def buy(self, order, rate, *, idempotency_key):
        self.bought.append(idempotency_key)
        return PurchaseResult(f"TRK{len(self.bought):04d}", f"https://labels.test/{order.id}.pdf")


@dataclass
class FakeMerchant:
    carrier_accounts: dict = field(default_factory=lambda: {"usps": object()})


@dataclass
class FakeOrder:
    id: str
    merchant: FakeMerchant = field(default_factory=FakeMerchant)


@pytest.fixture
def fresh_rate():
    return Rate("usps", "ground_advantage", Decimal("5.40"), datetime.now(timezone.utc), "rate_1")
