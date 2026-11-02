from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.batch import (
    ALREADY_LABELED,
    BOUGHT,
    FAILED,
    MAX_BATCH_ORDERS,
    NEEDS_REQUOTE,
    BatchItem,
    BatchRefused,
    batch_idempotency_key,
    plan_batch,
    run_item,
)
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


@pytest.fixture
def fake(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    return carrier


def items(n, rate, price=Decimal("5.40")):
    return [BatchItem(FakeOrder(f"o{i}"), rate, price) for i in range(n)]


def test_each_order_gets_its_own_stable_key(fake, fresh_rate):
    for item in items(2, fresh_rate):
        run_item("b1", item, attempt=1, has_live_label=False)
    assert fake.bought == ["batch:b1:o0:1", "batch:b1:o1:1"]
    assert batch_idempotency_key("b1", "o0", 1) == batch_idempotency_key("b1", "o0", 1)


def test_a_merchant_retry_gets_a_new_key(fake, fresh_rate):
    item = BatchItem(FakeOrder("o1"), fresh_rate, Decimal("5.40"))
    run_item("b1", item, attempt=2, has_live_label=False)
    assert fake.bought == ["batch:b1:o1:2"]


def test_changed_price_is_not_bought_and_comes_back_for_approval(fake, fresh_rate):
    outcome = run_item("b1", BatchItem(FakeOrder("o1"), fresh_rate, Decimal("4.99")), attempt=1, has_live_label=False)
    assert outcome.status == NEEDS_REQUOTE
    assert fake.bought == []


def test_quote_that_expired_mid_batch_is_not_bought(fake):
    old = Rate("usps", "ground_advantage", Decimal("5.40"), datetime.now(timezone.utc) - timedelta(minutes=11), "r")
    outcome = run_item("b1", BatchItem(FakeOrder("o1"), old, Decimal("5.40")), attempt=1, has_live_label=False)
    assert outcome.status == NEEDS_REQUOTE
    assert fake.bought == []


def test_order_with_a_live_label_is_never_bought_again(fake, fresh_rate):
    outcome = run_item("b1", BatchItem(FakeOrder("o1"), fresh_rate, Decimal("5.40")), attempt=1, has_live_label=True)
    assert outcome.status == ALREADY_LABELED
    assert fake.bought == []


def test_carrier_failure_is_reported_and_the_rest_still_buy(monkeypatch, fresh_rate):
    class Flaky(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "o1":
                raise CarrierError("address not deliverable")
            return super().buy(order, rate, idempotency_key=idempotency_key)

    flaky = Flaky()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: flaky)
    outcomes = [run_item("b1", item, attempt=1, has_live_label=False) for item in items(3, fresh_rate)]
    assert [o.status for o in outcomes] == [BOUGHT, FAILED, BOUGHT]
    assert outcomes[1].error == "address not deliverable"


def test_batch_over_allowance_is_refused_whole_with_labels_left(fresh_rate):
    with pytest.raises(BatchRefused) as refused:
        plan_batch(items(200, fresh_rate), plan="starter", used_this_month=850, labeled_order_ids=set())
    assert refused.value.labels_left == 150


def test_already_labeled_orders_dont_count_against_allowance(fresh_rate):
    plan = plan_batch(items(3, fresh_rate), plan="free", used_this_month=48, labeled_order_ids={"o0"})
    assert [i.order.id for i in plan.to_buy] == ["o1", "o2"]
    assert [i.order.id for i in plan.already_labeled] == ["o0"]


def test_batch_is_capped_at_500_orders(fresh_rate):
    plan_batch(items(MAX_BATCH_ORDERS, fresh_rate), plan="growth", used_this_month=0, labeled_order_ids=set())
    with pytest.raises(BatchRefused):
        plan_batch(items(MAX_BATCH_ORDERS + 1, fresh_rate), plan="growth", used_this_month=0, labeled_order_ids=set())


def test_duplicate_orders_are_refused(fresh_rate):
    item = BatchItem(FakeOrder("o1"), fresh_rate, Decimal("5.40"))
    with pytest.raises(BatchRefused):
        plan_batch([item, item], plan="growth", used_this_month=0, labeled_order_ids=set())


def test_orders_no_longer_unfulfilled_are_dropped_and_the_rest_bought(fresh_rate):
    plan = plan_batch(
        items(3, fresh_rate), plan="free", used_this_month=48, labeled_order_ids=set(), closed_order_ids={"o1"}
    )
    assert [i.order.id for i in plan.to_buy] == ["o0", "o2"]
    assert [i.order.id for i in plan.dropped] == ["o1"]


def test_dropped_orders_dont_count_against_allowance(fresh_rate):
    plan = plan_batch(
        items(3, fresh_rate), plan="free", used_this_month=48, labeled_order_ids=set(), closed_order_ids={"o0"}
    )
    assert len(plan.to_buy) == 2


def test_a_carrier_timeout_is_marked_so_the_retry_keeps_the_key(monkeypatch, fresh_rate):
    class Slow(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            raise CarrierError("USPS timed out", retryable=True)

    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: Slow())
    outcome = run_item("b1", BatchItem(FakeOrder("o1"), fresh_rate, Decimal("5.40")), attempt=1, has_live_label=False)
    assert outcome.status == FAILED and outcome.timed_out


def test_other_carrier_failures_are_not_marked_as_timeouts(monkeypatch, fresh_rate):
    class Rejects(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            raise CarrierError("address not deliverable")

    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: Rejects())
    outcome = run_item("b1", BatchItem(FakeOrder("o1"), fresh_rate, Decimal("5.40")), attempt=1, has_live_label=False)
    assert outcome.status == FAILED and not outcome.timed_out


class _Orders:
    """Answers the orders lookup in _closed_order_ids with (id, status) rows."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params):
        _merchant_id, order_ids = params
        rows = [(i, s) for i, s in self.rows if i in order_ids]
        return type("R", (), {"fetchall": lambda self: rows})()


def test_order_that_isnt_the_merchants_refuses_the_whole_batch():
    from app.labels.batch import _closed_order_ids

    with pytest.raises(BatchRefused):
        _closed_order_ids(_Orders([("o0", "unfulfilled")]), "bloom", ["o0", "someone_elses"])


def test_fulfilled_and_cancelled_orders_are_reported_as_closed():
    from app.labels.batch import _closed_order_ids

    conn = _Orders([("o0", "unfulfilled"), ("o1", "fulfilled"), ("o2", "cancelled")])
    assert _closed_order_ids(conn, "bloom", ["o0", "o1", "o2"]) == {"o1", "o2"}
