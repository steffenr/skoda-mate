import threading

from skoda_mate import recorder, schema


def test_one_connection_survives_concurrent_threads():
    """Regression: the poller and FastAPI worker threads share one connection; plain sqlite3 raised
    'bad parameter or other API misuse' when they overlapped (seen as a 500 on /api/settings)."""
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq", None, 77.0)
    errors = []

    def reader():
        try:
            for _ in range(300):
                conn.execute("SELECT value FROM settings WHERE key=?", ("x",)).fetchone()
                list(conn.execute("SELECT * FROM snapshots WHERE vehicle_id=?", (vid,)))
                conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def writer():
        try:
            for i in range(150):
                recorder.ingest(conn, vid, {"ts": f"2027-01-01T{i // 60:02d}:{i % 60:02d}:00+00:00", "soc": 50, "charging": False,
                                            "mileage_km": 1000 + i, "in_motion": False})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(6)] + [threading.Thread(target=writer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] >= 150


def test_results_are_fully_fetched_and_support_the_row_api():
    conn = schema.connect(":memory:")
    conn.execute("INSERT INTO settings(key,value) VALUES('a','1'),('b','2')")
    cur = conn.execute("SELECT key, value FROM settings ORDER BY key")
    assert [d[0] for d in cur.description] == ["key", "value"]
    first = cur.fetchone()
    assert first["key"] == "a" and [r["key"] for r in cur.fetchall()] == ["b"] and cur.fetchone() is None
    assert [r["value"] for r in conn.execute("SELECT value FROM settings ORDER BY key")] == ["1", "2"]
    assert conn.execute("INSERT INTO settings(key,value) VALUES('c','3')").lastrowid
    assert conn.execute("SELECT 1 WHERE 0").fetchone() is None
