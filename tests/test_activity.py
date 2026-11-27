"""Activity intervals: readings, trips and charges folded into one non-overlapping list."""
from datetime import UTC, datetime, timedelta

import pytest

from skoda_mate import activity, places, schema

DAY = "2027-03-01"


def _at(h, m=0):
    return f"{DAY}T{h:02d}:{m:02d}:00+00:00"


def _vid(conn):
    conn.execute("INSERT INTO vehicles(vin) VALUES('VIN')")
    vid = conn.execute("SELECT id FROM vehicles").fetchone()[0]
    conn.commit()
    return vid


def _snap(conn, vid, ts, *, soc=None, charging=0, in_motion=0, climate_state=None, aux_state=None,
          vent_state=None, lat=None, lon=None):
    conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,soc,charging,in_motion,climate_state,aux_state,"
                 "vent_state,lat,lon) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (vid, ts, soc, int(bool(charging)), int(bool(in_motion)), climate_state, aux_state, vent_state,
                  lat, lon))
    conn.commit()


def test_parked_readings_become_one_parked_interval():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    for ts in (_at(10), _at(10, 20), _at(11)):
        _snap(conn, vid, ts)
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert out == [{"kind": "parked", "start": _at(10), "end": _at(11), "minutes": 60,
                    "source": "reading", "trip_id": None, "charge_id": None, "place": None,
                    "estimated": True}]


def test_trip_wins_over_reading_segments():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,end_place) VALUES(?,?,?,?,?)",
                 (vid, "t1", _at(10, 5), _at(10, 35), "Work"))
    conn.commit()
    trip_id = conn.execute("SELECT id FROM trips").fetchone()[0]
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("parked", 5), ("drive", 30), ("parked", 25)]
    drive = out[1]
    assert (drive["start"], drive["end"], drive["source"]) == (_at(10, 5), _at(10, 35), "trip")
    assert (drive["trip_id"], drive["charge_id"], drive["place"], drive["estimated"]) == (trip_id, None, "Work", False)


def test_charge_interval_uses_charge_row():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150})
    for ts in (_at(10), _at(10, 20), _at(11)):
        _snap(conn, vid, ts, charging=1)
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,lat,lon) VALUES(?,?,?,?,?)",
                 (vid, _at(10), _at(12), 50.0, 8.0))
    conn.commit()
    charge_id = conn.execute("SELECT id FROM charges").fetchone()[0]
    out = activity.intervals(conn, vid, _at(10), _at(12))
    assert out == [{"kind": "charge", "start": _at(10), "end": _at(12), "minutes": 120,
                    "source": "charge", "trip_id": None, "charge_id": charge_id, "place": "Home",
                    "estimated": False}]


def test_climate_state_makes_a_climate_interval():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), climate_state="HEATING")
    _snap(conn, vid, _at(10, 40), climate_state="OFF")
    out = activity.intervals(conn, vid, _at(10), _at(10, 40))
    assert out == [{"kind": "climate", "start": _at(10), "end": _at(10, 40), "minutes": 40,
                    "source": "reading", "trip_id": None, "charge_id": None, "place": None,
                    "estimated": True}]


def test_heating_states_are_the_climate_states():
    assert activity.heating_states() == {"COOLING", "HEATING", "HEATING_AUXILIARY", "PREHEATING", "VENTILATION"}


@pytest.mark.parametrize("state", ["OFF", "IDLE", "UNKNOWN"])
def test_off_is_not_climate(state):
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), climate_state=state)
    _snap(conn, vid, _at(10, 30), climate_state=state)
    assert state not in activity.heating_states()
    out = activity.intervals(conn, vid, _at(10), _at(10, 30))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("parked", 30)]


def test_long_reading_gap_is_unknown():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    _snap(conn, vid, _at(18))
    out = activity.intervals(conn, vid, _at(10), _at(18))
    assert out == [{"kind": "unknown", "start": _at(10), "end": _at(18), "minutes": 480,
                    "source": "gap", "trip_id": None, "charge_id": None, "place": None,
                    "estimated": True}]


def test_trip_beats_overlapping_charge():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at) VALUES(?,?,?)",
                 (vid, _at(10), _at(12)))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _at(10, 30), _at(11)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(12))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("charge", 30), ("drive", 30), ("charge", 60)]
    assert [iv["source"] for iv in out] == ["charge", "trip", "charge"]


def test_range_clipping_and_merge():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(9, 40))
    _snap(conn, vid, _at(10, 15))
    _snap(conn, vid, _at(10, 45))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _at(9, 30), _at(10, 15)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in out] == [
        ("drive", _at(10), _at(10, 15), 15),
        ("parked", _at(10, 15), _at(11), 45),
    ]


def test_clipping_keeps_a_long_gap_unknown():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(3))
    _snap(conn, vid, _at(11))
    out = activity.intervals(conn, vid, _at(10), _at(12))
    assert [(iv["kind"], iv["source"], iv["start"], iv["end"], iv["minutes"]) for iv in out] == [
        ("unknown", "gap", _at(10), _at(11), 60),
        ("parked", "reading", _at(11), _at(12), 60),
    ]


def test_open_charge_ends_at_last_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), charging=1)
    _snap(conn, vid, _at(10, 30))
    conn.execute("INSERT INTO charges(vehicle_id,started_at) VALUES(?,?)", (vid, _at(10)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"], iv["source"], iv["estimated"]) for iv in out] == [
        ("charge", _at(10), _at(10, 30), 30, "charge", True),
        ("parked", _at(10, 30), _at(11), 30, "reading", True)]


def test_overlapping_charges_do_not_overlap():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    for started, ended in ((_at(10), _at(12)), (_at(11), _at(13))):
        conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at) VALUES(?,?,?)", (vid, started, ended))
    conn.commit()
    first, second = [row[0] for row in conn.execute("SELECT id FROM charges ORDER BY started_at")]
    out = activity.intervals(conn, vid, _at(10), _at(13))
    # The later-starting charge wins the overlap; the earlier keeps its uncovered part.
    assert out == [
        {"kind": "charge", "start": _at(10), "end": _at(11), "minutes": 60, "source": "charge",
         "trip_id": None, "charge_id": first, "place": None, "estimated": False},
        {"kind": "charge", "start": _at(11), "end": _at(13), "minutes": 120, "source": "charge",
         "trip_id": None, "charge_id": second, "place": None, "estimated": False},
    ]


def test_reversed_trip_does_not_split_base():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    _snap(conn, vid, _at(11))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _at(10, 30), _at(10, 15)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in out] == [
        ("parked", _at(10), _at(11), 60)]


def test_reversed_charge_does_not_split_base():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    _snap(conn, vid, _at(11))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at) VALUES(?,?,?)",
                 (vid, _at(10, 30), _at(10, 15)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in out] == [
        ("parked", _at(10), _at(11), 60)]


def test_motion_beats_charge_and_climate_in_one_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), charging=1, in_motion=1, climate_state="HEATING")
    _snap(conn, vid, _at(10, 30), charging=1, in_motion=1, climate_state="HEATING")
    out = activity.intervals(conn, vid, _at(10), _at(10, 30))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("drive", 30)]


def test_charge_beats_climate_in_one_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), charging=1, climate_state="HEATING")
    _snap(conn, vid, _at(10, 30), charging=1, climate_state="HEATING")
    out = activity.intervals(conn, vid, _at(10), _at(10, 30))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("charge", 30)]


def test_kinds_match_the_spec():
    assert activity.KINDS == ("drive", "charge", "climate", "aux", "vent", "parked", "unknown")


def test_aux_state_heating_is_aux():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), aux_state="PREHEATING")
    _snap(conn, vid, _at(10, 20), aux_state="PREHEATING")
    out = activity.intervals(conn, vid, _at(10), _at(10, 20))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"], iv["source"]) for iv in out] == [
        ("aux", _at(10), _at(10, 20), 20, "reading")]


def test_vent_state_heating_is_vent():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), vent_state="VENTILATION")
    _snap(conn, vid, _at(10, 20), vent_state="VENTILATION")
    out = activity.intervals(conn, vid, _at(10), _at(10, 20))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"], iv["source"]) for iv in out] == [
        ("vent", _at(10), _at(10, 20), 20, "reading")]


def test_climate_beats_aux_and_vent_in_one_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), climate_state="HEATING", aux_state="PREHEATING", vent_state="VENTILATION")
    _snap(conn, vid, _at(10, 20), climate_state="HEATING", aux_state="PREHEATING", vent_state="VENTILATION")
    out = activity.intervals(conn, vid, _at(10), _at(10, 20))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("climate", 20)]


def test_aux_beats_vent_in_one_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10), aux_state="PREHEATING", vent_state="VENTILATION")
    _snap(conn, vid, _at(10, 20), aux_state="PREHEATING", vent_state="VENTILATION")
    out = activity.intervals(conn, vid, _at(10), _at(10, 20))
    assert [(iv["kind"], iv["minutes"]) for iv in out] == [("aux", 20)]


def test_mixed_fixture_invariants():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(9))
    _snap(conn, vid, _at(9, 30), charging=1)
    _snap(conn, vid, _at(10), charging=1, in_motion=1, climate_state="HEATING")
    _snap(conn, vid, _at(10, 20), aux_state="PREHEATING")
    _snap(conn, vid, _at(11))
    _snap(conn, vid, _at(12, 30))
    for started, ended in ((_at(9, 20), _at(10, 10)), (_at(10, 50), _at(11, 20)), (_at(11), _at(11, 40))):
        conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at) VALUES(?,?,?)", (vid, started, ended))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _at(10, 30), _at(10, 50)))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t2", _at(12), _at(11, 50)))  # reversed: ignored
    conn.commit()
    out = activity.intervals(conn, vid, _at(9), _at(13))
    assert out == sorted(out, key=lambda iv: iv["start"])
    assert all(iv["start"] < iv["end"] for iv in out)
    assert all(iv["end"] <= nxt["start"] for iv, nxt in zip(out, out[1:], strict=False))
    assert (out[0]["start"], out[-1]["end"]) == (_at(9), _at(13))
    assert sum(iv["minutes"] for iv in out) == 240
    assert all(iv["minutes"] == round((datetime.fromisoformat(iv["end"])
                                       - datetime.fromisoformat(iv["start"])).total_seconds() / 60)
               for iv in out)


def test_open_trip_ends_at_last_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    _snap(conn, vid, _at(10, 30))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "t1", _at(10)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert out == [
        {"kind": "drive", "start": _at(10), "end": _at(10, 30), "minutes": 30, "source": "trip",
         "trip_id": 1, "charge_id": None, "place": None, "estimated": True},
        {"kind": "parked", "start": _at(10, 30), "end": _at(11), "minutes": 30, "source": "reading",
         "trip_id": None, "charge_id": None, "place": None, "estimated": True},
    ]


def test_open_rows_started_after_last_reading_are_dropped():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(10))
    _snap(conn, vid, _at(10, 30))
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "t1", _at(10, 45)))
    conn.execute("INSERT INTO charges(vehicle_id,started_at) VALUES(?,?)", (vid, _at(10, 50)))
    conn.commit()
    out = activity.intervals(conn, vid, _at(10), _at(11))
    assert out == [
        {"kind": "parked", "start": _at(10), "end": _at(11), "minutes": 60, "source": "reading",
         "trip_id": None, "charge_id": None, "place": None, "estimated": True},
    ]


def _stale_month(conn, vid, *, table):
    """An open trip or charge from 1 Nov 08:00 that nobody closed, then 26 days of hourly PARKED readings that are
    definitely not charging (a known charge state), with the charge level slowly dropping."""
    start = datetime(2026, 11, 1, tzinfo=UTC)
    if table == "trips":
        conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)",
                     (vid, "stale", (start + timedelta(hours=8)).isoformat()))
    else:
        conn.execute("INSERT INTO charges(vehicle_id,started_at) VALUES(?,?)", (vid, (start + timedelta(hours=8)).isoformat()))
    for h in range(26 * 24):
        conn.execute("INSERT INTO snapshots(vehicle_id,recorded_at,soc,charging,in_motion,charge_state) "
                     "VALUES(?,?,?,0,0,'READY_FOR_CHARGING')",
                     (vid, (start + timedelta(hours=h)).isoformat(), 80 - h // 24))
    conn.commit()
    return start + timedelta(days=26)


@pytest.mark.parametrize("table", ["trips", "charges"])
def test_a_stale_open_row_ends_at_its_first_definite_end_reading(table):
    """An open trip ends at the first PARKED reading after its start, an open charge at the first definitely
    not-charging one (the rules the quality repairs use), not at the newest reading of every later week."""
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    now = _stale_month(conn, vid, table=table)
    week = activity.timeline(conn, vid, "2026-11-20", "2026-11-26", 0, now, None)["summary"]
    assert week["drive_min"] == week["charge_min"] == 0
    assert week["parked_min"] == 7 * 24 * 60  # the last reading (26 Nov 23:00) is parked until the window ends
    loss = activity.parked_loss(conn, vid, (now - timedelta(days=7)).isoformat(), now.isoformat(), capacity_kwh=60.0)
    assert len(loss["sessions"]) >= 1
    first = activity.intervals(conn, vid, "2026-11-01T08:00:00+00:00", "2026-11-01T12:00:00+00:00")[0]
    kind = "drive" if table == "trips" else "charge"
    assert (first["kind"], first["end"], first["estimated"]) == (kind, "2026-11-01T09:00:00+00:00", True)


def test_a_live_open_drive_without_a_parked_reading_runs_to_the_last_reading():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _at(9, 40))  # parked before the drive
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "live", _at(10)))
    for m in (0, 5, 10, 15):
        _snap(conn, vid, _at(10, m), in_motion=1)
    _snap(conn, vid, _at(10, 20), in_motion=None)  # an unknown state never ends a drive
    out = activity.intervals(conn, vid, _at(9), _at(11))
    drive = [iv for iv in out if iv["kind"] == "drive"]
    assert [(iv["start"], iv["end"], iv["source"], iv["estimated"]) for iv in drive] == [
        (_at(10), _at(10, 20), "trip", True)]


# ---------------------------------------------------------------- timeline: local days

NOW_AFTER = datetime(2027, 3, 10, tzinfo=UTC)
ZERO = {"drive_min": 0, "charge_min": 0, "climate_min": 0, "parked_min": 0, "unknown_min": 0,
        "km": 0.0, "kwh": 0.0, "cost": None, "cost_partial": False}


def _ts(day, h, m=0):
    return f"{day}T{h:02d}:{m:02d}:00+00:00"


def test_timeline_lists_every_day_even_empty():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-07", now=NOW_AFTER)
    assert (out["from"], out["to"]) == ("2027-03-01", "2027-03-07")
    assert [d["date"] for d in out["days"]] == [f"2027-03-{d:02d}" for d in range(1, 8)]
    assert all(d["intervals"] == [] and d["summary"] == ZERO for d in out["days"])
    assert out["summary"] == ZERO


@pytest.mark.parametrize(("start", "end", "midnight", "tz"), [
    ("2027-03-01T23:00:00+00:00", "2027-03-02T01:00:00+00:00", "2027-03-02T00:00:00+00:00", 0),
    # tz_offset -60 is UTC+1: local midnight is 23:00 UTC, so a 22:00-00:00 trip spans two local days.
    ("2027-03-01T22:00:00+00:00", "2027-03-02T00:00:00+00:00", "2027-03-01T23:00:00+00:00", -60),
])
def test_timeline_splits_a_drive_at_local_midnight(start, end, midnight, tz):
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                 (vid, "t1", start, end, 40.0))
    conn.commit()
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-02", tz_offset=tz, now=NOW_AFTER)
    first, second = out["days"]
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in first["intervals"]] == [
        ("drive", start, midnight, 60)]
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in second["intervals"]] == [
        ("drive", midnight, end, 60)]
    assert (first["summary"]["drive_min"], second["summary"]["drive_min"]) == (60, 60)
    assert (first["summary"]["km"], second["summary"]["km"]) == (40.0, 0.0)


def test_timeline_buckets_sum_to_elapsed_minutes():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    _snap(conn, vid, _ts("2027-03-01", 10))
    _snap(conn, vid, _ts("2027-03-01", 11), charging=1)
    _snap(conn, vid, _ts("2027-03-01", 12), in_motion=1)
    _snap(conn, vid, _ts("2027-03-01", 13), climate_state="HEATING")
    _snap(conn, vid, _ts("2027-03-01", 14), aux_state="PREHEATING")
    _snap(conn, vid, _ts("2027-03-01", 15), vent_state="VENTILATION")
    _snap(conn, vid, _ts("2027-03-01", 16))
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-02", now=datetime(2027, 3, 3, tzinfo=UTC))
    s = out["summary"]
    # The 10 h before the first reading is a >6 h gap (unknown), as is the 32 h after the last one.
    assert (s["parked_min"], s["charge_min"], s["drive_min"], s["climate_min"], s["unknown_min"]) == (
        60, 60, 60, 180, 2520)
    assert sum(s[k] for k in ("drive_min", "charge_min", "climate_min", "parked_min", "unknown_min")) == 2 * 24 * 60
    for key in ("drive_min", "charge_min", "climate_min", "parked_min", "unknown_min", "km", "kwh"):
        assert s[key] == sum(d["summary"][key] for d in out["days"])
    assert (s["km"], s["kwh"], s["cost"], s["cost_partial"]) == (0.0, 0.0, None, False)
    # Bundling into climate_min must not relabel the pieces: each interval keeps its own kind.
    pieces = [(iv["kind"], iv["minutes"]) for d in out["days"] for iv in d["intervals"]
              if iv["kind"] in ("climate", "aux", "vent")]
    assert pieces == [("climate", 60), ("aux", 60), ("vent", 60)]


def test_timeline_km_kwh_and_cost():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150,
                         "price_kwh": 0.50})
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                 (vid, "t1", _ts("2027-03-01", 8), _ts("2027-03-01", 9), 40.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,charge_type,lat,lon) "
                 "VALUES(?,?,?,?,?,?,?)",
                 (vid, _ts("2027-03-01", 10), _ts("2027-03-01", 11), 10.0, "AC", 50.0, 8.0))
    conn.commit()
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-01", now=datetime(2027, 3, 2, tzinfo=UTC))
    day = out["days"][0]["summary"]
    assert (day["km"], day["kwh"], day["cost"], day["cost_partial"]) == (40.0, 10.0, 5.0, False)
    assert out["summary"] == day  # one day: the total is that day


def test_timeline_prices_charges_with_the_given_tariff():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,charge_type) VALUES(?,?,?,?,?)",
                 (vid, _ts("2027-03-01", 10), _ts("2027-03-01", 11), 10.0, "AC"))
    conn.commit()
    tariff = {"currency": "EUR", "home_kwh": 0.40, "public_ac_kwh": 0.55, "public_dc_kwh": 0.79,
              "home_lat": None, "home_lon": None, "home_radius_m": 150}
    day = activity.timeline(conn, vid, "2027-03-01", "2027-03-01", now=datetime(2027, 3, 2, tzinfo=UTC),
                            tariff=tariff)["days"][0]
    # No place and no home position: the unknown place falls back to the caller's home tariff (R2).
    assert (day["summary"]["cost"], day["summary"]["cost_partial"]) == (4.0, False)


def test_timeline_cost_is_partial_when_a_charge_has_no_amount():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    places.create(conn, {"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150,
                         "price_kwh": 0.50})
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,lat,lon) VALUES(?,?,?,?,?,?)",
                 (vid, _ts("2027-03-01", 10), _ts("2027-03-01", 11), 10.0, 50.0, 8.0))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh,lat,lon) VALUES(?,?,?,?,?,?)",
                 (vid, _ts("2027-03-01", 12), _ts("2027-03-01", 13), None, 50.0, 8.0))
    conn.commit()
    day = activity.timeline(conn, vid, "2027-03-01", "2027-03-01", now=datetime(2027, 3, 2, tzinfo=UTC))["days"][0]
    assert (day["summary"]["kwh"], day["summary"]["cost"], day["summary"]["cost_partial"]) == (10.0, 5.0, True)


def test_timeline_clips_the_window_end_at_now():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at) VALUES(?,?,?,?)",
                 (vid, "t1", _ts("2027-03-01", 10), _ts("2027-03-01", 12)))
    conn.commit()
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-01", now=datetime(2027, 3, 1, 11, tzinfo=UTC))
    assert [(iv["kind"], iv["start"], iv["end"], iv["minutes"]) for iv in out["days"][0]["intervals"]] == [
        ("drive", "2027-03-01T10:00:00+00:00", "2027-03-01T11:00:00+00:00", 60)]
    assert out["summary"]["drive_min"] == 60


def test_timeline_rejects_more_than_31_days():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    with pytest.raises(ValueError, match=r"The range is limited to 31 days\."):
        activity.timeline(conn, vid, "2027-01-01", "2027-02-01", now=NOW_AFTER)
    assert len(activity.timeline(conn, vid, "2027-01-01", "2027-01-31", now=NOW_AFTER)["days"]) == 31


def test_timeline_rejects_a_reversed_range():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    with pytest.raises(ValueError, match=r"The start must be before the end\."):
        activity.timeline(conn, vid, "2027-03-02", "2027-03-01", now=NOW_AFTER)


def test_timeline_buckets_still_sum_to_the_day_with_sub_minute_readings():
    """Every 20 s a different state: each piece alone rounds to 0 minutes, the day must still add up to 1440."""
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    base = datetime(2027, 3, 1, 10, tzinfo=UTC)
    for i in range(10):
        ts = (base + timedelta(seconds=20 * i)).isoformat()
        _snap(conn, vid, ts, charging=i % 2)
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-01", now=NOW_AFTER)
    s = out["days"][0]["summary"]
    assert sum(s[k] for k in ("drive_min", "charge_min", "climate_min", "parked_min", "unknown_min")) == 24 * 60
    assert s["charge_min"] + s["parked_min"] >= 1  # the three minutes of readings are not rounded away


def test_timeline_total_is_the_sum_of_the_rounded_days():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    for d in (1, 2, 3):
        conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                     (vid, f"t{d}", _ts(f"2027-03-0{d}", 10), _ts(f"2027-03-0{d}", 11), 0.04))
        conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,energy_kwh) VALUES(?,?,?,?)",
                     (vid, _ts(f"2027-03-0{d}", 12), _ts(f"2027-03-0{d}", 13), 0.004))
    conn.commit()
    out = activity.timeline(conn, vid, "2027-03-01", "2027-03-03", now=NOW_AFTER)
    for key in ("km", "kwh"):
        assert out["summary"][key] == round(sum(d["summary"][key] for d in out["days"]), 2 if key == "kwh" else 1)
    assert out["summary"]["km"] == 0.0 and out["summary"]["kwh"] == 0.0


def test_parked_loss_refuses_a_zero_or_negative_minimum_stay():
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    for bad in (0, -1):
        with pytest.raises(activity.RangeError, match="min_hours"):
            activity.parked_loss(conn, vid, "2027-03-01T00:00:00+00:00", "2027-03-02T00:00:00+00:00", bad)


def test_an_open_row_ends_at_the_last_reading_when_its_definite_end_lies_beyond_the_range():
    """The first definite end is looked up inside the range only; a later one must not stretch the row."""
    conn = schema.connect(":memory:")
    vid = _vid(conn)
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at) VALUES(?,?,?)", (vid, "open", _at(10)))
    for m in (0, 10, 20):
        _snap(conn, vid, _at(10, m), in_motion=1)
    _snap(conn, vid, _at(15), in_motion=0)  # parked, but after the range below
    drive = [iv for iv in activity.intervals(conn, vid, _at(9), _at(12)) if iv["source"] == "trip"]
    assert [(iv["start"], iv["end"]) for iv in drive] == [(_at(10), _at(10, 20))]
