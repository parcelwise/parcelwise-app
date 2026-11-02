"""The bulk-buy worker: one process that claims label batches from Postgres and buys them serially.

Run exactly one instance. It needs `load_order(order_id)` to return an Order whose merchant carries that
merchant's carrier accounts; that loader lives with the API's merchant code, so the entry point that wires it in
is deployed together with the worker service.
"""

import time

from app.labels.bulk_jobs import work_next_batch


def run_forever(store, load_order, *, idle_seconds: float = 5.0, sleep=time.sleep, should_stop=lambda: False):
    while not should_stop():
        if not work_next_batch(store, load_order):
            sleep(idle_seconds)
