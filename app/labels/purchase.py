"""Label purchasing. Every purchase goes through purchase_label(); nothing else may buy a label."""

from dataclasses import dataclass
from decimal import Decimal

from app.labels.carriers import get_carrier, with_one_retry
from app.labels.rates import quote_is_fresh


@dataclass
class Label:
    order_id: str
    carrier: str
    tracking_number: str
    price: Decimal
    pdf_url: str


class StaleRateError(Exception):
    """The merchant has not seen the current price for this order."""


def purchase_label(order, rate, *, idempotency_key: str, shown_price: Decimal) -> Label:
    """Buy one label for one order.

    `idempotency_key` must be stable for the order and the attempt, so a retry never buys twice.
    `shown_price` is the price the merchant saw and approved.
    """
    # Never buy a label before the merchant has seen its price (postmortem, 2026-06-02).
    if not quote_is_fresh(rate) or rate.price != shown_price:
        raise StaleRateError(order.id)
    carrier = get_carrier(rate.carrier, order.merchant)
    result = with_one_retry(lambda: carrier.buy(order, rate, idempotency_key=idempotency_key))
    return Label(order.id, rate.carrier, result.tracking, rate.price, result.pdf_url)
