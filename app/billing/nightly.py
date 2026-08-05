"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from datetime import date

from app.billing.charges import Charge, post_charge
from app.billing.plans import PLANS
from app.usage.daily import period_totals

# feature -> (the plan key for its allowance, the plan key for its price past the allowance)
METERED = {"labels": ("labels_per_month", "extra_label_price")}


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str]) -> list[Charge]:
    """`totals` is {(merchant_id, feature): count}; `plan_of` maps a merchant to its plan name."""
    charges = []
    for (merchant_id, feature), used in sorted(totals.items()):
        allowance_key, price_key = METERED[feature]
        plan = PLANS[plan_of[merchant_id]]
        allowance, price = plan[allowance_key], plan[price_key]
        if price is None or allowance is None:
            continue  # unlimited, or a plan that stops at its allowance instead of paying
        extra = max(0, used - allowance)
        if extra:
            charges.append(Charge(merchant_id, feature, period, extra, price))
    return charges


def closed_period(today: date) -> str:
    """The month before `today`, as "YYYY-MM"."""
    first = today.replace(day=1)
    if first.month == 1:
        return first.replace(year=first.year - 1, month=12).strftime("%Y-%m")
    return first.replace(month=first.month - 1).strftime("%Y-%m")


def run(usage, plan_of: dict[str, str], customer_of: dict[str, str], stripe, posted, *, period: str) -> int:
    """Post the period's charges that are not posted yet. Returns how many were posted this run."""
    totals = period_totals(usage, period, features=METERED)
    count = 0
    with posted.transaction():
        for charge in charges_for(period, totals, plan_of):
            if post_charge(stripe, posted, customer_of[charge.merchant_id], charge):
                count += 1
    return count
