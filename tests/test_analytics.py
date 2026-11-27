"""Insight: charging, driving and the projected range, all read from the stored rows."""
from datetime import UTC, datetime, timedelta

import pytest

from skoda_mate import analytics, costs, places, recorder, schema, stats

from .test_web import connected

TARIFF = costs.DEFAULT_TARIFF  # home 0.30, public AC 0.55, public DC 0.79


def _setup():
    conn = schema.connect(":memory:")
    return conn, recorder.upsert_vehicle(conn, "TMBJB9NY5RF999999", "Enyaq", None, 77.0)


def _insert(conn, table, **cols):
    cur = conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(cols.values()))
    conn.commit()
    return cur.lastrowid


def _charge(conn, vid, start="2027-03-01T10:00:00+00:00", *, minutes=60, **cols):
    end = (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat()
    base = {"vehicle_id": vid, "started_at": start, "ended_at": end, "duration_min": minutes, "energy_kwh": 10.0,
            "max_power_kw": 11.0, "charge_type": "AC", "source": "detected"}
    return _insert(conn, "charges", **{**base, **cols})


def _trip(conn, vid, start="2027-03-01T07:00:00+00:00", *, km=10.0, minutes=20, **cols):
    end = (datetime.fromisoformat(start) + timedelta(minutes=minutes)).isoformat()
    base = {"vehicle_id": vid, "cloud_id": f"t-{start}-{km}", "started_at": start, "ended_at": end,
            "distance_km": km, "duration_min": minutes}
    return _insert(conn, "trips", **{**base, **cols})


def _snap(conn, vid, at, **cols):
    return _insert(conn, "snapshots", vehicle_id=vid, recorded_at=at, **cols)


def _place(conn, name="Work", lat=52.5, lon=13.4, kind="work", **extra):
    return places.create(conn, {"name": name, "kind": kind, "lat": lat, "lon": lon, **extra})["id"] \
        if name else None


# ---------------------------------------------------------------- charging

def test_charging_totals_and_cost_per_kwh():
    conn, vid = _setup()
    _charge(conn, vid, energy_kwh=10.0, place_kind="home")  # 3.00
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", energy_kwh=20.0, charge_type="DC", max_power_kw=100.0)  # 15.80
    t = analytics.charging(conn, vid, TARIFF)["totals"]
    assert (t["sessions"], t["energy_kwh"], t["cost"], t["cost_partial"]) == (2, 30.0, 18.8, False)
    assert t["cost_per_kwh"] == 0.627
    assert (t["measured_sessions"], t["inferred_sessions"], t["inferred_share"]) == (2, 0, 0.0)


def test_a_period_with_only_inferred_charges_has_energy_but_no_power_curve_or_heatmap():
    conn, vid = _setup()
    _charge(conn, vid, source="inferred", charge_type=None, max_power_kw=0, minutes=600)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", source="import-trip", charge_type="DC", max_power_kw=50)
    _snap(conn, vid, "2027-03-02T10:10:00+00:00", soc=50, charging=1, charge_power_kw=40.0)
    out = analytics.charging(conn, vid, TARIFF)
    t = out["totals"]
    assert (t["energy_kwh"], t["inferred_sessions"], t["inferred_share"], t["measured_kwh"]) == (20.0, 2, 1.0, 0.0)
    assert t["cost"] > 0
    assert all(v["avg_power_kw"] is None and v["peak_power_kw"] is None and v["sessions"] == 0
               for v in out["types"].values())
    assert out["curve"] == {"ac": [], "dc": []}
    assert sum(map(sum, out["heatmap"])) == 0 and out["heatmap_excluded"] == 2


def test_ac_and_dc_never_mix_in_the_power_average():
    conn, vid = _setup()
    _charge(conn, vid, energy_kwh=11.0, minutes=60, max_power_kw=11.0)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", energy_kwh=11.0, minutes=120, max_power_kw=7.0)
    _charge(conn, vid, "2027-03-03T10:00:00+00:00", energy_kwh=40.0, minutes=30, max_power_kw=120.0, charge_type="DC")
    types = analytics.charging(conn, vid, TARIFF)["types"]
    assert (types["ac"]["avg_power_kw"], types["ac"]["peak_power_kw"], types["ac"]["sessions"]) == (7.3, 11.0, 2)
    assert (types["dc"]["avg_power_kw"], types["dc"]["peak_power_kw"]) == (80.0, 120.0)
    assert types["unknown"] == {"sessions": 0, "energy_kwh": 0.0, "avg_power_kw": None, "peak_power_kw": None,
                                "power_sessions": 0}


def test_a_charge_with_an_estimated_end_is_left_out_of_the_average_power():
    conn, vid = _setup()
    _charge(conn, vid, energy_kwh=11.0, minutes=60)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", energy_kwh=30.0, minutes=60, end_estimated=1)
    ac = analytics.charging(conn, vid, TARIFF)["types"]["ac"]
    assert (ac["avg_power_kw"], ac["power_sessions"], ac["sessions"]) == (11.0, 1, 2)


def test_unknown_energy_keeps_the_cost_unknown():
    conn, vid = _setup()
    _charge(conn, vid, energy_kwh=None)
    t = analytics.charging(conn, vid, TARIFF)["totals"]
    assert (t["cost"], t["cost_partial"], t["cost_per_kwh"], t["unknown_energy_sessions"]) == (None, True, None, 1)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", energy_kwh=10.0, place_kind="home")
    t = analytics.charging(conn, vid, TARIFF)["totals"]
    assert (t["cost"], t["cost_partial"], t["cost_per_kwh"]) == (3.0, True, 0.3)


def test_home_public_other_split():
    conn, vid = _setup()
    _charge(conn, vid, place_kind="home")
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", charge_type="DC")
    _charge(conn, vid, "2027-03-03T10:00:00+00:00")  # AC, no home known: neither
    split = analytics.charging(conn, vid, TARIFF)["split"]
    assert [(k, split[k]["sessions"], split[k]["energy_kwh"], split[k]["cost"]) for k in ("home", "public", "other")] == \
        [("home", 1, 10.0, 3.0), ("public", 1, 10.0, 7.9), ("other", 1, 10.0, 3.0)]


def test_session_fees_count_once_per_charge_and_not_on_a_manual_cost():
    conn, vid = _setup()
    pid = _place(conn, price_kwh=0.5, session_fee=1.5)
    _charge(conn, vid, geofence_id=pid)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", geofence_id=pid, cost_manual=2.0)
    assert analytics.charging(conn, vid, TARIFF)["totals"]["session_fees"] == 1.5


def test_heatmap_uses_the_viewers_weekday_and_hour():
    conn, vid = _setup()
    _charge(conn, vid, "2027-03-07T23:30:00+00:00")  # Sunday 23:30 UTC is Monday 00:30 at UTC+1
    utc = analytics.charging(conn, vid, TARIFF)["heatmap"]
    local = analytics.charging(conn, vid, TARIFF, tz_offset=-60)["heatmap"]
    assert utc[6][23] == 1 and local[0][0] == 1 and sum(map(sum, local)) == 1
    assert len(local) == 7 and all(len(r) == 24 for r in local)


def test_top_places_name_the_place_else_the_address_else_unknown():
    conn, vid = _setup()
    pid = _place(conn)
    _charge(conn, vid, geofence_id=pid, energy_kwh=30.0)
    _charge(conn, vid, "2027-03-02T10:00:00+00:00", address="Rastplatz 1", energy_kwh=20.0)
    _charge(conn, vid, "2027-03-03T10:00:00+00:00", energy_kwh=5.0)
    top = analytics.charging(conn, vid, TARIFF)["top_places"]
    assert [(p["place_id"], p["name"], p["sessions"], p["energy_kwh"]) for p in top] == \
        [(pid, "Work", 1, 30.0), (None, "Rastplatz 1", 1, 20.0), (None, None, 1, 5.0)]


def test_curve_hides_bins_with_fewer_than_three_samples():
    conn, vid = _setup()
    _charge(conn, vid, "2027-03-01T10:00:00+00:00", charge_type="DC", minutes=60)
    for i, (soc, kw) in enumerate([(40, 100), (42, 90), (44, 80), (46, 70), (47, 60), (100, 5), (99, 6), (96, 7)]):
        _snap(conn, vid, f"2027-03-01T10:{i + 1:02d}:00+00:00", soc=soc, charging=1, charge_power_kw=float(kw))
    _snap(conn, vid, "2027-03-01T10:20:00+00:00", soc=41, charging=0, charge_power_kw=999.0)
    _snap(conn, vid, "2027-03-05T10:00:00+00:00", soc=41, charging=1, charge_power_kw=999.0)  # no charge row around it
    curve = analytics.charging(conn, vid, TARIFF)["curve"]
    assert curve["dc"] == [{"soc_from": 40, "soc_to": 45, "avg_kw": 90.0, "samples": 3},
                           {"soc_from": 95, "soc_to": 100, "avg_kw": 6.0, "samples": 3}]
    assert curve["ac"] == []


def test_charging_over_all_time_reconciles_with_the_statistics_and_skips_open_charges():
    conn, vid = _setup()
    _charge(conn, vid)
    _charge(conn, vid, "2027-04-01T10:00:00+00:00", source="inferred", energy_kwh=7.5)
    _insert(conn, "charges", vehicle_id=vid, started_at="2027-04-02T10:00:00+00:00", energy_kwh=99.0)
    t, s = analytics.charging(conn, vid, TARIFF)["totals"], stats.totals(conn, vid, TARIFF)
    assert (t["sessions"], t["energy_kwh"], t["cost"]) == (s["charges"], s["charged_kwh"], s["cost"])


def test_charging_range_bounds():
    conn, vid = _setup()
    _charge(conn, vid, "2027-02-28T23:00:00+00:00")
    _charge(conn, vid, "2027-03-01T10:00:00+00:00")
    out = analytics.charging(conn, vid, TARIFF, "2027-03-01T00:00:00+00:00", "2027-04-01T00:00:00+00:00")
    assert out["totals"]["sessions"] == 1


# ---------------------------------------------------------------- driving

def test_destinations_use_the_place_name_else_the_address_else_unknown():
    conn, vid = _setup()
    pid = _place(conn)
    for d in (1, 2, 3):
        _trip(conn, vid, f"2027-03-0{d}T07:00:00+00:00", end_geofence_id=pid, end_place="Street 9", km=20)
    for d in (4, 5):
        _trip(conn, vid, f"2027-03-0{d}T07:00:00+00:00", end_place="Zeil 90", km=5)
    _trip(conn, vid, "2027-03-06T07:00:00+00:00", km=1)
    top = analytics.driving(conn, vid)["top_destinations"]
    assert top == [{"place_id": pid, "name": "Work", "trips": 3, "km": 60.0},
                   {"place_id": None, "name": "Zeil 90", "trips": 2, "km": 10.0},
                   {"place_id": None, "name": None, "trips": 1, "km": 1.0}]


def test_distance_buckets_longest_and_averages():
    conn, vid = _setup()
    for i, km in enumerate([4.9, 5.0, 19.9, 20.0, 50.0, 100.0, 240.0]):
        _trip(conn, vid, f"2027-03-0{i + 1}T07:00:00+00:00", km=km, minutes=30)
    _trip(conn, vid, "2027-03-08T07:00:00+00:00", km=None, minutes=30)
    _trip(conn, vid, "2027-03-09T07:00:00+00:00", km=3.0, minutes=600, approx=1)
    out = analytics.driving(conn, vid)
    assert [(b["from_km"], b["to_km"], b["trips"]) for b in out["buckets"]] == \
        [(0, 5, 2), (5, 20, 2), (20, 50, 1), (50, 100, 1), (100, None, 2)]
    assert [t["distance_km"] for t in out["longest"]] == [240.0, 100.0, 50.0, 20.0, 19.9]
    assert set(out["longest"][0]) == {"id", "started_at", "distance_km", "start", "end", "approx"}
    tot = out["totals"]
    assert (tot["trips"], tot["km"], tot["approx_trips"], tot["avg_km"], tot["avg_duration_min"]) == (9, 442.8, 1, 55.4, 30)


def test_driving_heatmap_leaves_out_estimated_start_times():
    conn, vid = _setup()
    _trip(conn, vid, "2027-03-01T07:00:00+00:00")  # a Monday
    _trip(conn, vid, "2027-03-02T07:00:00+00:00", approx=1)
    out = analytics.driving(conn, vid, tz_offset=-60)
    assert out["heatmap"][0][8] == 1 and sum(map(sum, out["heatmap"])) == 1 and out["heatmap_excluded"] == 1


def test_consumption_trend_matches_the_monthly_table():
    conn, vid = _setup()
    _trip(conn, vid, "2027-02-10T07:00:00+00:00", km=100, energy_kwh=18.0)
    _trip(conn, vid, "2027-03-10T07:00:00+00:00", km=50, energy_kwh=10.0)
    _trip(conn, vid, "2027-03-11T07:00:00+00:00", km=40, energy_kwh=None)
    trend = analytics.driving(conn, vid)["consumption"]
    monthly = stats.monthly(conn, vid, TARIFF)
    assert [(r["month"], r["kwh_100km"]) for r in trend] == [(m["month"], m["kwh_100km"]) for m in monthly]
    assert trend[1] == {"month": "2027-03", "kwh_100km": 20.0, "km": 90.0, "trips": 2}


def test_annual_projection_needs_sixty_tracked_days():
    conn, vid = _setup()
    start = datetime(2027, 1, 1, 12, tzinfo=UTC)
    _snap(conn, vid, start.isoformat(), mileage_km=1000)
    _snap(conn, vid, (start + timedelta(days=59)).isoformat(), mileage_km=2180)
    out = analytics.driving(conn, vid)
    assert out["projection"] is None and out["tracked_days"] == 59
    _snap(conn, vid, (start + timedelta(days=60)).isoformat(), mileage_km=2200)
    out = analytics.driving(conn, vid, "2027-03-01T00:00:00+00:00")  # the period does not change the projection
    assert out["projection"] == {"annual_km": 7300, "days": 60} and out["tracked_days"] == 60


def test_driving_and_charging_on_an_empty_database():
    conn, vid = _setup()
    d = analytics.driving(conn, vid)
    assert d["totals"]["trips"] == 0 and d["totals"]["avg_km"] is None and d["top_destinations"] == []
    assert d["projection"] is None and d["tracked_days"] == 0
    c = analytics.charging(conn, vid, TARIFF)
    assert c["totals"]["sessions"] == 0 and c["totals"]["cost"] is None and c["totals"]["inferred_share"] is None


# ---------------------------------------------------------------- projected range

DAY0 = datetime(2027, 1, 1, 12, tzinfo=UTC)


def _ranges(conn, vid, days, km_at_100, *, first=0, soc=50):
    """One reading a day, `km_at_100(day)` projected to 100 %."""
    for d in range(first, first + days):
        _snap(conn, vid, (DAY0 + timedelta(days=d)).isoformat(), soc=soc, range_km=km_at_100(d) * soc / 100)


def test_range_points_need_soc_range_and_a_plausible_result():
    conn, vid = _setup()
    at = DAY0.isoformat()
    for soc, rng in [(19, 100), (None, 100), (50, 0), (50, None), (50, 99), (50, 501), (20, 100), (50, 250)]:
        _snap(conn, vid, at, soc=soc, range_km=rng)
    out = analytics.projected_range(conn, vid)
    assert out["samples"] == 2 and out["latest"] == {"day": "2027-01-01", "range_km": 500.0, "samples": 2}


def test_an_outlier_is_removed_and_counted():
    conn, vid = _setup()
    _ranges(conn, vid, 7, lambda d: 500 + d % 3)
    _snap(conn, vid, (DAY0 + timedelta(days=3, hours=1)).isoformat(), soc=50, range_km=400.0)  # 800 km at 100 %
    out = analytics.projected_range(conn, vid)
    assert (out["samples"], out["rejected"]) == (7, 1)
    assert max(p["range_km"] for p in out["daily"]) <= 502


def test_a_week_gives_a_value_but_no_trend_or_degradation():
    conn, vid = _setup()
    _ranges(conn, vid, 7, lambda d: 500)
    out = analytics.projected_range(conn, vid)
    assert out["latest"]["range_km"] == 500.0 and len(out["daily"]) == 7
    assert out["trend_km_per_year"] is None and out["degradation"] is None


def test_a_stable_year_gives_a_flat_trend():
    conn, vid = _setup()
    _ranges(conn, vid, 365, lambda d: 500 + d % 3)
    out = analytics.projected_range(conn, vid)
    assert abs(out["trend_km_per_year"]) < 0.5
    assert out["degradation"] == {"first_km": 501.0, "last_km": 501.0, "change_pct": 0.0, "first_days": 90, "last_days": 90}


def test_degradation_compares_the_first_and_last_ninety_days():
    conn, vid = _setup()
    _ranges(conn, vid, 90, lambda d: 500)
    _ranges(conn, vid, 90, lambda d: 475, first=270)
    out = analytics.projected_range(conn, vid)
    assert out["degradation"]["change_pct"] == -5.0 and out["trend_km_per_year"] < 0


def test_degradation_needs_two_separate_windows_with_enough_days():
    conn, vid = _setup()
    _ranges(conn, vid, 170, lambda d: 500)  # the two windows would overlap
    assert analytics.projected_range(conn, vid)["degradation"] is None
    _ranges(conn, vid, 10, lambda d: 500, first=400)  # the last window has only 10 days with data
    assert analytics.projected_range(conn, vid)["degradation"] is None


def test_a_winter_dip_survives_the_outlier_filter():
    conn, vid = _setup()
    _ranges(conn, vid, 120, lambda d: 520)
    _ranges(conn, vid, 120, lambda d: 420, first=120)
    out = analytics.projected_range(conn, vid)
    assert out["latest"]["range_km"] == 420.0 and out["samples"] >= 225


def test_range_days_follow_the_viewer_and_an_empty_database_is_empty():
    conn, vid = _setup()
    assert analytics.projected_range(conn, vid) == {
        "samples": 0, "rejected": 0, "daily": [], "latest": None, "trend_km_per_year": None, "degradation": None}
    _snap(conn, vid, "2027-03-01T23:30:00+00:00", soc=50, range_km=250.0)
    assert analytics.projected_range(conn, vid, tz_offset=-60)["latest"]["day"] == "2027-03-02"


def test_the_range_is_worked_out_again_only_after_a_new_reading(monkeypatch):
    conn, vid = _setup()
    _ranges(conn, vid, 3, lambda d: 500)
    runs, compute = [], analytics._window_change
    monkeypatch.setattr(analytics, "_window_change", lambda daily: runs.append(1) or compute(daily))
    first = analytics.projected_range(conn, vid)
    assert analytics.projected_range(conn, vid) == first and len(runs) == 1  # the Battery page asks every 30 s
    analytics.projected_range(conn, vid, tz_offset=-60)  # another viewer's days are another answer
    assert len(runs) == 2
    _ranges(conn, vid, 1, lambda d: 505, first=3)
    assert analytics.projected_range(conn, vid)["latest"]["range_km"] == 505.0 and len(runs) == 3


# ---------------------------------------------------------------- endpoints

def test_insight_routes_answer_without_calling_skoda():
    c, conn, api, vid = connected()
    _charge(conn, vid, "2027-03-01T10:00:00+00:00")
    _trip(conn, vid, "2027-03-01T07:00:00+00:00")
    calls = len(api.calls)
    ledger = conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
    q = "from=2027-03-01&to=2027-03-31&tz_offset=-60"
    ch = c.get(f"/api/vehicles/{vid}/insights/charging?{q}")
    dr = c.get(f"/api/vehicles/{vid}/insights/driving?{q}")
    assert ch.status_code == dr.status_code == 200
    assert ch.json()["totals"]["sessions"] == 1 and ch.json()["currency"] == "EUR"
    assert dr.json()["totals"]["trips"] == 1
    assert c.get(f"/api/vehicles/{vid}/insights/charging?to=2027-02-28").json()["totals"]["sessions"] == 0
    bat = c.get(f"/api/vehicles/{vid}/battery?tz_offset=-60").json()
    assert bat["projected_range"]["samples"] >= 1
    assert len(api.calls) == calls and conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0] == ledger


@pytest.mark.parametrize("kind", ["charging", "driving"])
def test_insight_routes_reject_bad_ranges_unknown_cars_and_strangers(kind):
    c, conn, api, vid = connected()
    url = f"/api/vehicles/{vid}/insights/{kind}"
    bad = c.get(f"{url}?from=yesterday")
    assert bad.status_code == 400 and "expected YYYY-MM-DD" in bad.json()["detail"]
    reversed_ = c.get(f"{url}?from=2027-03-02&to=2027-03-01")
    assert reversed_.status_code == 400 and reversed_.json()["detail"] == "The range ends before it starts."
    assert c.get(f"{url}?from=2027-03-01&to=2027-03-01").status_code == 200
    assert c.get(f"{url}?tz_offset=99999").status_code == 422
    assert c.get(f"/api/vehicles/999/insights/{kind}").status_code == 404
    c.cookies.clear()
    assert c.get(url).status_code == 401
