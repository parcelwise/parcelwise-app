from app.labels.live import orders_with_live_labels


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return self.rows


def test_returns_orders_with_live_labels():
    conn = FakeConn([("o1",), ("o3",)])
    assert orders_with_live_labels(conn, ["o1", "o2", "o3"]) == {"o1", "o3"}
    sql, params = conn.calls[0]
    assert "voided_at IS NULL" in sql
    assert params == (["o1", "o2", "o3"],)


def test_empty_selection_skips_the_query():
    conn = FakeConn([])
    assert orders_with_live_labels(conn, []) == set()
    assert conn.calls == []
