"""Bulk label jobs in Postgres: preview, enqueue, and the steps the label-worker runs.

Rules live in app/labels/bulk.py; this file only stores and loads. A job is a row in bulk_label_jobs with one
bulk_label_job_items row per confirmed order, in the order the merchant saw them.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from app.core import config
from app.labels.bulk import AlreadyLabelled, BulkItem, BulkPlan, buy_all, idempotency_key, plan_bulk
from app.labels.purchase import Label, StaleRateError
from app.labels.rates import Rate

# A job left 'running' this long was dropped by a worker that died; it is picked up again. Retrying is safe:
# every order keeps the same idempotency key, and bought orders are not tried again.
STUCK_AFTER = "15 minutes"

# Labels this merchant bought this calendar month (database time zone) that haven't been voided.
USED_THIS_MONTH = (
    "SELECT count(*) FROM labels l JOIN orders o ON o.id = l.order_id "
    "WHERE o.merchant_id = %s AND l.voided_at IS NULL AND l.created_at >= date_trunc('month', now())"
)


class BulkBuyingOff(Exception):
    """Bulk label buying is switched off on this server (settings.bulk_label_buying)."""


def _require_bulk_buying() -> None:
    # Refuse rather than queue a job no worker will run: a queued job holds its orders and allowance.
    if not config.settings.bulk_label_buying:
        raise BulkBuyingOff("bulk label buying is switched off")


@dataclass(frozen=True)
class Selection:
    """One order the merchant selected, with the quote they were shown for it."""

    order_id: str
    carrier: str
    service: str
    rate_id: str
    quoted_at: datetime
    shown_price: Decimal


@dataclass(frozen=True)
class _Ref:
    id: str


def _items(selections: list[Selection]) -> list[BulkItem]:
    return [
        BulkItem(_Ref(s.order_id), Rate(s.carrier, s.service, s.shown_price, s.quoted_at, s.rate_id), s.shown_price)
        for s in selections
    ]


def _plan(conn, merchant_id: str, selections: list[Selection], *, lock: bool = False) -> BulkPlan:
    """Labels used this month are counted from the labels table: every label bought this calendar month, single
    or bulk, that hasn't been voided (Raven decision 22d823b40cb3, Jordan Okafor). Labels still waiting in another
    of this merchant's jobs count as used too, and their orders as labelled, so two bulk buys can't overspend the
    allowance or buy the same order twice. `lock` holds the merchant row until the transaction ends, so two
    enqueues for one merchant run one after the other."""
    (plan,) = conn.execute(
        "SELECT plan FROM merchants WHERE id = %s" + (" FOR UPDATE" if lock else ""),
        (merchant_id,),
    ).fetchone()
    (used,) = conn.execute(USED_THIS_MONTH, (merchant_id,)).fetchone()
    queued = conn.execute(
        "SELECT i.order_id FROM bulk_label_job_items i JOIN bulk_label_jobs j ON j.id = i.job_id "
        "WHERE j.merchant_id = %s AND i.status = 'pending'",
        (merchant_id,),
    ).fetchall()
    order_ids = [s.order_id for s in selections]
    labelled = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT l.order_id FROM labels l JOIN orders o ON o.id = l.order_id "
            "WHERE o.merchant_id = %s AND l.order_id = ANY(%s) AND l.voided_at IS NULL",
            (merchant_id, order_ids),
        ).fetchall()
    } | {row[0] for row in queued}
    return plan_bulk(
        _items(selections),
        has_live_label=lambda order: order.id in labelled,
        plan=plan,
        used_this_month=used + len(queued),
    )


def plan_json(plan: BulkPlan) -> dict:
    """The shape web/lib/api.ts calls BulkPreview. Order ids keep the order the merchant saw them in."""
    return {
        "toBuy": [item.order.id for item in plan.to_buy],
        "alreadyLabelled": [item.order.id for item in plan.already_labelled],
        "overAllowance": [item.order.id for item in plan.over_allowance],
        "remaining": plan.remaining,
        "total": str(plan.total),
    }


def preview(conn, merchant_id: str, selections: list[Selection]) -> dict:
    """What the confirm step shows: what will be bought and its total, what's already labelled, what's over."""
    _require_bulk_buying()
    return plan_json(_plan(conn, merchant_id, selections))


def enqueue(conn, merchant_id: str, selections: list[Selection]) -> dict:
    """Re-plan on the server, then queue only what will be bought. Returns the job id and that plan."""
    _require_bulk_buying()
    job_id, plan = _enqueue(conn, merchant_id, selections)
    return {"jobId": job_id, **plan_json(plan)}


def _enqueue(conn, merchant_id: str, selections: list[Selection]) -> tuple[int, BulkPlan]:
    plan = _plan(conn, merchant_id, selections, lock=True)
    (job_id,) = conn.execute(
        "INSERT INTO bulk_label_jobs (merchant_id) VALUES (%s) RETURNING id", (merchant_id,)
    ).fetchone()
    for position, item in enumerate(plan.to_buy):
        rate = item.rate
        conn.execute(
            "INSERT INTO bulk_label_job_items "
            "(job_id, position, order_id, carrier, service, rate_id, quoted_at, shown_price) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (job_id, position, item.order.id, rate.carrier, rate.service, rate.rate_id, rate.quoted_at,
             item.shown_price),
        )
    return job_id, plan


def claim_next_job(conn) -> tuple[int, str] | None:
    """Take the oldest queued job (or one a dead worker left running). Safe with more than one worker."""
    row = conn.execute(
        "UPDATE bulk_label_jobs SET status = 'running', started_at = now() WHERE id = ("
        "  SELECT id FROM bulk_label_jobs"
        "  WHERE status = 'queued' OR (status = 'running' AND started_at < now() - %s::interval)"
        "  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        ") RETURNING id, merchant_id",
        (STUCK_AFTER,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def pending_items(conn, job_id: int) -> list[tuple[int, Selection]]:
    rows = conn.execute(
        "SELECT position, order_id, carrier, service, rate_id, quoted_at, shown_price "
        "FROM bulk_label_job_items WHERE job_id = %s AND status = 'pending' ORDER BY position",
        (job_id,),
    ).fetchall()
    return [(row[0], Selection(*row[1:])) for row in rows]


def record_outcome(conn, job_id: int, position: int, merchant_id: str, outcome: Label | Exception) -> None:
    if isinstance(outcome, Label):
        (label_id,) = conn.execute(
            "INSERT INTO labels (order_id, carrier, tracking_number, price, pdf_url, idempotency_key) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key "
            "RETURNING id",
            (outcome.order_id, outcome.carrier, outcome.tracking_number, outcome.price, outcome.pdf_url,
             idempotency_key(str(job_id), outcome.order_id)),
        ).fetchone()
        status, error = "bought", None
    elif isinstance(outcome, StaleRateError):
        label_id, status, error = None, "needs_approval", None
    elif isinstance(outcome, AlreadyLabelled):
        label_id, status, error = None, "already_labelled", None
    else:
        label_id, status, error = None, "failed", str(outcome)
    conn.execute(
        "UPDATE bulk_label_job_items SET status = %s, error = %s, label_id = %s "
        "WHERE job_id = %s AND position = %s",
        (status, error, label_id, job_id, position),
    )


def order_has_live_label(conn, order_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM labels WHERE order_id = %s AND voided_at IS NULL LIMIT 1", (order_id,)
    ).fetchone() is not None


def finish_job(conn, job_id: int) -> None:
    conn.execute("UPDATE bulk_label_jobs SET status = 'done', finished_at = now() WHERE id = %s", (job_id,))


def run_job(
    transaction: Callable,
    job_id: int,
    merchant_id: str,
    *,
    load_order: Callable[[object, str], object],
    pace: Callable[[str], None],
) -> None:
    """Buy every pending item of one job, saving each outcome in its own transaction as it happens."""
    with transaction() as conn:
        pending = pending_items(conn, job_id)
        orders = {sel.order_id: load_order(conn, sel.order_id) for _, sel in pending}
    position_of = {sel.order_id: position for position, sel in pending}
    items = [
        BulkItem(orders[sel.order_id], Rate(sel.carrier, sel.service, sel.shown_price, sel.quoted_at, sel.rate_id),
                 sel.shown_price)
        for _, sel in pending
    ]

    def save(item: BulkItem, outcome: Label | Exception) -> None:
        with transaction() as conn:
            record_outcome(conn, job_id, position_of[item.order.id], merchant_id, outcome)

    def has_live_label(order) -> bool:
        with transaction() as conn:
            return order_has_live_label(conn, order.id)

    buy_all(items, job_id=str(job_id), pace=pace, has_live_label=has_live_label, on_result=save)
    with transaction() as conn:
        finish_job(conn, job_id)


def job_status(conn, merchant_id: str, job_id: int) -> dict:
    """Progress for the Orders page: counts by status, and which orders failed or need a new price approved."""
    row = conn.execute(
        "SELECT status FROM bulk_label_jobs WHERE id = %s AND merchant_id = %s", (job_id, merchant_id)
    ).fetchone()
    if row is None:
        raise LookupError(job_id)
    items = conn.execute(
        "SELECT order_id, status, error FROM bulk_label_job_items WHERE job_id = %s ORDER BY position", (job_id,)
    ).fetchall()
    counts = {"pending": 0, "bought": 0, "failed": 0, "needs_approval": 0, "already_labelled": 0}
    for _, status, _ in items:
        counts[status] += 1
    return {
        "status": row[0],
        "counts": counts,
        "failed": [{"orderId": order_id, "error": error} for order_id, status, error in items if status == "failed"],
        "needsApproval": [order_id for order_id, status, _ in items if status == "needs_approval"],
        "alreadyLabelled": [order_id for order_id, status, _ in items if status == "already_labelled"],
    }
