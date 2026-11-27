"""The events one reading produces (what MQTT and webhooks are told), and how the poller hands them on."""
import asyncio

from skoda_mate import automation, places, recorder, schema, store
from skoda_mate.client import ApiError
from skoda_mate.poller import Poller

from .helpers import FakeApi

VIN = "TMBJB9NY5RF999999"
HOME = (50.11, 8.68)
WORK = (50.20, 8.60)


def make(kwh=77.0):
    conn = schema.connect(":memory:")
    return conn, recorder.upsert_vehicle(conn, VIN, "Enyaq", None, kwh)


def t(h, m=0, day=1):
    return f"2026-01-{day:02d}T{h:02d}:{m:02d}:00+00:00"


def snap(ts, soc=None, **kw):
    return {"ts": ts, "soc": soc, "charging": False, **kw}


def charging(ts, soc, power=10.0, **kw):
    return snap(ts, soc, charging=True, charge_state="CHARGING", charge_power_kw=power, charge_type="AC", **kw)


def parked(ts, soc, km, at=HOME, **kw):
    return snap(ts, soc, in_motion=False, mileage_km=km, lat=at[0], lon=at[1], address="Some street 1", **kw)


def names(events):
    return [e["event"] for e in events]


def only(events, name):
    found = [e for e in events if e["event"] == name]
    assert len(found) == 1, names(events)
    return found[0]


def feed(conn, vid, *snaps):
    return [recorder.ingest(conn, vid, s) for s in snaps]


def add_place(conn, name, at, kind="place"):
    return places.create(conn, {"name": name, "kind": kind, "lat": at[0], "lon": at[1], "radius_m": 150})


# ------------------------------------------------------------------ charges

def test_a_watched_charge_is_reported_when_it_starts_and_ends():
    conn, vid = make()
    add_place(conn, "Home", HOME, "home")
    _, started, _, ended = feed(
        conn, vid, parked(t(9, 50), 18, 100, charge_state="CONNECT_CABLE"),
        charging(t(10), 20, lat=HOME[0], lon=HOME[1], target_soc=80),
        charging(t(11), 40, lat=HOME[0], lon=HOME[1], target_soc=80),
        parked(t(11, 30), 45, 100, charge_state="READY_FOR_CHARGING", target_soc=80))
    assert only(started, "charge.started")["data"]["place"] == "Home"
    e = only(ended, "charge.ended")
    cid = conn.execute("SELECT id FROM charges").fetchone()[0]
    assert e["at"] == t(11, 30)
    assert e["data"]["charge_id"] == cid and e["data"]["place"] == "Home" and e["data"]["energy_kwh"] == 12.5
    assert e["data"]["cost"] is not None and e["data"]["start_soc"] == 18 and e["data"]["end_soc"] == 45
    assert "charge.completed" not in names(ended)  # stopped at 45 %, the target was 80 %


def test_charge_completed_only_when_the_target_was_reached():
    conn, vid = make()
    events = feed(conn, vid, charging(t(10), 60, target_soc=80), charging(t(11), 79, target_soc=80),
                  snap(t(11, 20), 80, charge_state="READY_FOR_CHARGING", target_soc=80))[-1]
    assert {"charge.ended", "charge.completed"} <= set(names(events))


def test_a_charge_nobody_watched_sends_nothing():
    conn, vid = make()
    events = feed(conn, vid, parked(t(10), 20, 100), parked(t(14), 70, 100))
    assert conn.execute("SELECT source FROM charges").fetchone()[0] == "inferred"
    assert [n for e in events for n in names(e) if n.startswith("charge")] == []


def test_the_first_reading_and_unknown_values_send_nothing():
    conn, vid = make()
    first, gone, back = feed(
        conn, vid,
        parked(t(10), 15, 100, plug_connected=True, doors_open=True, windows_open=True, climate_state="HEATING"),
        snap(t(10, 5)),  # every field missing from this poll
        parked(t(10, 10), 15, 100, plug_connected=True, doors_open=True, windows_open=True, climate_state="HEATING"))
    assert first == [] and gone == [] and back == []


# ------------------------------------------------------------------ car state

def test_plug_doors_windows_and_climate_changes():
    conn, vid = make()
    closed = {"plug_connected": False, "doors_open": False, "windows_open": False, "climate_state": "OFF"}
    _, on, off = feed(
        conn, vid, parked(t(10), 50, 100, **closed),
        parked(t(10, 5), 50, 100, plug_connected=True, doors_open=True, windows_open=True, climate_state="HEATING"),
        parked(t(10, 10), 50, 100, **closed))
    assert sorted(names(on)) == ["climate.started", "doors.opened", "plug.connected", "windows.opened"]
    assert only(on, "climate.started")["data"] == {"state": "HEATING"}
    assert sorted(names(off)) == ["climate.ended", "plug.disconnected"]


def test_a_change_between_two_heating_states_is_not_a_new_start():
    conn, vid = make()
    events = feed(conn, vid, parked(t(10), 50, 100, climate_state="HEATING"),
                  parked(t(10, 5), 50, 100, climate_state="VENTILATION"))[-1]
    assert events == []


def test_soc_low_fires_once_per_crossing():
    conn, vid = make()
    out = feed(conn, vid, *[parked(t(10, m), soc, 100) for m, soc in enumerate([21, 19, 18, 20, 19])])
    assert [names(e).count("soc.low") for e in out] == [0, 1, 0, 0, 1]
    assert only(out[1], "soc.low")["data"] == {"soc": 19, "threshold": 20}


def test_soc_low_uses_the_stored_threshold():
    conn, vid = make()
    store.set_setting(conn, automation.SOC_LOW_KEY, "30")
    out = feed(conn, vid, parked(t(10), 31, 100), parked(t(10, 5), 29, 100))
    assert only(out[1], "soc.low")["data"]["threshold"] == 30


# ------------------------------------------------------------------ trips and places

def drive(conn, vid, hour, frm, to, km):
    """A watched drive from `frm` to `to`; returns the events of the start and of the end."""
    started = recorder.ingest(conn, vid, snap(t(hour, 10), 60, in_motion=True, mileage_km=km))
    ended = recorder.ingest(conn, vid, parked(t(hour, 40), 55, km + 20, at=to))
    return started, ended


def test_trip_events_name_places_not_addresses():
    conn, vid = make()
    add_place(conn, "Home", HOME, "home")
    recorder.ingest(conn, vid, parked(t(8), 60, 1000, at=HOME))
    started, ended = drive(conn, vid, 8, HOME, WORK, 1000)
    assert only(started, "trip.started")["data"]["start_place"] == "Home"
    data = only(ended, "trip.ended")["data"]
    assert data["trip_id"] == conn.execute("SELECT id FROM trips").fetchone()[0]
    assert data["distance_km"] == 20 and data["start_place"] == "Home" and data["end_place"] is None
    assert data["approx"] is False
    assert "Some street 1" not in str(started + ended) and str(HOME[0]) not in str(started + ended)


def test_leaving_and_entering_places_follows_consecutive_trip_ends():
    conn, vid = make()
    add_place(conn, "Home", HOME, "home")
    add_place(conn, "Work", WORK, "work")
    recorder.ingest(conn, vid, parked(t(7), 60, 1000, at=HOME))
    _, first = drive(conn, vid, 8, HOME, WORK, 1000)
    assert only(first, "geofence.left")["data"]["place"] == "Home"
    assert only(first, "geofence.entered")["data"]["place"] == "Work"
    _, again = drive(conn, vid, 12, WORK, WORK, 1020)  # an errand that ends where it began
    assert not [n for n in names(again) if n.startswith("geofence")]
    _, away = drive(conn, vid, 17, WORK, (51.0, 9.0), 1040)
    assert only(away, "geofence.left")["data"]["place"] == "Work" and "geofence.entered" not in names(away)


def test_commands_and_quality_entries_are_not_automation_events():
    conn, vid = make()
    recorder.ingest(conn, vid, parked(t(10), 50, 100))
    before = conn.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
    for kind in ("command", "quality_fix", "quality_review", "odometer_jump", "locked"):
        conn.execute("INSERT INTO events(vehicle_id,at,kind,detail) VALUES(?,?,?,?)", (vid, t(10), kind, "x"))
    last = recorder.last_snapshot(conn, vid)
    assert automation.collect(conn, vid, before, last, {"ts": t(10), "soc": 50}, last["id"]) == []


def test_envelope_names_the_car_and_has_a_unique_id():
    conn, vid = make()
    event = {"event": "plug.connected", "at": t(10), "data": {}}
    a, b = automation.envelope(conn, vid, event), automation.envelope(conn, vid, event)
    assert a["vehicle"] == {"id": vid, "name": "Enyaq", "vin": VIN}
    assert (a["event"], a["at"], a["data"]) == ("plug.connected", t(10), {})
    assert a["id"] != b["id"]


# ------------------------------------------------------------------ the poller

def poller(responses, sink):
    conn = schema.connect(":memory:")
    api = FakeApi(responses)
    p = Poller(conn, api, clock=api.clock)
    p.on_events = sink
    p.add_vehicle(VIN, recorder.upsert_vehicle(conn, VIN))
    return p


def run_polls(p, n):
    async def go():
        for _ in range(n):
            await p.poll(VIN)
    asyncio.run(go())


def test_poll_failed_fires_at_the_third_failure_in_a_row_and_again_only_after_a_success():
    from .fixtures import BEV
    err = ApiError(503, "service-unavailable", "down")
    got = []
    p = poller([err, err, err, err, BEV, err, err, err], lambda vid, events: got.extend(events))
    run_polls(p, 4)
    failed = [e for e in got if e["event"] == "poll.failed"]
    assert len(failed) == 1 and failed[0]["data"]["failures"] == 3 and failed[0]["data"]["kind"] == "service-unavailable"
    assert failed[0]["data"]["error"]
    run_polls(p, 4)
    assert len([e for e in got if e["event"] == "poll.failed"]) == 2


def test_a_failing_consumer_never_fails_the_poll():
    from .fixtures import BEV
    def boom(vid, events):
        raise RuntimeError("consumer broke")
    err = ApiError(503, "service-unavailable", "down")
    p = poller([err, err, err, BEV], boom)
    run_polls(p, 4)
    assert p.rt[VIN].polls == 1 and p.rt[VIN].last_error is None
