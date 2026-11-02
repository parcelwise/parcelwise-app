"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from datetime import date

from app.billing.charges import FEATURE_LABEL, Charge, post_charge
from app.billing.plans import OPEN, PLANS
from app.shopify.install import APP_STORE
from app.usage.daily import ASSISTANT_ANSWERS, period_totals

# --- The assistant's open calls. Each is OPEN until its owner answers in Raven; while any is OPEN the job posts
# --- no assistant charge at all. None of them has a default.

# Which usage_daily count the assistant is billed from: ASSISTANT_ANSWERS (one per completed answer, #80) or
# "assistant" (every attempt, failed and timed-out ones included, #216). The record points both ways; Jordan
# decides (Raven e7546fefa7ea, d9413aa8b344).
ASSISTANT_COUNTED_FROM: str | None = OPEN
ASSISTANT_COUNTS = {ASSISTANT_ANSWERS, "assistant"}

# The first period ("YYYY-MM") whose assistant usage is charged. Earlier periods never are. (Raven 45f4f68e1a9d)
ASSISTANT_BILLING_FROM: str | None = OPEN

# Merchants who pay nothing for the assistant, e.g. Bloom & Co's "all features included" order form until Sam
# clears it. A frozenset of merchant ids once decided; frozenset() means nobody is exempt. (Raven 037e55094784)
ASSISTANT_EXEMPT: frozenset[str] | None = OPEN

# Whether merchants who installed from the Shopify App Store (merchants.install_source) are charged for the
# assistant through Stripe here. False skips them (Shopify Billing would be separate work). (Raven faed86e26de0)
ASSISTANT_APP_STORE_VIA_STRIPE: bool | None = OPEN


def assistant_open_calls() -> list[str]:
    """What still has to be decided before the assistant is charged. Empty means it is billed."""
    missing = []
    if ASSISTANT_COUNTED_FROM is OPEN:
        missing.append("ASSISTANT_COUNTED_FROM")
    if ASSISTANT_BILLING_FROM is OPEN:
        missing.append("ASSISTANT_BILLING_FROM")
    if ASSISTANT_EXEMPT is OPEN:
        missing.append("ASSISTANT_EXEMPT")
    if ASSISTANT_APP_STORE_VIA_STRIPE is OPEN:
        missing.append("ASSISTANT_APP_STORE_VIA_STRIPE")
    if FEATURE_LABEL.get("assistant") is OPEN:
        missing.append("FEATURE_LABEL['assistant']")
    return missing


def metered() -> dict[str, tuple[str | None, str, str]]:
    """feature -> (the usage_daily feature it is counted from, the plan key for its allowance, the plan key for
    its price past the allowance)."""
    if ASSISTANT_COUNTED_FROM not in ASSISTANT_COUNTS | {OPEN}:
        raise ValueError(f"ASSISTANT_COUNTED_FROM must be one of {sorted(ASSISTANT_COUNTS)}")
    return {
        "labels": ("labels", "labels_per_month", "extra_label_price"),
        "assistant": (ASSISTANT_COUNTED_FROM, "assistant_per_month", "extra_assistant_price"),
    }


def billed(feature: str, period: str) -> bool:
    """Whether a feature is charged for a period at all."""
    if feature != "assistant":
        return True
    return not assistant_open_calls() and period >= ASSISTANT_BILLING_FROM


def charged_merchant(feature: str, merchant_id: str, source_of: dict[str, str]) -> bool:
    """Whether this merchant is charged for this feature; `source_of` maps a merchant to its install source."""
    if feature != "assistant":
        return True
    if merchant_id in ASSISTANT_EXEMPT:
        return False
    return ASSISTANT_APP_STORE_VIA_STRIPE or source_of.get(merchant_id) != APP_STORE


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str],
                source_of: dict[str, str] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, usage feature): count}; `plan_of` maps a merchant to its plan name and
    `source_of` to its install source. Charges are named by the billing feature (metered()'s key)."""
    source_of = source_of or {}
    meter = metered()
    usage_feature_of = {usage_feature: feature for feature, (usage_feature, _, _) in meter.items() if usage_feature}
    charges = []
    for (merchant_id, usage_feature), used in sorted(totals.items()):
        feature = usage_feature_of.get(usage_feature)
        if feature is None:
            continue  # a count nothing is billed from
        if not billed(feature, period) or not charged_merchant(feature, merchant_id, source_of):
            continue
        _, allowance_key, price_key = meter[feature]
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


BATCH = 100  # charges per transaction (#148): one transaction for the whole run held the lock past the Stripe calls


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def run(usage, plan_of: dict[str, str], customer_of: dict[str, str], stripe, posted, *, period: str,
        source_of: dict[str, str] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    """
    features = {usage_feature for feature, (usage_feature, _, _) in metered().items() if billed(feature, period)}
    totals = period_totals(usage, period, features=features)
    count = 0
    for batch in batches(charges_for(period, totals, plan_of, source_of), BATCH):
        with posted.transaction():
            for charge in batch:
                if post_charge(stripe, posted, customer_of[charge.merchant_id], charge):
                    count += 1
    return count


def main(today: date | None = None) -> int:  # pragma: no cover - needs Postgres and Stripe
    import stripe

    from app.billing.posted import PostedCharges
    from app.core.db import transaction
    from app.usage.store import UsageStore

    with transaction() as cur:
        cur.execute(
            "SELECT id, plan, stripe_customer_id, install_source FROM merchants WHERE stripe_customer_id IS NOT NULL"
        )
        rows = cur.fetchall()
    plan_of = {row[0]: row[1] for row in rows}
    customer_of = {row[0]: row[2] for row in rows}
    source_of = {row[0]: row[3] for row in rows}
    period = closed_period(today or date.today())
    if not billed("assistant", period):
        print(f"billing: assistant not charged for {period}; open: {', '.join(assistant_open_calls()) or 'none'}")
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period, source_of=source_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
