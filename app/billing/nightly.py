"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is an entry in METERED, a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.

A feature with any Undecided input (app/billing/plans.py) posts nothing at all and is reported as waiting, so
an open price, allowance, start month, exemption list or App Store rule can never be guessed into a charge.
"""

from dataclasses import dataclass, field
from datetime import date

from app.billing.charges import Charge, post_charge
from app.billing.plans import PLANS, Undecided, is_undecided
from app.shopify.install import APP_STORE
from app.usage.daily import ASSISTANT_ANSWERS, period_totals

CHARGE = "charge"  # App Store installs are charged through Stripe like everyone else
SKIP = "skip"  # App Store installs are not charged for this feature


@dataclass(frozen=True)
class Metered:
    """One metered feature: what it is called on the invoice, which usage_daily count it bills, and its rules."""

    feature: str  # the charge's feature: its idempotency key and invoice line (ADR 0007, #124)
    usage_feature: str | Undecided  # which usage_daily feature is billed (ADR 0005: ask app/usage once per feature)
    allowance_key: str  # the plan key for what the subscription includes
    price_key: str  # the plan key for the price past the allowance
    starts: str | Undecided | None = None  # first billed period, "YYYY-MM"; None means no start limit
    exempt: frozenset[str] | Undecided = field(default_factory=frozenset)  # merchants never charged for it
    app_store: str | Undecided = CHARGE  # CHARGE or SKIP for merchants who installed from the App Store

    def open_inputs(self) -> list[Undecided]:
        values = [self.usage_feature, self.starts, self.exempt, self.app_store]
        for plan in PLANS.values():
            values += [plan[self.allowance_key], plan[self.price_key]]
        unique = []
        for value in values:
            if is_undecided(value) and value not in unique:
                unique.append(value)
        return unique


METERED = {
    "labels": Metered("labels", "labels", "labels_per_month", "extra_label_price"),
    # Starter and Growth (Priya, Oct 29); through this job, never at question time (Marcus, Oct 29).
    "assistant": Metered(
        "assistant",
        usage_feature=ASSISTANT_ANSWERS,  # completed answers, one per request id; not attempts (Jordan)
        allowance_key="assistant_answers_per_month",
        price_key="extra_assistant_answer_price",
        starts=Undecided("Which month is the first one we charge assistant usage for?", "Marcus Lee"),
        exempt=Undecided("Which merchants are exempt from assistant charges (Bloom & Co, anyone else)?",
                         "Priya Shah"),
        app_store=Undecided("Do App Store installs get assistant charges through Stripe, or not for now?",
                            "Theo Grant"),
    ),
}


def ready(metered: dict[str, Metered] | None = None) -> dict[str, Metered]:
    """The metered features with every input decided: the only ones this job bills."""
    metered = METERED if metered is None else metered
    return {name: m for name, m in metered.items() if not m.open_inputs()}


def waiting(metered: dict[str, Metered] | None = None) -> dict[str, list[Undecided]]:
    """{feature: its open inputs} for the features this job will not bill yet."""
    metered = METERED if metered is None else metered
    return {name: m.open_inputs() for name, m in metered.items() if m.open_inputs()}


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str], *,
                install_of: dict[str, str] | None = None, metered: dict[str, Metered] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, usage feature): count}; `plan_of` maps a merchant to its plan name;
    `install_of` maps a merchant to its install source (app/shopify/install.py), direct when missing."""
    install_of = install_of or {}
    by_usage = {m.usage_feature: m for m in ready(metered).values()}
    charges = []
    for (merchant_id, usage_feature), used in sorted(totals.items()):
        m = by_usage.get(usage_feature)
        if m is None:
            continue
        if m.starts is not None and period < m.starts:
            continue
        if merchant_id in m.exempt:
            continue
        if m.app_store == SKIP and install_of.get(merchant_id) == APP_STORE:
            continue
        plan = PLANS[plan_of[merchant_id]]
        allowance, price = plan[m.allowance_key], plan[m.price_key]
        if price is None or allowance is None:
            continue  # unlimited, or a plan that stops at its allowance instead of paying
        extra = max(0, used - allowance)
        if extra:
            charges.append(Charge(merchant_id, m.feature, period, extra, price))
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
        install_of: dict[str, str] | None = None, metered: dict[str, Metered] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    """
    features = {m.usage_feature for m in ready(metered).values()}
    totals = period_totals(usage, period, features=features)
    count = 0
    charges = charges_for(period, totals, plan_of, install_of=install_of, metered=metered)
    for batch in batches(charges, BATCH):
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
    install_of = {row[0]: row[3] for row in rows}
    period = closed_period(today or date.today())
    for feature, inputs in waiting().items():
        for value in inputs:
            print(f"billing: not charging {feature} yet, {value}")
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period, install_of=install_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
