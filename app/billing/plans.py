"""Plans. Prices live in Stripe; this file only holds what the app enforces.

A plan's allowance is what the subscription includes. Past it, a plan with an `extra_label_price` keeps buying
and pays per label on the next invoice (app/billing/nightly.py); a plan without one stops.

The assistant is metered the same way on Starter and Growth: `assistant_per_month` answers are included and each
answer past it pays `assistant_price` (Oct 29 founders sync). Free has no assistant, so nothing is metered there.
"""

from decimal import Decimal


class Open:
    """A value the owner has not decided yet. The billing job refuses to charge from one (see nightly.py)."""

    def __init__(self, decision: str):
        self.decision = decision

    def __repr__(self) -> str:
        return f"Open({self.decision!r})"


# Raven 83c4a62cc43b, Priya's calls. Nothing bills from a value that is still Open.
ASSISTANT_PRICE = Decimal("0.02")  # Priya, Raven 95990e0b370d: past the allowance they keep asking and pay this
ASSISTANT_PER_MONTH = 500  # Priya, Raven c48161595061: exactly what fits under finance's budget, not a round number

# Shops (merchants.shop_domain) kept off the public assistant rate until legal clears their most-favored-nation
# clause: Bloom & Co pays nothing for the assistant until then (Priya, Raven 95990e0b370d, b9c3b68b3ef8,
# c899624e4b42). Take a shop out of this set when legal clears it.
OFF_PUBLIC_ASSISTANT_RATE: frozenset[str] | Open = frozenset({"bloom-and-co.myshopify.com"})

PLANS = {
    "free": {
        "labels_per_month": 50, "assistant": False, "extra_label_price": None,
        "assistant_per_month": None, "assistant_price": None,
    },
    "starter": {
        "labels_per_month": 1_000, "assistant": True, "extra_label_price": Decimal("0.08"),
        "assistant_per_month": ASSISTANT_PER_MONTH, "assistant_price": ASSISTANT_PRICE,
    },
    "growth": {
        "labels_per_month": None, "assistant": True, "extra_label_price": None,
        "assistant_per_month": ASSISTANT_PER_MONTH, "assistant_price": ASSISTANT_PRICE,
    },
}


def monthly_allowance(plan: str) -> int | None:
    """None means unlimited."""
    return PLANS[plan]["labels_per_month"]


def within_allowance(plan: str, used_this_month: int) -> bool:
    allowance = monthly_allowance(plan)
    return allowance is None or used_this_month < allowance


def can_buy_label(plan: str, used_this_month: int) -> bool:
    """Within the allowance, or on a plan that charges for extra labels."""
    return within_allowance(plan, used_this_month) or PLANS[plan]["extra_label_price"] is not None


def has_assistant(plan: str) -> bool:
    """The assistant is part of the paid plans; Free does not get it (Priya, #55)."""
    return PLANS[plan]["assistant"]
