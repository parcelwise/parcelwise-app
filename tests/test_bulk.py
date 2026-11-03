from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.bulk import (
    MAX_ORDERS,
    AllowanceExceeded,
    BulkLine,
    BulkTooLarge,
    CarrierNotSupported,
    buy_labels,
    check_allowance,
    idempotency_key,
    quote_batch,
    total_price,
)
from app.labels.carriers import CarrierError
from app.labels.purchase import Label
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


def no_wait(seconds):
    pass


def _line(order_id, price="5.40"):
    rate = Rate("usps", "ground_advantage", Decimal(price), datetime.now(UTC), f"rate_{order_id}")
    return BulkLine(FakeOrder(order_id), rate, Decimal(price))


@pytest.fixture
def fake(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    return carrier


def no_label(order):
    return None


def test_one_purchase_per_order_with_its_own_key(fake):
    outcomes = buy_labels(
        [_line("o1"), _line("o2"), _line("o3")],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        sleep=no_wait,
        live_label=no_label,
    )
    assert sorted(fake.bought) == ["bulk:b1:o1", "bulk:b1:o2", "bulk:b1:o3"]
    assert [o.order_id for o in outcomes] == ["o1", "o2", "o3"]
    assert all(o.status == "bought" for o in outcomes)


def test_order_with_a_live_label_is_reprinted_not_bought_again(fake):
    existing = Label("o2", "usps", "TRK-OLD", Decimal("5.40"), "https://labels.test/o2.pdf")
    outcomes = buy_labels(
        [_line("o1"), _line("o2")],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        sleep=no_wait,
        live_label=lambda order: existing if order.id == "o2" else None,
    )
    assert fake.bought == ["bulk:b1:o1"]
    assert outcomes[1].status == "reprint"
    assert outcomes[1].label is existing


def test_key_is_stable_for_order_and_batch():
    assert idempotency_key("b1", "o1") == idempotency_key("b1", "o1")
    assert idempotency_key("b1", "o1") != idempotency_key("b2", "o1")


def test_total_is_the_sum_of_shown_prices():
    assert total_price([_line("o1", "5.40"), _line("o2", "7.15")]) == Decimal("12.55")


def test_batch_over_the_limit_buys_nothing(fake):
    with pytest.raises(BulkTooLarge):
        buy_labels(
            [_line(f"o{i}") for i in range(MAX_ORDERS + 1)],
            batch_id="b1",
            plan="growth",
            used_this_month=0,
            sleep=no_wait,
            live_label=no_label,
        )
    assert fake.bought == []


def test_free_plan_batch_past_allowance_is_refused_with_labels_left():
    with pytest.raises(AllowanceExceeded) as err:
        check_allowance("free", used_this_month=45, count=6)
    assert err.value.remaining == 5


def test_free_plan_batch_within_allowance_passes():
    check_allowance("free", used_this_month=45, count=5)


def test_plans_that_pay_for_extra_labels_or_are_unlimited_are_not_refused():
    check_allowance("starter", used_this_month=999, count=200)
    check_allowance("growth", used_this_month=10_000, count=200)


def test_stale_quote_is_skipped_with_a_reason_and_the_rest_still_buy(fake):
    old = Rate("usps", "ground_advantage", Decimal("5.40"), datetime.now(UTC) - timedelta(minutes=11), "rate_old")
    stale = BulkLine(FakeOrder("o2"), old, Decimal("5.40"))
    outcomes = buy_labels(
        [_line("o1"), stale, _line("o3")],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        sleep=no_wait,
        live_label=no_label,
    )
    assert sorted(fake.bought) == ["bulk:b1:o1", "bulk:b1:o3"]
    assert outcomes[1].status == "stale"
    assert outcomes[1].reason


def test_changed_price_is_skipped_not_bought(fake):
    line = _line("o1", "5.40")
    changed = BulkLine(line.order, line.rate, Decimal("4.99"))
    [outcome] = buy_labels(
        [changed],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        sleep=no_wait,
        live_label=no_label,
    )
    assert outcome.status == "stale"
    assert fake.bought == []


def test_carrier_failure_is_listed_and_the_rest_still_buy(monkeypatch):
    class FailsForO2(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "o2":
                raise CarrierError("address not deliverable")
            return super().buy(order, rate, idempotency_key=idempotency_key)

    carrier = FailsForO2()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    outcomes = buy_labels(
        [_line("o1"), _line("o2"), _line("o3")],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        sleep=no_wait,
        live_label=no_label,
    )
    assert [o.status for o in outcomes] == ["bought", "failed", "bought"]
    assert outcomes[1].reason == "address not deliverable"
    assert sorted(carrier.bought) == ["bulk:b1:o1", "bulk:b1:o3"]


def test_purchases_are_paced_to_forty_a_minute(fake):
    now = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    buy_labels(
        [_line("o1"), _line("o2"), _line("o3")],
        batch_id="b1",
        plan="growth",
        used_this_month=0,
        live_label=no_label,
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert waits == [1.5, 1.5]
    assert len(fake.bought) == 3


def test_limits_are_carrier_ops_numbers():
    from app.labels import bulk

    assert bulk.MAX_ORDERS == 200
    assert bulk.PURCHASES_PER_MINUTE == 40


def test_ups_lines_are_refused_before_anything_is_bought(fake):
    ups = Rate("ups", "ground", Decimal("7.00"), datetime.now(UTC), "rate_ups")
    with pytest.raises(CarrierNotSupported):
        buy_labels(
            [_line("o1"), BulkLine(FakeOrder("o2"), ups, Decimal("7.00"))],
            batch_id="b1",
            plan="growth",
            used_this_month=0,
            live_label=no_label,
            sleep=no_wait,
        )
    assert fake.bought == []


def test_ups_lines_are_refused_at_the_quote_step():
    ups = Rate("ups", "ground", Decimal("7.00"), datetime.now(UTC), "rate_ups")
    with pytest.raises(CarrierNotSupported):
        quote_batch([_line("o1"), BulkLine(FakeOrder("o2"), ups, Decimal("7.00"))], plan="growth", used_this_month=0)


def test_starter_quote_shows_labels_past_allowance_and_extra_charge():
    lines = [_line(f"o{i}", "5.00") for i in range(200)]
    quote = quote_batch(lines, plan="starter", used_this_month=900)
    assert quote.carrier_total == Decimal("1000.00")
    assert quote.labels_past_allowance == 100
    assert quote.extra_charge == Decimal("8.00")
    assert quote.total == Decimal("1008.00")


def test_starter_already_past_allowance_pays_extra_on_every_label():
    quote = quote_batch([_line("o1", "5.00"), _line("o2", "5.00")], plan="starter", used_this_month=1_200)
    assert quote.labels_past_allowance == 2
    assert quote.extra_charge == Decimal("0.16")


def test_quote_within_allowance_or_unlimited_has_no_extra():
    lines = [_line("o1", "5.40"), _line("o2", "7.15")]
    for plan, used in (("starter", 0), ("growth", 50_000), ("free", 48)):
        quote = quote_batch(lines, plan=plan, used_this_month=used)
        assert quote.labels_past_allowance == 0
        assert quote.extra_charge == Decimal(0)
        assert quote.total == Decimal("12.55")


def test_free_plan_batch_past_allowance_buys_nothing(fake):
    with pytest.raises(AllowanceExceeded):
        buy_labels(
            [_line("o1"), _line("o2")],
            batch_id="b1",
            plan="free",
            used_this_month=49,
            live_label=no_label,
            sleep=no_wait,
        )
    assert fake.bought == []


def test_free_plan_quote_past_allowance_is_refused_before_the_confirm_step():
    with pytest.raises(AllowanceExceeded) as err:
        quote_batch([_line("o1"), _line("o2")], plan="free", used_this_month=49)
    assert err.value.remaining == 1
