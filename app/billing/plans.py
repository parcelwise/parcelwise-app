"""Plans. Prices live in Stripe; this file only holds what the app enforces.

A plan's allowance is what the subscription includes. Past it, a plan with an `extra_label_price` keeps buying
and pays per label on the next invoice (app/billing/nightly.py); a plan without one stops.

The assistant is metered on Starter and Growth (Priya, founders sync Oct 29). How many answers a month are
included and what one costs past that are not decided yet: they are `Undecided` below, and the nightly job posts
no assistant charge until both are filled in.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Undecided:
    """A value nobody has decided yet. Billing posts nothing for a feature while any of its inputs is Undecided."""

    question: str
    owner: str

    def __str__(self) -> str:
        return f"undecided ({self.owner}): {self.question}"


def is_undecided(value) -> bool:
    return isinstance(value, Undecided)


ASSISTANT_ALLOWANCE = Undecided("How many assistant answers a month are included on this plan?", "Priya Shah")
ASSISTANT_PRICE = Undecided("What do we charge per assistant answer past the monthly allowance?", "Priya Shah")

PLANS = {
    "free": {
        "labels_per_month": 50, "assistant": False, "extra_label_price": None,
        "assistant_answers_per_month": None, "extra_assistant_answer_price": None,
    },
    "starter": {
        "labels_per_month": 1_000, "assistant": True, "extra_label_price": Decimal("0.08"),
        "assistant_answers_per_month": ASSISTANT_ALLOWANCE, "extra_assistant_answer_price": ASSISTANT_PRICE,
    },
    "growth": {
        "labels_per_month": None, "assistant": True, "extra_label_price": None,
        "assistant_answers_per_month": ASSISTANT_ALLOWANCE, "extra_assistant_answer_price": ASSISTANT_PRICE,
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
