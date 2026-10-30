"""Bulk label purchases. The merchant confirms many orders at once; a worker buys them one at a time.

Each order still goes through purchase_label() with its own idempotency key (ADR 0004). USPS throttles us past
40 purchases a minute and has suspended an account for bursts, so a batch runs one purchase at a time, paced.
"""

import time
from dataclasses import dataclass
from decimal import Decimal

from app.billing.plans import remaining_allowance
from app.labels.purchase import StaleRateError, purchase_label
from app.labels.rates import Rate

PURCHASES_PER_MINUTE = 40


class AllowanceExceeded(Exception):
    """The batch would take the merchant past their plan's monthly labels. Nothing is bought."""

    def __init__(self, remaining: int):
        super().__init__(f"{remaining} labels left this month")
        self.remaining = remaining


@dataclass
class BatchItem:
    batch_id: int
    order_id: str
    rate: Rate
    shown_price: Decimal
    attempt: int = 1
    status: str = "queued"  # queued, bought, stale, failed
    sent_to_carrier: bool = False
    tracking_number: str = ""
    pdf_url: str = ""
    error: str = ""

    @property
    def idempotency_key(self) -> str:
        return f"batch{self.batch_id}:{self.order_id}:{self.attempt}"

    def requote(self, rate: Rate, shown_price: Decimal):
        """Queue again at a new price the merchant has seen.

        A new attempt only if the carrier never saw this one: if it did, the label may exist, and reusing the
        key lets the carrier return it instead of buying a second.
        """
        if not self.sent_to_carrier:
            self.attempt += 1
        self.rate, self.shown_price = rate, shown_price
        self.status, self.error = "queued", ""


def check_allowance(plan: str, used_this_month: int, count: int):
    """Block the whole batch up front rather than stop halfway (Priya Shah, 2026-10-30)."""
    remaining = remaining_allowance(plan, used_this_month)
    if remaining is not None and count > remaining:
        raise AllowanceExceeded(remaining)


class Pacer:
    """Spaces purchase starts so a batch never goes faster than PURCHASES_PER_MINUTE."""

    def __init__(self, per_minute: int = PURCHASES_PER_MINUTE, *, clock=time.monotonic, sleep=time.sleep):
        self.interval = 60 / per_minute
        self.clock, self.sleep = clock, sleep
        self.next_at = None

    def wait(self):
        now = self.clock()
        if self.next_at is not None and now < self.next_at:
            self.sleep(self.next_at - now)
            now = self.next_at
        self.next_at = now + self.interval


def run_items(items: list[BatchItem], load_order, *, pacer: Pacer, on_item=lambda item: None):
    """Buy the queued items in order, one at a time.

    At the first stale or changed price, stop: that item and every queued one after it become `stale`, so the
    merchant sees the new prices before anything else is bought (Priya Shah, 2026-10-30). Any other failure is
    recorded on its item and the batch goes on; the merchant can retry the failed ones.
    """
    for i, item in enumerate(items):
        if item.status != "queued":
            continue
        pacer.wait()
        try:
            label = purchase_label(
                load_order(item.order_id),
                item.rate,
                idempotency_key=item.idempotency_key,
                shown_price=item.shown_price,
            )
        except StaleRateError:
            for rest in items[i:]:
                if rest.status == "queued":
                    rest.status = "stale"
                    on_item(rest)
            return
        except Exception as error:  # noqa: BLE001 - any failure is the merchant's to retry; the key makes that safe
            item.status, item.error, item.sent_to_carrier = "failed", str(error), True
        else:
            item.status, item.sent_to_carrier = "bought", True
            item.tracking_number, item.pdf_url = label.tracking_number, label.pdf_url
        on_item(item)


# Storage. Handlers in app/api call these with a connection from app.core.db.transaction().

ITEM_COLUMNS = (
    "batch_id, order_id, carrier, service, rate_id, price, quoted_at, shown_price, attempt, status, "
    "sent_to_carrier, tracking_number, pdf_url, error"
)


def _item_from_row(row) -> BatchItem:
    batch_id, order_id, carrier, service, rate_id, price, quoted_at, shown_price, attempt, status = row[:10]
    sent, tracking, pdf, err = row[10:]
    return BatchItem(
        batch_id,
        order_id,
        Rate(carrier, service, Decimal(price), quoted_at, rate_id),
        Decimal(shown_price),
        attempt,
        status,
        sent,
        tracking or "",
        pdf or "",
        err or "",
    )


def load_items(conn, batch_id: int) -> list[BatchItem]:
    rows = conn.execute(
        f"SELECT {ITEM_COLUMNS} FROM label_batch_items WHERE batch_id = %s ORDER BY position", (batch_id,)
    ).fetchall()
    return [_item_from_row(row) for row in rows]


def save_item(conn, item: BatchItem):
    conn.execute(
        "UPDATE label_batch_items SET carrier = %s, service = %s, rate_id = %s, price = %s, quoted_at = %s, "
        "shown_price = %s, attempt = %s, status = %s, sent_to_carrier = %s, tracking_number = %s, pdf_url = %s, "
        "error = %s "
        "WHERE batch_id = %s AND order_id = %s",
        (
            item.rate.carrier,
            item.rate.service,
            item.rate.rate_id,
            item.rate.price,
            item.rate.quoted_at,
            item.shown_price,
            item.attempt,
            item.status,
            item.sent_to_carrier,
            item.tracking_number or None,
            item.pdf_url or None,
            item.error or None,
            item.batch_id,
            item.order_id,
        ),
    )


@dataclass(frozen=True)
class Quoted:
    """One order as the merchant confirmed it.

    `rate` is our own quote looked up by the rate id the dashboard sent, never built from the request body, so
    its price and age are ours. `shown_price` is the price the merchant saw.
    """

    order_id: str
    rate: Rate
    shown_price: Decimal


def create_batch(conn, merchant, quoted: list[Quoted]) -> int:
    """Queue a batch for the worker, bought in the order given. Raises AllowanceExceeded or LookupError first."""
    check_allowance(merchant.plan, merchant.labels_this_month, len(quoted))
    order_ids = [q.order_id for q in quoted]
    found = conn.execute(
        "SELECT id FROM orders WHERE merchant_id = %s AND status = 'unfulfilled' AND id = ANY(%s)",
        (merchant.id, order_ids),
    ).fetchall()
    missing = set(order_ids) - {row[0] for row in found}
    if missing:
        raise LookupError(f"not unfulfilled orders of this merchant: {sorted(missing)}")
    (batch_id,) = conn.execute(
        "INSERT INTO label_batches (merchant_id) VALUES (%s) RETURNING id", (merchant.id,)
    ).fetchone()
    for position, q in enumerate(quoted):
        conn.execute(
            "INSERT INTO label_batch_items "
            "(batch_id, position, order_id, carrier, service, rate_id, price, quoted_at, shown_price) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                batch_id,
                position,
                q.order_id,
                q.rate.carrier,
                q.rate.service,
                q.rate.rate_id,
                q.rate.price,
                q.rate.quoted_at,
                q.shown_price,
            ),
        )
    return batch_id


def batch_status(conn, merchant_id: str, batch_id: int) -> dict:
    row = conn.execute(
        "SELECT status FROM label_batches WHERE id = %s AND merchant_id = %s", (batch_id, merchant_id)
    ).fetchone()
    if row is None:
        raise LookupError(batch_id)
    return {"id": batch_id, "status": row[0], "items": load_items(conn, batch_id)}


def retry_batch(conn, merchant, batch_id: int, requoted: list[Quoted]) -> int:
    """Queue the failed items again, and the stale ones at the new prices the merchant just confirmed."""
    batch = batch_status(conn, merchant.id, batch_id)
    if batch["status"] != "done":
        raise ValueError(f"batch {batch_id} is still {batch['status']}")
    new_quotes = {q.order_id: q for q in requoted}
    queued = []
    for item in batch["items"]:
        if item.order_id in new_quotes:
            item.requote(new_quotes[item.order_id].rate, new_quotes[item.order_id].shown_price)
        elif item.status == "failed":
            item.status, item.error = "queued", ""
        else:
            continue
        queued.append(item)
    check_allowance(merchant.plan, merchant.labels_this_month, len(queued))
    for item in queued:
        save_item(conn, item)
    conn.execute("UPDATE label_batches SET status = 'queued' WHERE id = %s", (batch_id,))
    return len(queued)
