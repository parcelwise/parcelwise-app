"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from dataclasses import dataclass
from datetime import date

from app.billing.charges import Charge, post_charge
from app.billing.plans import PLANS
from app.usage.daily import period_totals

APP_STORE = "app_store"  # merchants.install_source, app/shopify/install.py


@dataclass(frozen=True)
class Metered:
    """One metered feature: the plan keys for its allowance and price, and who it may be charged to.

    `starts`: the first period ("YYYY-MM") charged; earlier periods never are, re-runs included. None: not started.
    `exempt_shops`: shop domains never charged for this feature. None: the list is not confirmed, charge nobody.
    `bill_app_store`: whether App Store installs are charged through Stripe. None: undecided, charge nobody.
    """

    allowance_key: str
    price_key: str
    starts: str | None = "0000-00"
    exempt_shops: frozenset[str] | None = frozenset()
    bill_app_store: bool | None = True

    def ready(self) -> bool:
        return self.starts is not None and self.exempt_shops is not None and self.bill_app_store is not None


# usage feature -> how it is charged. A new metered feature is an entry here and in PLANS (ADR 0006).
METERED = {
    "labels": Metered("labels_per_month", "extra_label_price"),
    # Assistant answers (founders sync 2026-10-29). Each None below is an OPEN call, filled in by its owner.
    # OPEN (Jordan, Raven 6ee6ac89dcf7): usage_daily's "assistant" count is every model attempt (#216); whether
    # merchants pay per attempt or per completed answer must be settled before this entry goes live.
    "assistant": Metered(
        "assistant_answers_per_month",
        "assistant_answer_price",
        starts=None,  # OPEN: first month charged (Priya, Raven 4a9dfb616aee)
        # Bloom & Co stays off per-use charges until Sam clears their order form (Priya, Raven 8d8478f52e9a).
        # OPEN: their shop domain(s), confirmed, go here.
        exempt_shops=None,
        bill_app_store=None,  # OPEN: App Store installs and Shopify Billing (Theo, Raven ff346d951479)
    ),
}


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str], *,
                shop_of: dict[str, str] | None = None, source_of: dict[str, str] | None = None,
                metered: dict[str, Metered] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, feature): count}; `plan_of` maps a merchant to its plan name.

    `shop_of` and `source_of` map a merchant to its shop domain and install source. A merchant whose shop domain
    or install source is unknown is not charged for a feature that needs it.
    """
    metered = METERED if metered is None else metered
    shop_of, source_of = shop_of or {}, source_of or {}
    charges = []
    for (merchant_id, feature), used in sorted(totals.items()):
        rule = metered[feature]
        if not chargeable(rule, period, shop_of.get(merchant_id), source_of.get(merchant_id)):
            continue
        plan = PLANS[plan_of[merchant_id]]
        allowance, price = plan[rule.allowance_key], plan[rule.price_key]
        if price is None or allowance is None:
            continue  # unlimited, or a plan that stops at its allowance instead of paying
        extra = max(0, used - allowance)
        if extra:
            charges.append(Charge(merchant_id, feature, period, extra, price))
    return charges


def chargeable(rule: Metered, period: str, shop: str | None, source: str | None) -> bool:
    if not rule.ready() or period < rule.starts:
        return False
    if rule.exempt_shops and (shop is None or shop in rule.exempt_shops):
        return False
    return rule.bill_app_store or (source is not None and source != APP_STORE)


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
        shop_of: dict[str, str] | None = None, source_of: dict[str, str] | None = None,
        metered: dict[str, Metered] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    Features whose open inputs are not filled in are not read at all.
    """
    metered = METERED if metered is None else metered
    live = {feature: rule for feature, rule in metered.items() if rule.ready()}
    totals = period_totals(usage, period, features=live)
    count = 0
    charges = charges_for(period, totals, plan_of, shop_of=shop_of, source_of=source_of, metered=live)
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
            "SELECT id, plan, stripe_customer_id, shop_domain, install_source FROM merchants "
            "WHERE stripe_customer_id IS NOT NULL"
        )
        rows = cur.fetchall()
    plan_of = {row[0]: row[1] for row in rows}
    customer_of = {row[0]: row[2] for row in rows}
    shop_of = {row[0]: row[3] for row in rows}
    source_of = {row[0]: row[4] for row in rows}
    period = closed_period(today or date.today())
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period,
                shop_of=shop_of, source_of=source_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
