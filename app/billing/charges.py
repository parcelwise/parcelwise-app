"""Charges. Everything a merchant pays beyond the subscription posts through post_charge(), as a Stripe
invoice item on the next invoice (ADR 0006). Nothing charges at purchase time.

Not a Stripe metered price: usage records on a metered price cannot be taken back when a label is voided
within 24 hours, and an invoice item posted when the period closes is computed net of voids.

An invoice carries one line per feature per billing period (#124): several charges for the same feature
in the same period fold into one. Per-label detail is the usage page's job, not the invoice's.

Every charge is idempotent (ADR 0007, postmortem 2026-08-03): its key is the merchant, the feature and the
period; post_charge() is a no-op when the key was posted before and hands Stripe the same key. Posting a
charge twice, for any reason, bills once.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

FEATURE_LABEL = {"labels": "Extra labels"}


@dataclass(frozen=True)
class Charge:
    merchant_id: str
    feature: str
    period: str  # "2026-06": the month the usage happened in
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    @property
    def description(self) -> str:
        """One line per feature per period: the feature, the period, the quantity and the unit price (#124)."""
        month = date.fromisoformat(self.period + "-01").strftime("%B %Y")
        return f"{FEATURE_LABEL.get(self.feature, self.feature)}, {month}: {self.quantity} × ${self.unit_price}"

    @property
    def idempotency_key(self) -> str:
        return f"{self.merchant_id}:{self.feature}:{self.period}"


def post_charge(stripe, posted, customer_id: str, charge: Charge) -> str | None:
    """Post one charge as an invoice item on the merchant's upcoming invoice.

    `posted` is the posted_charges table (app/billing/posted.py). Returns Stripe's item id, or None when this
    charge was posted before.
    """
    if posted.seen(charge.idempotency_key):
        return None
    item = stripe.InvoiceItem.create(
        customer=customer_id,
        amount=int(charge.amount * 100),
        currency="usd",
        description=charge.description,
        idempotency_key=charge.idempotency_key,
    )
    posted.mark(charge, item["id"])
    return item["id"]
