from decimal import Decimal

from app.billing.charges import Charge, post_charge


class FakeStripe:
    class InvoiceItem:
        created = []

        @classmethod
        def create(cls, **kwargs):
            cls.created.append(kwargs)
            return {"id": f"ii_{len(cls.created)}"}


class FakePosted:
    def __init__(self):
        self.keys = {}

    def seen(self, key):
        return key in self.keys

    def mark(self, charge, item_id):
        self.keys[charge.idempotency_key] = item_id


def test_amount_is_decimal_cents():
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert charge.amount == Decimal("16.96")


def test_description_is_one_line_per_feature_per_period():
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert charge.description == "Extra labels, June 2026: 212 × $0.08"


def test_post_charge_is_one_invoice_item_in_cents_with_the_key():
    FakeStripe.InvoiceItem.created.clear()
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert post_charge(FakeStripe, FakePosted(), "cus_1", charge) == "ii_1"
    (created,) = FakeStripe.InvoiceItem.created
    assert created["customer"] == "cus_1" and created["amount"] == 1696 and created["currency"] == "usd"
    assert created["idempotency_key"] == "m1:labels:2026-06"


def test_posting_twice_bills_once():
    FakeStripe.InvoiceItem.created.clear()
    posted = FakePosted()
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert post_charge(FakeStripe, posted, "cus_1", charge) == "ii_1"
    assert post_charge(FakeStripe, posted, "cus_1", charge) is None
    assert len(FakeStripe.InvoiceItem.created) == 1
