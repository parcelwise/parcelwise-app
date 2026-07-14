from decimal import Decimal

from app.billing.charges import Charge, post_charge


class FakeStripe:
    class InvoiceItem:
        created = []

        @classmethod
        def create(cls, **kwargs):
            cls.created.append(kwargs)
            return {"id": f"ii_{len(cls.created)}"}


def test_amount_is_decimal_cents():
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert charge.amount == Decimal("16.96")


def test_post_charge_is_one_invoice_item_in_cents():
    FakeStripe.InvoiceItem.created.clear()
    item = post_charge(FakeStripe, "cus_1", Charge("m1", "labels", "2026-06", 212, Decimal("0.08")))
    assert item == "ii_1"
    (created,) = FakeStripe.InvoiceItem.created
    assert created["customer"] == "cus_1" and created["amount"] == 1696 and created["currency"] == "usd"


def test_description_is_one_line_per_feature_per_period():
    charge = Charge("m1", "labels", "2026-06", 212, Decimal("0.08"))
    assert charge.description == "Extra labels, June 2026: 212 × $0.08"
