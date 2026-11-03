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


@dataclass(frozen=True)
class Meter:
    """How one charged feature is metered.

    `usage_feature` is the usage_daily feature the quantity is read from. `first_period` ("YYYY-MM") is the first
    month this feature bills; earlier months never do. `install_sources`, when set, limits the charge to
    merchants whose merchants.install_source is in it.
    """

    usage_feature: str
    allowance_key: str
    price_key: str
    first_period: str = ""
    install_sources: frozenset[str] | None = None


# OPEN: assistant billing also needs these answers (Raven task 7fd1f6eb3a29). While any of them is None the
# assistant is not metered at all and the job charges nothing for it.
#   ASSISTANT_USAGE_FEATURE: the usage_daily feature that counts one billable use. Today "assistant" counts
#     every model attempt, failed and timed-out ones included (#216). (Jordan, eb3bcadcccce)
#   ASSISTANT_FIRST_PERIOD: the first month billed, "YYYY-MM". Without it the next run would bill the month
#     that already closed. (Marcus, f2b44c5a2c3e)
#   ASSISTANT_INSTALL_SOURCES: which install sources are charged through Stripe, e.g.
#     frozenset({"direct", "app_store"}) or frozenset({"direct"}). (Theo, da7a587e89f6)
ASSISTANT_USAGE_FEATURE: str | None = None
ASSISTANT_FIRST_PERIOD: str | None = None
ASSISTANT_INSTALL_SOURCES: frozenset[str] | None = None


def metered(*, assistant_usage_feature: str | None = None, assistant_first_period: str | None = None,
            assistant_install_sources: frozenset[str] | None = None) -> dict[str, Meter]:
    """Charged feature -> Meter. The assistant is included only once all of its open inputs are set."""
    meters = {"labels": Meter("labels", "labels_per_month", "extra_label_price")}
    if None not in (assistant_usage_feature, assistant_first_period, assistant_install_sources):
        meters["assistant"] = Meter(assistant_usage_feature, "assistant_per_month", "extra_assistant_price",
                                    first_period=assistant_first_period,
                                    install_sources=assistant_install_sources)
    return meters


METERED = metered(assistant_usage_feature=ASSISTANT_USAGE_FEATURE, assistant_first_period=ASSISTANT_FIRST_PERIOD,
                  assistant_install_sources=ASSISTANT_INSTALL_SOURCES)


def charges_for(period: str, totals: dict[tuple[str, str], int], plan_of: dict[str, str], *,
                meters: dict[str, Meter] | None = None,
                install_source_of: dict[str, str] | None = None) -> list[Charge]:
    """`totals` is {(merchant_id, usage_feature): count}; `plan_of` maps a merchant to its plan name.

    `install_source_of` maps a merchant to merchants.install_source; it is needed only by a meter that limits
    install sources, and a merchant missing from it is not charged by such a meter.
    """
    meters = METERED if meters is None else meters
    charges = []
    for feature, meter in sorted(meters.items()):
        if period < meter.first_period:
            continue
        for (merchant_id, usage_feature), used in sorted(totals.items()):
            if usage_feature != meter.usage_feature:
                continue
            if meter.install_sources is not None and \
                    (install_source_of or {}).get(merchant_id) not in meter.install_sources:
                continue
            plan = PLANS[plan_of[merchant_id]]
            allowance, price = plan[meter.allowance_key], plan[meter.price_key]
            if price is None or allowance is None:
                continue  # unlimited, a plan that stops at its allowance, or a price nobody has set
            extra = max(0, used - allowance)
            if extra:
                charges.append(Charge(merchant_id, feature, period, extra, price))
    return sorted(charges, key=lambda c: (c.merchant_id, c.feature))


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
        meters: dict[str, Meter] | None = None, install_source_of: dict[str, str] | None = None) -> int:
    """Post the period's charges that are not posted yet, BATCH per transaction. Returns how many were posted.

    A batch that fails rolls back its own transaction only; the next run posts it (every charge is idempotent).
    """
    meters = METERED if meters is None else meters
    totals = period_totals(usage, period, features={m.usage_feature for m in meters.values()})
    charges = charges_for(period, totals, plan_of, meters=meters, install_source_of=install_source_of)
    count = 0
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
    install_source_of = {row[0]: row[3] for row in rows}
    period = closed_period(today or date.today())
    count = run(UsageStore(), plan_of, customer_of, stripe, PostedCharges(), period=period,
                install_source_of=install_source_of)
    print(f"billing: {count} charges posted for {period}")
    return count


if __name__ == "__main__":
    main()
