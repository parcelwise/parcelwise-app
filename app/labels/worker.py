"""The label-worker service: runs bulk label jobs from Postgres, one at a time (Raven decision ceed75dcbb69).

Run with `python -m app.labels.worker`. One instance keeps USPS purchases at or under 40 a minute in total.
"""

import time
from typing import Callable

from app.labels import bulk_jobs
from app.labels.bulk import carrier_pacer

POLL_SECONDS = 2.0


def run_once(transaction: Callable, *, load_order: Callable, pace: Callable[[str], None]) -> bool:
    """Claim and run one job. Returns False when there was nothing to do."""
    with transaction() as conn:
        claimed = bulk_jobs.claim_next_job(conn)
    if claimed is None:
        return False
    job_id, merchant_id = claimed
    bulk_jobs.run_job(transaction, job_id, merchant_id, load_order=load_order, pace=pace)
    return True


def run_forever(transaction: Callable, *, load_order: Callable, sleep: Callable[[float], None] = time.sleep):
    pace = carrier_pacer()
    while True:
        if not run_once(transaction, load_order=load_order, pace=pace):
            sleep(POLL_SECONDS)


def main():  # pragma: no cover - needs a database and an order loader
    # purchase_label() needs an order whose merchant carries its carrier accounts (carriers.get_carrier), and
    # nothing in this repo loads one yet: there is no carrier-account table in migrations/. Wire the same loader
    # the single-label route uses here before deploying the worker.
    raise SystemExit("label-worker: no order loader is wired yet; see app/labels/worker.py")


if __name__ == "__main__":
    main()
