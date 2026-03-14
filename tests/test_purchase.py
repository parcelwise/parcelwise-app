from decimal import Decimal

from app.labels import carriers
from app.labels.purchase import purchase_label
from tests.conftest import FakeCarrier, FakeOrder


def test_purchase_uses_idempotency_key(monkeypatch, fresh_rate):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    label = purchase_label(FakeOrder("o1"), fresh_rate, idempotency_key="o1:1", shown_price=Decimal("5.40"))
    assert fake.bought == ["o1:1"]
    assert label.tracking_number == "TRK0001"
