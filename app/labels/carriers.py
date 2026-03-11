"""Carrier clients. Each merchant brings their own carrier accounts; we never pool them."""

from dataclasses import dataclass


@dataclass
class PurchaseResult:
    tracking: str
    pdf_url: str


class CarrierError(Exception):
    """A carrier rejected or failed a request. `retryable` is set for timeouts and 5xx."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


CARRIERS: dict[str, type] = {}


def register(name: str):
    def wrap(cls):
        CARRIERS[name] = cls
        return cls

    return wrap


def get_carrier(name: str, merchant):
    return CARRIERS[name](merchant.carrier_accounts[name])


@register("usps")
class USPS:
    base_url = "https://apis.usps.com/labels/v3"

    def __init__(self, account):
        self.account = account

    def buy(self, order, rate, *, idempotency_key: str) -> PurchaseResult:
        response = self.account.post(
            f"{self.base_url}/label",
            json={
                "rateId": rate.rate_id,
                "reference": order.id,
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        return PurchaseResult(response["trackingNumber"], response["labelUrl"])
