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
