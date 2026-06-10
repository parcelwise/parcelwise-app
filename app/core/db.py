"""Thin wrapper over the Postgres pool. Handlers never open connections themselves."""

from contextlib import contextmanager

_pool = None


def init_pool(factory):
    global _pool
    _pool = factory()


@contextmanager
def transaction():
    conn = _pool.getconn()
    try:
        with conn:
            yield conn
    finally:
        _pool.putconn(conn)


STATEMENT_TIMEOUT_MS = 5_000


def set_statement_timeout(conn, ms: int = STATEMENT_TIMEOUT_MS):
    conn.execute(f"SET LOCAL statement_timeout = {int(ms)}")
