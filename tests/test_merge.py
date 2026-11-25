
import pytest

from skoda_mate import importer, merge, recorder, schema

from .fixtures import VIN
from .test_importer import A, csv, f
from .test_web import connected

B = A.replace("01.07.2026 08:00", "01.07.2026 08:50").replace("01.07.2026 08:30", "01.07.2026 09:20").replace('"1000","1030"', '"1030","1060"')


def setup():
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, VIN, "Enyaq", None, 77.0)
    return conn, vid


def add(conn, vid, start, end, km, kwh, s0, s1, note=None, odo=(None, None)):
    return conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,energy_kwh,start_soc,end_soc,note,odo_start,odo_end,"
                        "start_place,end_place) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (vid, f"c-{start}", start, end, km, kwh, s0, s1, note, *odo, f"from {start[11:16]}", f"to {end[11:16]}")).lastrowid


def test_merge_sums_keeps_first_id_and_can_be_undone():
    conn, vid = setup()
    a = add(conn, vid, "2026-07-01T08:00:00+00:00", "2026-07-01T08:30:00+00:00", 20, 4.0, 80, 74, "first", (1000, 1020))
    b = add(conn, vid, "2026-07-01T08:45:00+00:00", "2026-07-01T09:15:00+00:00", 10, 2.0, 74, 71, "second", (1020, 1030))
    keep = merge.merge(conn, vid, [b, a])
    assert keep == a and conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    t = dict(conn.execute("SELECT * FROM trips").fetchone())
    assert (t["distance_km"], t["energy_kwh"], t["start_soc"], t["end_soc"], t["odo_start"], t["odo_end"]) == (30, 6.0, 80, 71, 1000, 1030)
    assert t["started_at"].startswith("2026-07-01T08:00") and t["ended_at"].startswith("2026-07-01T09:15") and t["duration_min"] == 75
    assert t["avg_kwh_100km"] == 20.0 and t["end_place"] == "to 09:15" and t["note"] == "first · second"
    ids = merge.unmerge(conn, vid, a)
    rows = [dict(r) for r in conn.execute("SELECT * FROM trips ORDER BY started_at")]
    assert len(rows) == 2 and ids[0] == a and rows[0]["distance_km"] == 20 and rows[1]["distance_km"] == 10 and rows[1]["note"] == "second"
    assert rows[0]["merged_json"] is None and rows[0]["ended_at"].startswith("2026-07-01T08:30")


def test_merge_refuses_unsafe_requests():
    conn, vid = setup()
    a = add(conn, vid, "2026-07-01T08:00:00+00:00", "2026-07-01T08:30:00+00:00", 20, 4, 80, 74)
    far = add(conn, vid, "2026-07-01T20:00:00+00:00", "2026-07-01T20:30:00+00:00", 10, 2, 74, 71)
    over = add(conn, vid, "2026-07-01T08:20:00+00:00", "2026-07-01T08:50:00+00:00", 5, 1, 74, 72)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "open", "2026-07-01T08:55:00+00:00"))
    open_ = conn.execute("SELECT id FROM trips WHERE cloud_id='open'").fetchone()[0]
    for ids, msg in (([a], "between 2"), ([a, far], "apart"), ([a, over], "overlap"), ([a, open_], "still running"), ([a, 9999], "does not exist")):
        with pytest.raises(merge.MergeError, match=msg):
            merge.merge(conn, vid, ids)
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 4  # nothing was changed by the failed attempts
    with pytest.raises(merge.MergeError):
        merge.unmerge(conn, vid, a)


def test_reimporting_the_csv_does_not_bring_merged_parts_back():
    """The duplicate guarantee must survive a merge."""
    conn, vid = setup()
    importer.run(conn, vid, VIN, [f("t.csv", csv(A, B))], "Europe/Berlin", False)
    first, second = [r[0] for r in conn.execute("SELECT id FROM trips ORDER BY started_at")]
    merge.merge(conn, vid, [first, second])
    r = importer.run(conn, vid, VIN, [f("t.csv", csv(A, B))], "Europe/Berlin", False)
    assert r["new"] == 0 and conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    merge.unmerge(conn, vid, first)  # and after an undo the parts are real again, still without duplicates
    assert importer.run(conn, vid, VIN, [f("t.csv", csv(A, B))], "Europe/Berlin", False)["new"] == 0
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 2


def test_api_merge_and_unmerge():
    c, conn, api, vid = connected()
    a = add(conn, vid, "2027-01-01T08:00:00+00:00", "2027-01-01T08:30:00+00:00", 20, 4, 80, 74)
    b = add(conn, vid, "2027-01-01T08:40:00+00:00", "2027-01-01T09:00:00+00:00", 10, 2, 74, 71)
    conn.commit()
    r = c.post(f"/api/vehicles/{vid}/trips/merge", json={"ids": [a, b]})
    assert r.status_code == 200 and r.json()["id"] == a
    t = c.get(f"/api/vehicles/{vid}/trips/{a}").json()
    assert t["merged_parts"] == 2 and t["distance_km"] == 30 and "merged_json" not in t
    assert c.post(f"/api/vehicles/{vid}/trips/merge", json={"ids": [a]}).status_code == 400
    assert len(c.post(f"/api/vehicles/{vid}/trips/{a}/unmerge").json()["ids"]) == 2
    assert c.post(f"/api/vehicles/{vid}/trips/{a}/unmerge").status_code == 400
