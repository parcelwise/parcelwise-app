from app.orders.queries import SELECT_ALL_LIMIT, unfulfilled_order_ids


class Conn:
    def __init__(self, ids, total):
        self.ids, self.total, self.limits = ids, total, []

    def execute(self, sql, params):
        if "count(*)" in sql:
            self._rows = [(self.total,)]
        else:
            self.limits.append(params[1])
            self._rows = [(i,) for i in self.ids[: params[1]]]
        return self

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


def test_select_all_matching_stops_at_200_even_if_asked_for_more():
    conn = Conn([f"o{i}" for i in range(500)], 500)
    result = unfulfilled_order_ids(conn, "m1", limit=500)
    assert SELECT_ALL_LIMIT == 200
    assert conn.limits == [200]
    assert len(result["ids"]) == 200 and result["total"] == 500 and result["limit"] == 200
