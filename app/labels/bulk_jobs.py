"""Bulk label buys run as a background job (Raven decision 5e5e0741c202, Ana Ruiz): 200 orders at 40 a minute takes
about 5 minutes, and the API stops a request after 30 seconds. The merchant can leave the page and come back to
the results.

The API records the job and returns at once (start_bulk_buy). A worker claims it with FOR UPDATE SKIP LOCKED and
keeps the row locked while it buys (run_next_job). If the worker dies, the row is unlocked, still pending, and runs
again with the same batch id, so every purchase reuses its idempotency key and nothing is bought twice.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from app.labels.bulk import AllowanceExceeded, BulkLine, BulkOutcome, buy_labels, check_batch
from app.labels.purchase import Label
from app.labels.rates import Rate


class BulkAlreadyRunning(Exception):
    """This merchant already has a bulk buy running. Nothing was bought."""

    def __init__(self):
        super().__init__("A bulk label buy is already running for your shop. Try again when it finishes.")


@dataclass(frozen=True)
class SelectedLine:
    """One selected order as the merchant approved it, in the form the job keeps until it runs."""

    order_id: str
    rate: Rate
    shown_price: Decimal


def _line_to_json(line: SelectedLine) -> dict:
    r = line.rate
    return {
        "order_id": line.order_id,
        "rate": {
            "carrier": r.carrier,
            "service": r.service,
            "price": str(r.price),
            "quoted_at": r.quoted_at.isoformat(),
            "rate_id": r.rate_id,
        },
        "shown_price": str(line.shown_price),
    }


def _line_from_json(raw: dict) -> SelectedLine:
    r = raw["rate"]
    rate = Rate(r["carrier"], r["service"], Decimal(r["price"]), datetime.fromisoformat(r["quoted_at"]), r["rate_id"])
    return SelectedLine(raw["order_id"], rate, Decimal(raw["shown_price"]))


def start_bulk_buy(
    conn, merchant_id: str, batch_id: str, lines: list[SelectedLine], *, plan: str, used_this_month: int
):
    """Record a bulk buy for the worker and return the job, still pending. Nothing is bought here.

    A batch that will be refused (too big, or past a Free allowance) is refused now, before it is queued. Sending
    the same batch id again returns the same job. A second batch while one is pending
    for the merchant raises BulkAlreadyRunning (Raven decision af32723a4431, Ana Ruiz).
    """
    check_batch([_as_bulk_line(line, order=None) for line in lines], plan=plan, used_this_month=used_this_month)
    payload = json.dumps([_line_to_json(line) for line in lines])
    # ON CONFLICT with no target covers the primary key (a resend of this batch) and the one-pending-per-merchant
    # index (another batch is running), including two requests that race.
    conn.execute(
        "INSERT INTO bulk_label_jobs (id, merchant_id, lines) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (batch_id, merchant_id, payload),
    )
    job = get_job(conn, merchant_id, batch_id)
    if job is None:
        raise BulkAlreadyRunning()
    return job


def _as_bulk_line(line: SelectedLine, *, order) -> BulkLine:
    return BulkLine(order, line.rate, line.shown_price)


@dataclass(frozen=True)
class JobDeps:
    """What a job reads at run time, from outside this module.

    `load_order(merchant_id, order_id)` must only return the merchant's own order, or None.
    `plan_and_usage(merchant_id)` returns (plan, labels used this month), read when the job starts.
    `live_label(order)` returns the order's label that hasn't been voided, or None. It must see labels bought by an
    earlier run of this job that died before finishing, so record each label in its own committed transaction, not
    the job's: then a rerun reprints that order instead of reporting it stale, and the merchant isn't led to buy it
    a second time from the row.
    """

    load_order: Callable[[str, str], object | None]
    plan_and_usage: Callable[[str], tuple[str, int]]
    live_label: Callable[[object], Label | None]
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


def run_next_job(conn, deps: JobDeps) -> str | None:
    """Claim the oldest pending job no other worker holds, run it, and record the outcome. None if none waits.

    The caller commits when this returns; the row stays locked until then.
    """
    row = conn.execute(
        "SELECT id, merchant_id, lines FROM bulk_label_jobs WHERE status = 'pending' "
        "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
    ).fetchone()
    if row is None:
        return None
    job_id, merchant_id, raw = row
    selected = [_line_from_json(item) for item in (json.loads(raw) if isinstance(raw, str) else raw)]

    missing, lines = [], []
    for line in selected:
        order = deps.load_order(merchant_id, line.order_id)
        if order is None:
            missing.append(BulkOutcome(line.order_id, "failed", None, "order not found"))
        else:
            lines.append(_as_bulk_line(line, order=order))

    plan, used = deps.plan_and_usage(merchant_id)
    try:
        bought = buy_labels(
            lines,
            batch_id=job_id,
            plan=plan,
            used_this_month=used,
            live_label=deps.live_label,
            clock=deps.clock,
            sleep=deps.sleep,
        )
    except AllowanceExceeded as refused:
        # Usage can grow between queueing and running; still never buy part of a batch (Raven decision b587e27675e9).
        _finish(conn, job_id, "refused", None, f"Nothing was bought: {refused}.")
        return job_id
    by_order = {o.order_id: o for o in bought + missing}
    outcomes = [by_order[line.order_id] for line in selected]
    _finish(conn, job_id, "done", [_outcome_to_json(o) for o in outcomes], "")
    return job_id


def _outcome_to_json(o: BulkOutcome) -> dict:
    label = None
    if o.label is not None:
        label = {**asdict(o.label), "price": str(o.label.price)}
    return {"order_id": o.order_id, "status": o.status, "label": label, "reason": o.reason}


def _finish(conn, job_id: str, status: str, outcomes, reason: str) -> None:
    conn.execute(
        "UPDATE bulk_label_jobs SET status = %s, outcomes = %s, reason = %s, finished_at = now() WHERE id = %s",
        (status, None if outcomes is None else json.dumps(outcomes), reason, job_id),
    )


def _job(row) -> dict | None:
    if row is None:
        return None
    job_id, status, outcomes, reason, count = row
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    return {"id": job_id, "status": status, "outcomes": outcomes, "reason": reason, "count": count}


_JOB_COLUMNS = "id, status, outcomes, reason, jsonb_array_length(lines)"


def get_job(conn, merchant_id: str, job_id: str) -> dict | None:
    """One of the merchant's bulk buys: pending while it runs, then done (with each order's outcome) or refused."""
    return _job(
        conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM bulk_label_jobs WHERE id = %s AND merchant_id = %s", (job_id, merchant_id)
        ).fetchone()
    )


def latest_job(conn, merchant_id: str) -> dict | None:
    """The merchant's most recent bulk buy, so the Orders page can show its results when they come back."""
    return _job(
        conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM bulk_label_jobs WHERE merchant_id = %s ORDER BY created_at DESC LIMIT 1",
            (merchant_id,),
        ).fetchone()
    )


# One worker runs one job at a time (Raven decision d773fe7fd066, Ana Ruiz: a Postgres table and one worker for v1).
IDLE_SECONDS = 2.0


def work(transaction, deps: JobDeps, *, should_stop: Callable[[], bool] = lambda: False) -> None:
    """One worker slot: claim and run jobs until told to stop, resting when none waits."""
    while not should_stop():
        with transaction() as conn:
            ran = run_next_job(conn, deps)
        if ran is None:
            deps.sleep(IDLE_SECONDS)
