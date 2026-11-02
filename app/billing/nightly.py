"""The nightly billing job: the only thing that posts charges (ADR 0006). Runs after the usage rollup.

For the billing period that closed, for each metered feature: walk usage_daily by cursor, total per merchant,
take the plan's allowance off, and post one charge per merchant and feature. Nothing charges at purchase time.
A new metered feature is a plan entry and a usage feature, not a code path of its own here.

Every charge is idempotent (ADR 0007), so the job can be re-run for a period. It runs on the first of the month
for the month that just closed, and again every night after that for anything a failed batch left behind.
"""

from dataclasses import dataclass, field
from datetime import date

from app.billing.charges import Charge, post_charge
from app.billing.open_calls import Open, is_open
from app.billing.plans import PLANS
from app.shopify.install import APP_STORE
from app.usage.daily import ASSISTANT_ANSWERED, period_totals


@dataclass(frozen=True)
class Metered:
    """How one feature is charged. Any field still `Open` holds that feature's charges until it is answered."""

    allowance: str  # the plan key for what the subscription includes
    price: str  # the plan key for the price of each use past the allowance
    counted_from: str | Open = ""  # the usage_daily feature the billable count is read from; "" = the feature
    first_period: str | Open | None = None  # the first month ("YYYY-MM") that is charged; None = every month
    exempt: frozenset[str] | Open = frozenset()  # merchants never charged for this feature
    charge_app_store: bool | Open = True  # whether App Store installs are charged here, through Stripe


METERED = {
    "labels": Metered("labels_per_month", "extra_label_price"),
    "assistant": Metered(
        "assistant_answers_per_month",
        "assistant_answer_price",
        counted_from=ASSISTANT_ANSWERED,  # completed answers only, not attempts (Jordan, Raven 75668ac5d832)
        first_period="2026-12",  # December usage, on January's invoice (Priya, Raven 22fc5b84721e)
        # Bloom & Co only, until Sam clears their order form (Sam, Raven c5fd81c49082). Their merchant id is not in
        # the repo; until it is put here, every assistant charge is held so they cannot be charged by mistake.
        exempt=Open("c5fd81c49082", "Bloom & Co's merchant id (merchants.id), to exempt them from assistant charges"),
        # App Store installs are charged through Shopify Billing usage charges, never Stripe (Theo, Raven b9d5a20eb56f).
        # That path is not built yet, so this job leaves them out.
        charge_app_store=False,
    ),
}


@dataclass
class Held:
    """Charges the job did not post because a value they depend on is still open, by the Raven node holding them."""

    by_node: dict[str, set[tuple[str, str]]] = field(default_factory=dict)

    def add(self, value: Open, merchant_id: str, feature: str) -> None:
        self.by_node.setdefault(value.node, set()).add((merchant_id, feature))

    def __len__(self) -> int:
        return len({key for keys in self.by_node.values() for key in keys})


def _first_open(*values):
    return next((value for value in values if is_open(value)), None)


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str], *,
                source_of: dict[str, str] | None = None, held: Held | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, feature): count}; `plan_of` maps a merchant to its plan name; `source_of` maps a
    merchant to its install source (app/shopify/install.py), direct when missing.

    A charge that depends on an open value is not posted; it is recorded in `held` instead.
    """
    held = held if held is not None else Held()
    source_of = source_of or {}
    charges = []
    for (merchant_id, feature), used in sorted(totals.items()):
        metered = METERED[feature]
        plan = PLANS[plan_of[merchant_id]]
        allowance, price = plan[metered.allowance], plan[metered.price]
        if price is None or allowance is None:
            continue  # unlimited, or a plan that stops at its allowance instead of paying
        if isinstance(metered.first_period, str) and period < metered.first_period:
            continue  # before this feature was charged
        if isinstance(metered.exempt, frozenset) and merchant_id in metered.exempt:
            continue
        app_store = source_of.get(merchant_id) == APP_STORE
        if app_store and metered.charge_app_store is False:
            continue
        waiting_on = _first_open(metered.counted_from, metered.first_period, metered.exempt,
                                 metered.charge_app_store if app_store else None, allowance, price)
        if waiting_on is not None:
            held.add(waiting_on, merchant_id, feature)
            continue
        extra = max(0, used - allowance)
        if extra:
            charges.append(Charge(merchant_id, feature, period, extra, price))
    return charges


def billable_totals(usage, period: str) -> dict[tuple[str, str], int]:
    """{(merchant_id, feature): count} for every metered feature, read from usage_daily (ADR 0005).

    A feature whose source count is still open is read from its own usage feature so its held charges can be
    reported; charges_for() holds them either way.
    """
    sources = {}
    for feature, metered in METERED.items():
        source = metered.counted_from if isinstance(metered.counted_from, str) and metered.counted_from else feature
        sources[source] = feature
    read = period_totals(usage, period, features=sources)
    return {(merchant_id, sources[source]): count for (merchant_id, source), count in read.items()}


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
        source_of: dict[str, str] | None = None, held: Held | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    Charges waiting on an open value land in `held`, and post on the first run after it is answered.
    """
    totals = billable_totals(usage, period)
    count = 0
    for batch in batches(charges_for(period, totals, plan_of, source_of=source_of, held=held), BATCH):
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
    held = Held()
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period, source_of=source_of,
                held=held)
    print(f"billing: {count} charges posted for {period}")
    for node, keys in sorted(held.by_node.items()):
        print(f"billing: {len(keys)} charges held for {period}, waiting on Raven node {node}")
    return count


if __name__ == "__main__":
    main()
