"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from datetime import date

from app.billing import plans
from app.billing.charges import Charge, post_charge
from app.billing.plans import PLANS, Open
from app.shopify.install import APP_STORE
from app.usage.daily import ASSISTANT_ANSWERS, period_totals

# feature -> (the plan key for its allowance, the plan key for its price past the allowance)
METERED = {
    "labels": ("labels_per_month", "extra_label_price"),
    ASSISTANT_ANSWERS: ("assistant_per_month", "assistant_price"),  # completed answers, not attempts
}

# feature -> the first billing period it is charged for. Periods before it are never billed, whatever a re-run
# reads. The assistant starts with December 2026, posted on January 1 (Oct 29 founders sync, Raven 43ee1379bf6a).
BILLED_FROM = {ASSISTANT_ANSWERS: "2026-12"}

# Features App Store installs are not charged for on our Stripe invoice: Shopify Billing is theirs, and new usage
# charges skip them until they are wired to Shopify usage records (Theo, decision 5030d2c32446, PR #160).
# Extra labels predate that rule and are unchanged.
STRIPE_ONLY = {ASSISTANT_ANSWERS}


class OpenDecision(Exception):
    """A plan value this period needs is still undecided (app/billing/plans.py). Nothing is posted for it."""


def billed_features(period: str) -> set[str]:
    """The metered features that bill for `period`."""
    return {feature for feature in METERED if period >= BILLED_FROM.get(feature, "")}


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str],
                source_of: dict[str, str] | None = None, shop_of: dict[str, str] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, feature): count}; `plan_of` maps a merchant to its plan name; `source_of` to
    its install source (app/shopify/install.py), direct when missing; `shop_of` to its shop domain."""
    charges = []
    billed = billed_features(period)
    source_of, shop_of = source_of or {}, shop_of or {}
    exempt = plans.OFF_PUBLIC_ASSISTANT_RATE if ASSISTANT_ANSWERS in billed else frozenset()
    if isinstance(exempt, Open) and any(feature == ASSISTANT_ANSWERS for _, feature in totals):
        raise OpenDecision(f"assistant charges held back: {exempt.decision}")
    for (merchant_id, feature), used in sorted(totals.items()):
        if feature not in billed:
            continue
        if feature in STRIPE_ONLY and source_of.get(merchant_id) == APP_STORE:
            continue
        if feature == ASSISTANT_ANSWERS and shop_of.get(merchant_id) in exempt:
            continue  # off the public rate (plans.OFF_PUBLIC_ASSISTANT_RATE)
        allowance_key, price_key = METERED[feature]
        plan = PLANS[plan_of[merchant_id]]
        allowance, price = plan[allowance_key], plan[price_key]
        for key, value in ((allowance_key, allowance), (price_key, price)):
            if isinstance(value, Open):
                raise OpenDecision(f"{plan_of[merchant_id]}.{key} is not decided: {value.decision}")
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
        source_of: dict[str, str] | None = None, shop_of: dict[str, str] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    A feature whose plan values are still Open posts nothing; the other features post, and then the run raises
    OpenDecision so the job fails loudly. Once the value is filled in, the next night posts what was held back.
    """
    totals = period_totals(usage, period, features=billed_features(period))
    charges, undecided = [], []
    for feature in sorted(billed_features(period)):
        try:
            charges += charges_for(period, {k: v for k, v in totals.items() if k[1] == feature}, plan_of, source_of, shop_of)
        except OpenDecision as open_value:
            undecided.append(str(open_value))
    count = 0
    for batch in batches(charges, BATCH):
        with posted.transaction():
            for charge in batch:
                if post_charge(stripe, posted, customer_of[charge.merchant_id], charge):
                    count += 1
    if undecided:
        raise OpenDecision(f"{count} charges posted for {period}; held back: " + "; ".join(undecided))
    return count


def main(today: date | None = None) -> int:  # pragma: no cover - needs Postgres and Stripe
    import stripe

    from app.billing.posted import PostedCharges
    from app.core.db import transaction
    from app.usage.store import UsageStore

    with transaction() as cur:
        cur.execute(
            "SELECT id, plan, stripe_customer_id, install_source, shop_domain FROM merchants "
            "WHERE stripe_customer_id IS NOT NULL"
        )
        rows = cur.fetchall()
    plan_of = {row[0]: row[1] for row in rows}
    customer_of = {row[0]: row[2] for row in rows}
    source_of = {row[0]: row[3] for row in rows}
    shop_of = {row[0]: row[4] for row in rows}
    period = closed_period(today or date.today())
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period, source_of=source_of,
                shop_of=shop_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
