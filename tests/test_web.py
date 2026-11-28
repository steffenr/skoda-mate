import csv
import io
import json
import sqlite3

import pytest

from skoda_mate import recorder, store
from skoda_mate.routers.settings import SettingsBody, put_settings

from .fixtures import VIN, bev
from .helpers import FakeApi, client_for, make_app, sign_up

KEY = "sk-live-0123456789abcdef"


def connected(api=None, charging=False, **kw):
    """An app with a working connection (one poll done) and a signed-in client.

    By default the car is plugged in but NOT charging, so the connection poll does not open a charge session
    that would mix with the sessions a test seeds itself."""
    holder = {}
    default = bev() if charging else bev(**{"charging.status.state": "READY_FOR_CHARGING"})

    def factory(key):
        holder["api"] = api or FakeApi([default])
        return holder["api"]

    app, conn = make_app(api_factory=factory, **kw)
    c = client_for(app)
    c.__enter__()
    sign_up(c)
    r = c.post("/api/setup/skoda", json={"api_key": KEY, "vins": VIN, "spin": "1234"})
    assert r.status_code == 200, r.text
    vid = c.get("/api/vehicles").json()[0]["id"]
    return c, conn, holder["api"], vid


def seed_trip(conn, vid, day="2027-02-10"):
    def s(h, m, **k):
        return {"ts": f"{day}T{h:02d}:{m:02d}:00+00:00", "charging": False, **k}
    recorder.upsert_vehicle(conn, VIN, battery_kwh=77.0)
    recorder.ingest(conn, vid, s(8, 0, soc=90, in_motion=False, mileage_km=2000, lat=50.0, lon=8.0, address="Home"))
    recorder.ingest(conn, vid, s(8, 10, soc=88, in_motion=True, mileage_km=2005))
    recorder.ingest(conn, vid, s(8, 40, soc=78, in_motion=False, mileage_km=2040, lat=50.4, lon=8.4, address="Work"))


def seed_charge(conn, vid, day="2027-02-11", start=20, end=80, kw=10.0, kind="AC", lat=50.0, lon=8.0):
    """A 3 h charge polled every 30 min (realistic spacing: power integration is capped at 1 h per gap)."""
    steps = 6
    for i in range(steps + 1):
        minutes = i * 30
        recorder.ingest(conn, vid, {"ts": f"{day}T{10 + minutes // 60:02d}:{minutes % 60:02d}:00+00:00",
                                    "soc": start + (end - start) * i / steps, "charging": True, "charge_state": "CHARGING",
                                    "charge_power_kw": kw, "charge_type": kind, "lat": lat, "lon": lon})
    recorder.ingest(conn, vid, {"ts": f"{day}T13:00:00+00:00", "soc": end, "charging": False, "charge_state": "READY_FOR_CHARGING"})


def test_overview_has_everything_the_dashboard_needs():
    c, conn, api, vid = connected(charging=True)
    o = c.get(f"/api/vehicles/{vid}/overview").json()
    assert o["vehicle"]["vin"] == VIN and o["snapshot"]["soc"] == 55 and o["sections"]["info"]["name"] == "My Enyaq"
    assert o["sections"]["charging"]["power_kw"] == 10.8 and o["sections"]["position"]["address"].startswith("Main")
    assert "raw" not in o["sections"] and "operations" not in o["sections"]  # internals stay out of the payload
    assert o["features"]["charge_control"]["available"] is True and o["features"]["aux_heating"]["available"] is False
    assert o["parts"]["charging"]["available"] and o["parts"]["fuelStatus"]["reason"] == "Not supported by this car"
    assert o["poller"]["budget"]["used"] == 1 and o["poller"]["key_expires_at"] == "2027-06-01T00:00:00Z"
    cat = {x["name"]: x for x in o["commands"]}
    assert cat["start_charging"]["supported"] is True and cat["start_aux_heating"]["supported"] is False
    assert "lock" not in cat and any(u["key"] == "lock" for u in o["unavailable"])  # honest about what Škoda does not offer
    assert o["needs_capacity"] is True and o["tariff"]["currency"] == "EUR"


def test_refresh_costs_one_request_and_reports_the_budget():
    c, conn, api, vid = connected()
    before = len(api.calls)
    r = c.post(f"/api/vehicles/{vid}/refresh").json()
    assert r["ok"] and len(api.calls) == before + 1 and r["poller"]["budget"]["used"] == 2


def test_trips_listing_filters_costs_and_detail():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_trip(conn, vid, day="2027-03-05")
    r = c.get(f"/api/vehicles/{vid}/trips").json()
    assert r["total"] == 2 and r["items"][0]["started_at"].startswith("2027-03-05")  # newest first
    t = r["items"][0]
    assert t["distance_km"] == 40 and t["start_place"] == "Home" and t["end_place"] == "Work" and t["approx"] == 0
    assert t["cost"] == round(t["energy_kwh"] * 0.30, 2) and "route_json" not in t
    assert c.get(f"/api/vehicles/{vid}/trips?from=2027-03-01").json()["total"] == 1
    assert c.get(f"/api/vehicles/{vid}/trips?q=work").json()["total"] == 2 and c.get(f"/api/vehicles/{vid}/trips?q=zzz").json()["total"] == 0
    assert c.get(f"/api/vehicles/{vid}/trips?min_km=100").json()["total"] == 0
    d = c.get(f"/api/vehicles/{vid}/trips/{t['id']}").json()
    assert [p["place"] for p in d["route"]] == ["Home", "Work"]
    assert c.put(f"/api/trips/{t['id']}/note", json={"note": "client visit"}).status_code == 200
    assert c.get(f"/api/vehicles/{vid}/trips/{t['id']}").json()["note"] == "client visit"
    assert c.get(f"/api/vehicles/{vid}/trips/9999").status_code == 404


def test_charges_costs_home_vs_public_and_manual_override():
    c, conn, api, vid = connected()
    seed_charge(conn, vid)
    seed_charge(conn, vid, day="2027-02-12", kind="DC", kw=50.0, lat=51.0, lon=9.0)
    items = c.get(f"/api/vehicles/{vid}/charges").json()["items"]
    dc, ac = items[0], items[1]
    assert dc["charge_type"] == "DC" and dc["place_kind_resolved"] == "public" and dc["cost_basis"] == "tariff"
    assert dc["cost"] == round(dc["energy_kwh"] * 0.79, 2)
    assert ac["place_kind_resolved"] == "unknown" and ac["cost_basis"] == "tariff-guess"  # no home position yet
    r = c.post(f"/api/vehicles/{vid}/home-here")
    assert r.status_code == 200 and r.json()["home_lat"] == 50.11  # the parked position from the connection test
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_kwh": 0.20}})
    ac = [x for x in c.get(f"/api/vehicles/{vid}/charges").json()["items"] if x["charge_type"] == "AC"][0]
    assert ac["place_kind_resolved"] == "home" and ac["cost"] == round(ac["energy_kwh"] * 0.20, 2)
    p = c.patch(f"/api/vehicles/{vid}/charges/{ac['id']}", json={"cost_manual": 4.5, "note": "garage"}).json()
    assert p["cost"] == 4.5 and p["cost_basis"] == "manual" and p["note"] == "garage"
    assert c.patch(f"/api/vehicles/{vid}/charges/{ac['id']}", json={"place_kind": "public"}).json()["place_kind_resolved"] == "public"
    assert c.patch(f"/api/vehicles/{vid}/charges/{ac['id']}", json={"clear_cost": True, "place_kind": ""}).json()["cost_basis"] == "tariff"
    assert c.patch(f"/api/vehicles/{vid}/charges/{ac['id']}", json={"place_kind": "moon"}).status_code == 400
    assert c.get(f"/api/vehicles/{vid}/charges?kind=DC").json()["total"] == 1
    cur = c.get(f"/api/vehicles/{vid}/charges/{ac['id']}").json()["curve"]
    assert [p["soc"] for p in cur][:2] == [20, 30] and cur[0]["p"] == 10.0  # the charging curve from the polls
    assert c.get(f"/api/vehicles/{vid}/charges/{ac['id']}").json()["curve_gaps"] == []  # polled every 30 min: no holes


def test_charge_curve_names_the_stretches_without_readings():
    """Issue #8: the chart must leave holes in the readings open, including the time up to an estimated end."""
    c, conn, api, vid = connected()
    recorder.upsert_vehicle(conn, VIN, battery_kwh=77.0)
    for ts, soc in (("19:49", 46), ("21:26", 68), ("21:30", 69)):
        recorder.ingest(conn, vid, {"ts": f"2027-02-11T{ts}:00+00:00", "soc": soc, "charging": True, "charge_state": "CHARGING",
                                    "charge_power_kw": 10.5, "remaining_min": 50})
    recorder.ingest(conn, vid, {"ts": "2027-02-12T05:27:00+00:00", "soc": 80, "charging": False, "charge_state": "READY_FOR_CHARGING"})
    cid = conn.execute("SELECT id FROM charges WHERE source='detected'").fetchone()[0]
    ch = c.get(f"/api/vehicles/{vid}/charges/{cid}").json()
    assert ch["end_estimated"] == 1 and ch["ended_at"] == "2027-02-11T22:23:47+00:00"
    assert [p["t"] for p in ch["curve"]][-1] == "2027-02-11T21:30:00+00:00"  # the 05:27 reading is after the end
    assert ch["curve_gaps"] == [{"from": "2027-02-11T19:49:00+00:00", "to": "2027-02-11T21:26:00+00:00"},
                                {"from": "2027-02-11T21:30:00+00:00", "to": "2027-02-11T22:23:47+00:00"}]


def test_home_filter_applies_before_paging():
    c, conn, api, vid = connected()
    seed_charge(conn, vid, day="2027-02-11", lat=50.0, lon=8.0)
    seed_charge(conn, vid, day="2027-02-12", lat=51.0, lon=9.0)
    seed_charge(conn, vid, day="2027-02-13", lat=50.0, lon=8.0)
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0}})
    r = c.get(f"/api/vehicles/{vid}/charges?kind=home&limit=1&offset=1").json()
    assert r["total"] == 2 and len(r["items"]) == 1 and r["items"][0]["started_at"].startswith("2027-02-11")
    assert c.get(f"/api/vehicles/{vid}/charges?kind=public").json()["total"] == 1


def test_day_filters_respect_the_browsers_timezone():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)  # 08:00-08:40 UTC on 2027-02-10
    url = f"/api/vehicles/{vid}/trips?from=2027-02-10&to=2027-02-10"
    assert c.get(url).json()["total"] == 1  # UTC: it is the 10th
    assert c.get(url + "&tz_offset=600").json()["total"] == 0  # UTC-10: 22:00 on the 9th, not the 10th
    assert c.get(f"/api/vehicles/{vid}/trips?from=2027-02-09&to=2027-02-09&tz_offset=600").json()["total"] == 1
    assert c.get(f"/api/vehicles/{vid}/trips?from=nonsense").status_code == 400
    assert c.get(f"/api/vehicles/{vid}/events?from=2027-02-10&tz_offset=600").status_code == 200


def test_home_can_be_set_from_a_charge():
    c, conn, api, vid = connected()
    seed_charge(conn, vid, lat=50.5, lon=8.5)
    cid = c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]["id"]
    r = c.post(f"/api/vehicles/{vid}/home-here?charge_id={cid}").json()
    assert (r["home_lat"], r["home_lon"]) == (50.5, 8.5)
    assert c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]["place_kind_resolved"] == "home"
    assert c.post(f"/api/vehicles/{vid}/home-here?charge_id=9999").status_code == 400


def test_home_here_moves_the_home_geofence():
    c, conn, api, vid = connected()
    r = c.post(f"/api/vehicles/{vid}/home-here").json()
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], r["home_lat"], r["home_lon"]) == (50.11, 8.68, 50.11, 8.68)


def test_settings_home_coordinates_update_the_home_place():
    c, conn, api, vid = connected()
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 200}})
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], home["radius_m"]) == (50.0, 8.0, 200)


def test_saving_prices_keeps_the_home_place():
    c, conn, api, vid = connected()
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 200}})
    c.put("/api/settings", json={"tariff": {"home_kwh": 0.25}})  # prices only: the place stays where it is
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], home["radius_m"]) == (50.0, 8.0, 200)
    c.put("/api/settings", json={"tariff": {"home_lat": None, "home_lon": None}})  # old clients may clear the keys
    homes = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchall()
    assert len(homes) == 1 and (homes[0]["lat"], homes[0]["lon"], homes[0]["radius_m"]) == (50.0, 8.0, 200)


def test_home_here_keeps_the_home_radius():
    c, conn, api, vid = connected()
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 300}})
    c.post(f"/api/vehicles/{vid}/home-here")
    home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
    assert (home["lat"], home["lon"], home["radius_m"]) == (50.11, 8.68, 300)


def test_home_here_needs_both_coordinates():
    """normalise.py writes lat and lon independently; a one-sided position must be a 400, not float(None)."""
    c, conn, api, vid = connected()
    store.save_sections(conn, vid, {"position": {"state": "PARKED", "lat": 50.11, "lon": None}},
                        "2027-02-10T08:00:00+00:00")
    conn.commit()
    r = c.post(f"/api/vehicles/{vid}/home-here")
    assert r.status_code == 400
    assert r.json()["detail"] == "The car's position is not known yet (it is moving or not reported)."
    assert conn.execute("SELECT COUNT(*) FROM geofences WHERE kind='home'").fetchone()[0] == 0


def test_non_finite_settings_coordinates_keep_the_home_place():
    """NaN/Infinity pass clean_tariff; SQLite stores NaN as NULL against the NOT NULL coordinates."""
    c, conn, api, vid = connected()
    c.put("/api/settings", json={"tariff": {"home_lat": 50.0, "home_lon": 8.0, "home_radius_m": 200}})
    ctx = c.app.state.ctx
    for bad in (float("nan"), float("inf")):
        put_settings(SettingsBody(tariff={"home_lat": bad, "home_lon": 8.0}), ctx)
        home = conn.execute("SELECT * FROM geofences WHERE kind='home'").fetchone()
        assert (home["lat"], home["lon"], home["radius_m"]) == (50.0, 8.0, 200)


def test_statistics_and_battery_estimate():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_charge(conn, vid, start=20, end=80)  # 30 kWh for 60 % -> 50 kWh per 100 % at the wall
    s = c.get(f"/api/vehicles/{vid}/stats").json()
    m = {x["month"]: x for x in s["monthly"]}
    assert m["2027-02"]["trips"] == 1 and m["2027-02"]["km"] == 40 and m["2027-02"]["charges"] == 1
    assert m["2027-02"]["charged_kwh"] == 30.0 and m["2027-02"]["ac_kwh"] == 30.0 and m["2027-02"]["kwh_100km"] is not None
    assert s["totals"]["km"] == 40 and s["totals"]["charged_kwh"] == 30.0 and s["totals"]["currency"] == "EUR"
    b = c.get(f"/api/vehicles/{vid}/battery").json()
    assert b["estimate_kwh_at_wall"] == 50.0 and b["samples"] == 1 and "does not report battery health" in b["note"]
    assert b["nominal_kwh"] == 77.0 and b["charging"]["settings"]["target_soc"] == 80 and b["profiles"]["profiles"][0]["id"] == 7


def test_events_history_and_map():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_charge(conn, vid)
    ev = c.get(f"/api/vehicles/{vid}/events").json()
    kinds = [e["kind"] for e in ev["items"]]
    assert "trip_start" in kinds and "charge_end" in kinds and set(kinds) <= set(ev["kinds"])
    assert c.get(f"/api/vehicles/{vid}/events?kind=trip_end").json()["total"] == 1
    assert c.get(f"/api/vehicles/{vid}/events?q=kWh").json()["total"] == 1
    assert len(c.get(f"/api/vehicles/{vid}/history?hours=8760").json()) > 5
    m = c.get(f"/api/vehicles/{vid}/map").json()
    assert m["current"]["lat"] == 50.11 and m["trips"][0]["end_place"] == "Work" and m["charges"]
    assert any(p["address"] == "Work" for p in m["parked"])


def test_map_returns_places_and_respects_the_limit():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150}).json()
    m = c.get(f"/api/vehicles/{vid}/map?limit=1").json()
    assert m["limit"] == 1 and len(m["parked"]) <= 1
    assert any(p["id"] == work["id"] and p["visit_count"] == 1 for p in m["places"])
    assert c.get(f"/api/vehicles/{vid}/map?limit=0").status_code == 422
    assert c.get(f"/api/vehicles/{vid}/map?limit=2001").status_code == 422
    assert m["tariff"]["currency"] == "EUR"  # the map keeps its live position and tariff


def test_map_marks_a_parked_cluster_inside_a_place():
    c, conn, api, vid = connected()
    place = c.post("/api/places", json={"name": "Parked", "kind": "place", "lat": 50.11, "lon": 8.68, "radius_m": 150}).json()
    m = c.get(f"/api/vehicles/{vid}/map").json()
    assert m["limit"] == 1000 and any(p["place_id"] == place["id"] for p in m["parked"])


def test_map_place_days_use_the_browser_offset():
    """R14: the map's place rows count days in the same local day as the places pages."""
    c, conn, api, vid = connected()
    seed_trip(conn, vid, day="2027-02-10")
    seed_trip(conn, vid, day="2027-02-11")
    conn.execute("UPDATE trips SET ended_at='2027-02-10T23:30:00+00:00' WHERE started_at LIKE '2027-02-10%'")
    conn.execute("UPDATE trips SET ended_at='2027-02-11T22:30:00+00:00' WHERE started_at LIKE '2027-02-11%'")
    conn.commit()
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4}).json()

    def map_days(tz: int) -> int:
        places = c.get(f"/api/vehicles/{vid}/map?tz_offset={tz}").json()["places"]
        return next(p for p in places if p["id"] == work["id"])["day_count"]

    assert map_days(0) == 2  # UTC: one arrival per day
    assert map_days(-60) == 1  # CET: both arrivals are on the 11th locally
    assert c.get(f"/api/vehicles/{vid}/map?tz_offset=841").status_code == 422
    assert c.get(f"/api/vehicles/{vid}/map?tz_offset=-841").status_code == 422


def test_places_crud_and_one_home():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    home = c.post("/api/places", json={"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0, "radius_m": 150}).json()
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150}).json()
    assert work["visit_count"] == 1 and home["kind"] == "home"
    assert c.post("/api/places", json={"name": "Second home", "kind": "home", "lat": 51, "lon": 9}).status_code == 409
    edited = c.put(f"/api/places/{work['id']}",
                   json={"name": "Office 2", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 80}).json()
    assert edited["name"] == "Office 2" and edited["radius_m"] == 80
    assert c.delete(f"/api/places/{home['id']}").status_code == 400
    assert c.delete(f"/api/places/{work['id']}").json() == {"ok": True, "trips": 1, "charges": 0}


def test_moving_the_home_place_mirrors_its_position_into_the_tariff():
    """R15: the cost engine and the map's near-home fallback read the legacy tariff home position."""
    c, conn, api, vid = connected()
    home = c.post("/api/places", json={"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0,
                                        "radius_m": 150}).json()
    c.put(f"/api/places/{home['id']}", json={"name": "Home", "kind": "home", "lat": 50.2, "lon": 8.2,
                                             "radius_m": 150})
    tariff = c.get("/api/settings").json()["tariff"]
    assert (tariff["home_lat"], tariff["home_lon"]) == (50.2, 8.2)


def test_resizing_the_home_place_mirrors_its_radius_into_the_tariff():
    c, conn, api, vid = connected()
    home = c.post("/api/places", json={"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0,
                                        "radius_m": 150}).json()
    c.put(f"/api/places/{home['id']}", json={"name": "Home", "kind": "home", "lat": 50.0, "lon": 8.0,
                                             "radius_m": 300})
    assert c.get("/api/settings").json()["tariff"]["home_radius_m"] == 300


def test_converting_a_place_to_home_mirrors_it_into_the_tariff():
    c, conn, api, vid = connected()
    place = c.post("/api/places", json={"name": "Casa", "kind": "work", "lat": 51.0, "lon": 9.0,
                                         "radius_m": 200}).json()
    assert c.get("/api/settings").json()["tariff"]["home_lat"] is None  # not a home: no mirror
    c.put(f"/api/places/{place['id']}", json={"name": "Casa", "kind": "home", "lat": 51.0, "lon": 9.0,
                                              "radius_m": 200})
    tariff = c.get("/api/settings").json()["tariff"]
    assert (tariff["home_lat"], tariff["home_lon"], tariff["home_radius_m"]) == (51.0, 9.0, 200)


def test_place_validation():
    c, conn, api, vid = connected()
    for body in ({"name": "", "lat": 50, "lon": 8},
                 {"name": "X", "lat": 91, "lon": 8},
                 {"name": "X", "lat": 50, "lon": 8, "radius_m": 5},
                 {"name": "X", "lat": 50, "lon": 8, "free": True, "price_kwh": 0.5}):
        assert c.post("/api/places", json=body).status_code == 400


def test_place_validation_messages():
    """The exact English texts the frontend translates (static/i18n/de.json) and the API shows."""
    c, conn, api, vid = connected()
    cases = (
        ({"name": "", "lat": 50, "lon": 8}, "Name must be 1 to 60 characters."),
        ({"name": "X", "kind": "moon", "lat": 50, "lon": 8}, "Kind must be home, work or place."),
        ({"name": "X", "lat": 91, "lon": 8}, "Latitude must be between -90 and 90."),
        ({"name": "X", "lat": 50, "lon": 181}, "Longitude must be between -180 and 180."),
        ({"name": "X", "lat": 50, "lon": 8, "radius_m": 5}, "Radius must be between 20 and 5000 metres."),
        ({"name": "X", "lat": 50, "lon": 8, "color": "red"}, "Colour must be a hex colour such as #0b7a52."),
        ({"name": "X", "lat": 50, "lon": 8, "price_kwh": 1001}, "Price per kWh must be between 0 and 1000."),
        ({"name": "X", "lat": 50, "lon": 8, "price_minute": -1}, "Price per minute must be between 0 and 1000."),
        ({"name": "X", "lat": 50, "lon": 8, "session_fee": 10001}, "Session fee must be between 0 and 10000."),
        ({"name": "X", "lat": 50, "lon": 8, "free": True, "price_kwh": 0.5}, "A free place cannot have a price."),
    )
    for body, message in cases:
        r = c.post("/api/places", json=body)
        assert r.status_code == 400 and r.json()["detail"] == message
    assert c.get("/api/places/9999").json()["detail"] == "Place not found."


def test_price_caps_cover_every_supported_currency():
    """Issue 46: per-unit caps sit above every supported currency (HUF DC ~300/kWh), totals at 10000."""
    c, conn, api, vid = connected()
    # CZK/HUF-scale prices are accepted: 20 CZK DC, 300 Ft DC, 150 Ft public AC.
    r = c.post("/api/places", json={"name": "DC CZ", "lat": 50, "lon": 8, "price_kwh": 20, "price_minute": 5})
    assert r.status_code == 200 and r.json()["price_kwh"] == 20
    r = c.post("/api/places", json={"name": "DC HU", "lat": 50, "lon": 8, "price_kwh": 300, "session_fee": 9500})
    assert r.status_code == 200 and r.json()["price_kwh"] == 300
    r = c.put("/api/settings", json={"tariff": {"currency": "CZK", "home_kwh": 5, "public_ac_kwh": 12, "public_dc_kwh": 20}})
    assert r.status_code == 200
    tariff = c.get("/api/settings").json()["tariff"]
    assert (tariff["home_kwh"], tariff["public_ac_kwh"], tariff["public_dc_kwh"]) == (5, 12, 20)
    r = c.put("/api/settings", json={"tariff": {"currency": "HUF", "public_dc_kwh": 300}})
    assert r.status_code == 200
    # And the caps still stop magnitude typos.
    r = c.put("/api/settings", json={"tariff": {"home_kwh": 1001}})
    assert r.status_code == 400 and r.json()["detail"] == "home_kwh must be between 0 and 1000 per kWh"


def test_place_day_count_uses_the_browser_offset():
    """R2: list and detail count days in the browser's local day, not in UTC."""
    c, conn, api, vid = connected()
    seed_trip(conn, vid, day="2027-02-10")
    seed_trip(conn, vid, day="2027-02-11")
    conn.execute("UPDATE trips SET ended_at='2027-02-10T23:30:00+00:00' WHERE started_at LIKE '2027-02-10%'")
    conn.execute("UPDATE trips SET ended_at='2027-02-11T22:30:00+00:00' WHERE started_at LIKE '2027-02-11%'")
    conn.commit()
    work = c.post("/api/places", json={"name": "Work", "kind": "work", "lat": 50.4, "lon": 8.4}).json()
    assert work["visit_count"] == 2 and work["day_count"] == 2
    assert c.get("/api/places?tz_offset=-60").json()["items"][0]["day_count"] == 1
    assert c.get(f"/api/places/{work['id']}?tz_offset=-60").json()["day_count"] == 1


def test_editing_a_place_reassigns_trips_and_charges():
    c, conn, api, vid = connected()
    seed_charge(conn, vid, lat=50.001, lon=8.001)
    place = c.post("/api/places", json={"name": "Edge", "kind": "place", "lat": 50.0, "lon": 8.0,
                                          "radius_m": 150, "price_kwh": 0.50}).json()
    linked = c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]
    assert linked["geofence_id"] == place["id"] and linked["cost_basis"] == "place"
    c.put(f"/api/places/{place['id']}", json={"name": "Edge", "kind": "place", "lat": 50.0, "lon": 8.0, "radius_m": 20})
    cleared = c.get(f"/api/vehicles/{vid}/charges").json()["items"][0]
    assert cleared["geofence_id"] is None and cleared["cost_basis"] == "tariff-guess"


def test_place_detail_lists_visits_and_charges():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_charge(conn, vid, lat=50.4, lon=8.4)
    work = c.post("/api/places", json={"name": "Office", "kind": "work", "lat": 50.4, "lon": 8.4, "radius_m": 150,
                                        "price_kwh": 0.50}).json()
    d = c.get(f"/api/places/{work['id']}?tz_offset=0").json()
    assert d["visit_count"] == 1 and len(d["visits"]) == 1 and d["charged_kwh"] > 0
    assert d["charges"][0]["cost_basis"] == "place" and d["charges"][0]["place_kind_resolved"] == "public"


def test_battery_history_draws_a_drive_even_without_readings_during_it():
    """Regression: only readings taken AFTER a drive existed, so the chart was one flat line. A trip's start and end
    charge level are now part of the curve."""
    from datetime import UTC, datetime, timedelta

    c, conn, api, vid = connected()  # one reading, 55 %, stamped "now" by the poller
    def ago(h):
        return (datetime.now(UTC) - timedelta(hours=h)).isoformat()
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,start_soc,end_soc,distance_km) VALUES(?,?,?,?,?,?,?)",
                 (vid, "x", ago(3), ago(2.5), 47, 36, 32))
    conn.execute("INSERT INTO charges(vehicle_id,started_at,ended_at,start_soc,end_soc) VALUES(?,?,?,?,?)",
                 (vid, ago(9), ago(5), 20, 47))
    h = c.get(f"/api/vehicles/{vid}/history?hours=8760").json()
    assert [(p["soc"], p.get("src")) for p in h] == [(20, "charge"), (47, "charge"), (47, "trip"), (36, "trip"), (55, None)]
    assert [p["t"] for p in h] == sorted(p["t"] for p in h)  # in time order: rises while charging, falls on the drive
    assert c.get(f"/api/vehicles/{vid}/battery?hours=8760").json()["history"] == h


def test_commands_catalogue_log_and_execution():
    c, conn, api, vid = connected()
    cat = c.get(f"/api/vehicles/{vid}/commands").json()
    assert cat["spin_set"] is True and {x["name"] for x in cat["catalogue"] if x["supported"]} >= {"start_charging", "set_charge_limit"}
    r = c.post(f"/api/vehicles/{vid}/command", json={"name": "set_charge_limit", "params": {"percent": 70}})
    assert r.status_code == 200 and r.json()["ok"] and api.calls[-1][2] == "setChargingLimit"
    assert c.post(f"/api/vehicles/{vid}/command", json={"name": "set_charge_limit", "params": {"percent": 5000}}).status_code == 400
    assert c.post(f"/api/vehicles/{vid}/command", json={"name": "start_aux_heating", "params": {}}).status_code == 400  # unsupported here
    assert c.post(f"/api/vehicles/{vid}/command", json={"name": "unlock"}).status_code == 400  # there is no such command
    log = c.get(f"/api/vehicles/{vid}/commands").json()["log"]
    assert log[0]["name"] == "set_charge_limit" and log[0]["ok"] == 1 and log[0]["params"] == {"percent": 70}
    from skoda_mate.client import ApiError, RateInfo

    api.operate_error = ApiError(422, "operation-disabled", "x", None, RateInfo())
    r = c.post(f"/api/vehicles/{vid}/command", json={"name": "stop_charging"}).json()
    assert r["ok"] is False and r["kind"] == "operation-disabled" and "disabled" in r["error"]


def test_diagnostics_are_redacted_but_raw_is_not():
    c, conn, api, vid = connected()
    raw = c.get(f"/api/vehicles/{vid}/raw").json()
    assert raw["vehicle"]["vin"] == VIN and raw["vehicle"]["parkingPosition"]["gpsCoordinates"]["latitude"] == 50.11
    r = c.get(f"/api/vehicles/{vid}/diagnostics")
    text = r.text
    assert "attachment" in r.headers["content-disposition"]
    for secret in (VIN, "1MB 1234", "My Enyaq", "50.11", "Main Street", "Home"):
        assert secret not in text, secret
    d = json.loads(text)
    assert d["response_redacted"]["vehicle"]["vin"] == VIN[:3] + "*" * 11 + VIN[-3:]
    assert d["parts"]["charging"] == "present" and d["poller"]["budget"]["limit"] == 20 and d["api_calls"]
    assert KEY not in text and "\"1234\"" not in text  # neither the API key nor the S-PIN


def test_exports_and_backup():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    seed_charge(conn, vid)
    r = c.get(f"/api/vehicles/{vid}/export/trips.csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert r.headers["content-type"].startswith("text/csv") and rows[0]["distance_km"] == "40.0" and "route_json" not in rows[0]
    assert "energy_kwh" in c.get(f"/api/vehicles/{vid}/export/charges.csv").text
    assert c.get(f"/api/vehicles/{vid}/export/passwords.csv").status_code == 404
    b = c.get("/api/backup")
    assert b.status_code == 200 and b.content[:15] == b"SQLite format 3"
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b.content)
    try:
        assert sqlite3.connect(f.name).execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    finally:
        os.unlink(f.name)


def test_settings_roundtrip_and_validation():
    c, conn, api, vid = connected()
    s = c.get("/api/settings").json()
    assert s["poll_idle_s"] == 1200 and s["poll_active_s"] == 300 and s["poll_min_s"] == 180 and s["tariff"]["home_kwh"] == 0.30
    r = c.put("/api/settings", json={"tariff": {"home_kwh": 0.25, "currency": "chf"}, "poll_idle_s": 900, "units": "mi",
                                     "language": "de", "theme": "dark", "command_reserve": 6, "battery_kwh_default": 77})
    assert r.status_code == 200
    s = r.json()
    assert s["tariff"]["home_kwh"] == 0.25 and s["tariff"]["currency"] == "CHF" and s["poll_idle_s"] == 900
    assert (s["units"], s["language"], s["theme"], s["command_reserve"]) == ("mi", "de", "dark", 6)
    assert c.get(f"/api/vehicles/{vid}/overview").json()["vehicle"]["capacity_kwh"] == 77.0
    for bad in ({"poll_idle_s": 10}, {"poll_active_s": 99999}, {"units": "furlongs"}, {"tariff": {"home_kwh": -1}},
                {"tariff": {"currency": ""} if False else {"home_radius_m": 1}}, {"battery_kwh_default": 5}, {"command_reserve": 99}):
        assert c.put("/api/settings", json=bad).status_code == 400, bad
    assert c.put(f"/api/vehicles/{vid}", json={"battery_kwh": 82}).status_code == 200
    assert c.get(f"/api/vehicles/{vid}/overview").json()["vehicle"]["capacity_kwh"] == 82.0
    assert c.put(f"/api/vehicles/{vid}", json={"battery_kwh": 5}).status_code == 400


def test_unknown_vehicle_and_unauthenticated_access():
    c, conn, api, vid = connected()
    for path in ("overview", "trips", "charges", "stats", "battery", "events", "map", "commands", "raw"):
        assert c.get(f"/api/vehicles/999/{path}").status_code == 404, path
    c.cookies.clear()
    assert c.get(f"/api/vehicles/{vid}/overview").status_code == 401
    assert c.get("/api/backup").status_code == 401 and c.get("/api/settings").status_code == 401


def test_bearer_token_for_scripts():
    c, conn, api, vid = connected(api_token="tok")
    c.cookies.clear()
    assert c.get("/api/vehicles", headers={"Authorization": "Bearer tok"}).status_code == 200
    assert c.get("/api/vehicles", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_ice_vehicle_overview_hides_battery_features():
    from .fixtures import ICE

    api = FakeApi([json.loads(json.dumps(ICE))])
    c, conn, _, vid = connected(api=api)
    o = c.get(f"/api/vehicles/{vid}/overview").json()
    assert o["parts"]["charging"]["state"] == "unsupported" and o["parts"]["fuelStatus"]["available"]
    assert o["features"]["charge_control"]["available"] is False and o["features"]["aux_heating"]["available"] is True
    assert o["snapshot"]["fuel_pct"] == 62 and o["snapshot"]["charging"] == 0
    assert o["operation_params"]["startAuxiliaryHeating"] == ["targetTemperature"]  # what this heater takes besides the basics
    ops = {x["id"]: x for x in c.get(f"/api/vehicles/{vid}/capabilities").json()["operations"]}
    assert ops["startAuxiliaryHeating"]["accepts"] == ["targetTemperature"] and "accepts" not in ops["startCharging"]


def test_capabilities_lists_every_operation_and_field_with_this_cars_state():
    c, conn, api, vid = connected(charging=True)
    cap = c.get(f"/api/vehicles/{vid}/capabilities").json()
    ops = {o["id"]: o for o in cap["operations"]}
    assert len(ops) == 12 and ops["getVehicle"]["supported"] is True
    assert ops["startCharging"]["supported"] is True and ops["startAuxiliaryHeating"]["supported"] is False  # per this car's operations
    assert cap["summary"]["operations_total"] == 11 and cap["summary"]["operations_supported"] == 7
    parts = {p["key"]: p for p in cap["parts"]}
    assert parts["charging"]["state"] == "present" and parts["fuelStatus"]["state"] == "unsupported" and parts["fuelStatus"]["reason"]
    soc = [r for r in parts["charging"]["fields"] if r["api"] == "charging.status.battery.stateOfChargeInPercent"][0]
    assert soc["value"] == 55
    assert [r["value"] for r in parts["odometer"]["fields"]][0] == 12345
    assert cap["contract"]["version"] == "1.2.0" and cap["derived"] and cap["unavailable"]


def test_api_calls_are_paged_newest_first_and_can_be_filtered_to_failures():
    c, conn, _, vid = connected()
    conn.execute("DELETE FROM api_calls")
    for i in range(30):
        conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok,error) VALUES(?,?,?,?,?)", (vid, 1000 + i, f"/e{i}", 0 if i % 10 == 0 else 1, "boom" if i % 10 == 0 else None))
    conn.commit()
    first = c.get(f"/api/vehicles/{vid}/calls?limit=25").json()
    assert first["total"] == 30 and len(first["items"]) == 25 and first["items"][0]["endpoint"] == "/e29"
    rest = c.get(f"/api/vehicles/{vid}/calls?limit=25&offset=25").json()
    assert [x["endpoint"] for x in rest["items"]] == ["/e4", "/e3", "/e2", "/e1", "/e0"]
    bad = c.get(f"/api/vehicles/{vid}/calls?failed=true").json()
    assert bad["total"] == 3 and [x["endpoint"] for x in bad["items"]] == ["/e20", "/e10", "/e0"]


TIMELINE_NOW = "2027-03-10T23:30:00+00:00"


def freeze_now(c, iso=TIMELINE_NOW):
    """Pin the route clock: the timeline defaults and error paths must not read the wall clock."""
    c.app.state.ctx.now_iso = lambda: iso


def test_timeline_defaults_to_seven_days():
    c, conn, api, vid = connected()
    freeze_now(c)
    body = c.get(f"/api/vehicles/{vid}/timeline?tz_offset=-60").json()
    # UTC 23:30 is already the 11th at UTC+1; the default window is that day and the six before it.
    assert (body["from"], body["to"]) == ("2027-03-05", "2027-03-11")
    assert [d["date"] for d in body["days"]] == [f"2027-03-{d:02d}" for d in range(5, 12)]
    assert body["summary"]["parked_min"] == 0 and body["summary"]["cost"] is None


def test_timeline_route_rejects_a_range_over_31_days_or_reversed():
    c, conn, api, vid = connected()
    freeze_now(c)
    r = c.get(f"/api/vehicles/{vid}/timeline?from=2027-03-01&to=2027-04-01")
    assert r.status_code == 400 and r.json()["detail"] == "The range is limited to 31 days."
    r = c.get(f"/api/vehicles/{vid}/timeline?from=2027-03-02&to=2027-03-01")
    assert r.status_code == 400 and r.json()["detail"] == "The start must be before the end."
    r = c.get(f"/api/vehicles/{vid}/timeline?from=nonsense")
    assert r.status_code == 400 and r.json()["detail"] == "bad date 'nonsense', expected YYYY-MM-DD"


def test_timeline_route_rejects_a_malformed_to_date_with_the_app_message():
    c, conn, api, vid = connected()
    freeze_now(c)
    # `to` alone must fail the same way `from` does, not with FastAPI's raw isoformat message.
    r = c.get(f"/api/vehicles/{vid}/timeline?to=nonsense")
    assert r.status_code == 400 and r.json()["detail"] == "bad date 'nonsense', expected YYYY-MM-DD"


def test_timeline_route_returns_404_for_another_vehicle():
    c, conn, api, vid = connected()
    freeze_now(c)
    r = c.get("/api/vehicles/999/timeline?from=2027-03-01&to=2027-03-07")
    assert r.status_code == 404 and r.json()["detail"] == "no such vehicle"


def test_range_errors_have_german_entries():
    import json
    from pathlib import Path
    de = json.loads((Path(__file__).parent.parent / "skoda_mate" / "static" / "i18n" / "de.json").read_text(encoding="utf-8"))
    for message in ("The start must be before the end.", "The range is limited to 31 days.",
                    "min_hours must be between 1 and 168."):
        assert de.get(message), message


def test_every_static_file_is_in_the_python_package():
    """A file outside the package-data globs works from a checkout and is missing from an installed package."""
    import tomllib
    from pathlib import Path
    root = Path(__file__).parent.parent
    globs = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]["skoda_mate"]
    package = root / "skoda_mate"
    shipped = {path for pattern in globs for path in package.glob(pattern)}
    missing = [str(p.relative_to(package)) for p in (package / "static").rglob("*") if p.is_file() and p not in shipped]
    assert not missing


def test_parked_loss_route_turns_only_range_errors_into_a_400(monkeypatch):
    c, conn, api, vid = connected()
    freeze_now(c)
    assert c.get(f"/api/vehicles/{vid}/parked-loss?from=2027-03-05&to=2027-03-01").status_code == 400

    def boom(*a, **kw):
        raise ValueError("a bug, not a bad request")
    monkeypatch.setattr("skoda_mate.activity.parked_loss", boom)
    with pytest.raises(ValueError, match="a bug"):  # not swallowed into a 400: the test client re-raises server errors
        c.get(f"/api/vehicles/{vid}/parked-loss")


def test_local_bound_accepts_the_space_separated_datetime():
    from skoda_mate.presenters import local_bound
    assert local_bound("2027-03-01T10:00:00+00:00") == "2027-03-01T10:00:00+00:00"
    # the form before the timeline work: parsed as a local datetime, shifted by the offset into UTC
    assert local_bound("2027-03-01 10:00", 60) == "2027-03-01T11:00:00+00:00"
    assert local_bound("2027-03-01", 0, end=True) == "2027-03-02T00:00:00+00:00"
    with pytest.raises(Exception, match="bad date"):
        local_bound("nonsense")
