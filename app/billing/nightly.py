"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from datetime import date

from app.billing.charges import FEATURE_LABEL, Charge, post_charge
from app.billing.plans import PLANS
from app.shopify.install import APP_STORE
from app.usage.daily import period_totals

# feature -> (the plan key for its allowance, the plan key for its price past the allowance)
METERED = {
    "labels": ("labels_per_month", "extra_label_price"),
    "assistant": ("assistant_answers_per_month", "extra_assistant_price"),
}

# Rollout inputs for a metered feature that is not billed for everyone from the start. A feature listed here
# posts nothing until every input is filled in by its owner; a feature not listed (labels) is unaffected.
#   billed_from: the first period ("YYYY-MM") charged; earlier periods never are.
#   exempt:      merchant ids never charged for the feature (customer deals).
#   app_store:   "bill" charges App Store installs through Stripe like everyone else; "skip" leaves them out.
GATES = {
    "assistant": {
        # OPEN, Marcus Lee (Raven: "Which month is the first one we bill assistant usage for?").
        "billed_from": None,
        # DECIDED, Priya Shah (Oct 29 pricing sync): Bloom & Co pays no per-use charge until Sam clears the
        # "all features included" clause in their order form. OPEN: their merchant id, filled in as a frozenset.
        "exempt": None,
        # OPEN, Theo Grant (Raven: "Do App Store merchants get assistant charges through Stripe, through
        # Shopify Billing, or not at all for now?"). Shopify Billing itself is not built; that answer means "skip".
        "app_store": None,
    },
}


def gate_ready(feature: str) -> bool:
    """True when the feature has no gate, or every input of its gate and its invoice wording are filled in."""
    gate = GATES.get(feature)
    if gate is None:
        return True
    return feature in FEATURE_LABEL and all(value is not None for value in gate.values())


def billable_features() -> list[str]:
    return sorted(feature for feature in METERED if gate_ready(feature))


def _gated_out(feature: str, merchant_id: str, period: str, install_source_of: dict[str, str]) -> bool:
    gate = GATES.get(feature)
    if gate is None:
        return False
    if not gate_ready(feature) or period < gate["billed_from"] or merchant_id in gate["exempt"]:
        return True
    return gate["app_store"] == "skip" and install_source_of.get(merchant_id) == APP_STORE


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str],
                install_source_of: dict[str, str] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, feature): count}; `plan_of` maps a merchant to its plan name;
    `install_source_of` maps a merchant to where it installed from (app/shopify/install.py)."""
    charges = []
    for (merchant_id, feature), used in sorted(totals.items()):
        if _gated_out(feature, merchant_id, period, install_source_of or {}):
            continue
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


BATCH = 100  # charges per transaction (#148): one transaction for the whole run held the lock past the Stripe calls


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def run(usage, plan_of: dict[str, str], customer_of: dict[str, str], stripe, posted, *, period: str,
        install_source_of: dict[str, str] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    """
    totals = period_totals(usage, period, features=billable_features())
    count = 0
    for batch in batches(charges_for(period, totals, plan_of, install_source_of), BATCH):
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
        cur.execute("SELECT id, plan, stripe_customer_id, install_source FROM merchants "
                    "WHERE stripe_customer_id IS NOT NULL")
        rows = cur.fetchall()
    plan_of = {row[0]: row[1] for row in rows}
    customer_of = {row[0]: row[2] for row in rows}
    install_source_of = {row[0]: row[3] for row in rows}
    period = closed_period(today or date.today())
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period,
                install_source_of=install_source_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
