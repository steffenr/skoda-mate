import pytest

from skoda_mate import importer, places, recorder, schema

from .fixtures import VIN
from .test_web import connected

HEADER = ('"Start of trip","End of trip","Classification","Start address","End address","Start coordinates","End coordinates",'
          '"Distance in km","Start odometer in km","End odometer in km","Driving time in minutes","Travel time in minutes",'
          '"Average speed in km/h","Electricity consumption in kWh","Average electricity consumption in kWh/100km",'
          '"Start SoC in %","End SoC in %","Public charging stops","Public charge SoC gained in %","Short trip"')
HOME, WORK = '"Home St 1, 12345 Town, Germany"', '"Work Rd 2, 12345 City, Germany"'

A = f'"01.07.2026 08:00","01.07.2026 08:30","",{HOME},{WORK},"50.1,8.6","50.2,8.7","30","1000","1030","28","30","60","6.0","20.0","80","70","0","0","false"'
B = f'"01.07.2026 17:00","01.07.2026 17:35","",{WORK},{HOME},"50.2,8.7","50.1,8.6","30","1030","1060","30","35","51","6.0","20.0","70","60","0","0","false"'
ZERO = f'"02.07.2026 07:59","02.07.2026 10:54","","",{HOME},"","50.1,8.6","0","","1060","40","175","0","3.85","","76","71","0","0","true"'
D = f'"05.07.2026 09:00","05.07.2026 12:00","",{HOME},{WORK},"50.1,8.6","50.2,8.7","200","1060","1260","150","180","80","40.0","20.0","90","30","2","80","false"'
E = '"06.07.2026 08:00","06.07.2026 08:12","","","","","","6","1260","1266","10","12","30","1.5","","90","88","0","0","true"'

# The PHEV export of the MyŠkoda app (issue #11): no start time, no addresses, no SoC; mileage and fuel instead.
PHEV_HEADER = ('"End of trip","Start mileage in km","End mileage in km","Mileage in km","Travel time in minutes",'
               '"Average speed in km/h","Total cost","Total cost currency","Average electric consumption in kWh/100km",'
               '"Electricity cost","Electricity cost currency","Electricity price per kWh",'
               '"Average auxiliary consumption in kWh/100km","Average recuperation in kWh/100km",'
               '"Average fuel consumption in l/100km","Fuel cost","Fuel cost currency","Fuel price per litre"')
PHEV_E = ('"25.11.2026 15:00","3984","3990","6","16","24","0.69","EUR","42.9","0.69","EUR","0.27","","","0.0","0.0",'
          '"EUR","1.919"')
PHEV_H = ('"15.11.2026 21:19","3851","3911","60","46","79","5.53","EUR","11.4","1.85","EUR","0.27","","","3.2","3.68",'
          '"EUR","1.919"')
PHEV_FREE = ('"01.11.2026 10:00","3000","3030","30","20","90","","","15.0","","","","","","","","",""')


def csv(*rows):
    return HEADER + "\n" + "\n".join(rows) + "\n"


def phev(*rows):
    return PHEV_HEADER + "\n" + "\n".join(rows) + "\n"


def f(name, text):
    return {"name": name, "text": text}


def setup(kwh=77.0):
    conn = schema.connect(":memory:")
    vid = recorder.upsert_vehicle(conn, VIN, "Enyaq", None, kwh)
    return conn, vid


def run(conn, vid, files, tz="Europe/Berlin", dry=False):
    return importer.run(conn, vid, VIN, files, tz, dry)


def trips(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM trips ORDER BY started_at")]


# ------------------------------------------------------------------ parsing
def test_parsing_times_numbers_coordinates_and_edge_rows():
    rows, rep = importer.parse_file("tripStatistics_x.csv", csv(A, ZERO, E, D), importer.get_tz("Europe/Berlin"))
    assert rep.rows == 4 and rep.parsed == 3 and rep.skipped_no_distance == 1 and not rep.errors  # the 0 km row is not a trip
    a = rows[0]
    assert a["start"].isoformat() == "2026-07-01T06:00:00+00:00"  # CEST (UTC+2): 08:00 local
    assert (a["distance_km"], a["energy_kwh"], a["avg_kwh_100km"], a["start_soc"], a["end_soc"]) == (30, 6.0, 20.0, 80, 70)
    assert (a["start_lat"], a["start_lon"], a["odo_start"], a["odo_end"]) == (50.1, 8.6, 1000, 1030)
    assert a["start_place"].startswith("Home St 1") and a["short_trip"] == 0
    e = [r for r in rows if r["distance_km"] == 6][0]  # blank address / coordinates / consumption
    assert e["start_place"] is None and e["start_lat"] is None and e["short_trip"] == 1 and e["avg_kwh_100km"] == 25.0  # computed 1.5/6*100
    d = [r for r in rows if r["distance_km"] == 200][0]
    assert d["public_stops"] == 2 and d["public_soc_gained"] == 80
    winter, _ = importer.parse_file("x.csv", csv(A.replace("01.07.2026", "23.11.2026")), importer.get_tz("Europe/Berlin"))
    assert winter[0]["start"].isoformat() == "2026-11-23T07:00:00+00:00"  # CET (UTC+1): the DST switch is handled


def test_german_style_export_semicolons_decimal_commas_and_bom():
    de = ("﻿" + HEADER.replace('","', '";"') + "\n"
          '"01.07.2026 08:00";"01.07.2026 08:30";"";"Home";"Work";"50,1;8,6";"50,2;8,7";"30";"1000";"1030";"28";"30";"60";"6,5";"21,7";"80";"70";"0";"0";"false"\n')
    rows, rep = importer.parse_file("x.csv", de, importer.get_tz("Europe/Berlin"))
    assert not rep.errors and rows[0]["energy_kwh"] == 6.5 and rows[0]["avg_kwh_100km"] == 21.7 and (rows[0]["start_lat"], rows[0]["start_lon"]) == (50.1, 8.6)


def test_unusable_files_are_reported_not_crashed_on():
    rows, rep = importer.parse_file("x.csv", "name,age\nbob,3\n", importer.get_tz("UTC"))
    assert rows == [] and "does not look like a MyŠkoda trip export" in rep.errors[0]
    assert importer.parse_file("x.csv", "", importer.get_tz("UTC"))[1].errors == ["The file is empty."]
    bad = csv(A.replace('"01.07.2026 08:00"', '"yesterday"'), B.replace('"01.07.2026 17:35"', '"01.07.2026 16:00"'))
    rows, rep = importer.parse_file("x.csv", bad, importer.get_tz("UTC"))
    assert rows == [] and len(rep.errors) == 2 and "unreadable date" in rep.errors[0] and "ends before it starts" in rep.errors[1]
    with pytest.raises(importer.ImportError_, match="time zone"):
        importer.get_tz("Mars/Olympus")


# ------------------------------------------------------------------ the PHEV export layout (#11)
def test_the_phev_layout_is_detected_from_its_header_and_mapped():
    rows, rep = importer.parse_file("tripStatistics_x.csv", phev(PHEV_E, PHEV_H), importer.get_tz("Europe/Berlin"))
    assert not rep.errors and rep.rows == 2 and rep.parsed == 2
    e, h = rows
    # CET: 15:00 local ends the trip, 16 minutes of travel time give the start (there is no start column)
    assert (e["end"].isoformat(), e["start"].isoformat()) == ("2026-11-25T14:00:00+00:00", "2026-11-25T13:44:00+00:00")
    assert (e["distance_km"], e["odo_start"], e["odo_end"], e["duration_min"], e["avg_speed_kmh"]) == (6, 3984, 3990, 16, 24)
    assert (e["avg_kwh_100km"], e["energy_kwh"]) == (42.9, 2.57)  # kWh = 42.9 * 6 / 100
    assert (e["cost"], e["fuel_l_100km"], e["aux_kwh_100km"], e["recup_kwh_100km"]) == (0.69, 0.0, None, None)
    assert e["start_place"] is None and e["start_soc"] is None and e["short_trip"] == 0  # not in this layout
    assert (h["start"].isoformat(), h["end"].isoformat()) == ("2026-11-15T19:33:00+00:00", "2026-11-15T20:19:00+00:00")
    assert (h["distance_km"], h["duration_min"], h["avg_speed_kmh"]) == (60, 46, 79)
    assert (h["fuel_l_100km"], h["cost"], h["energy_kwh"]) == (3.2, 5.53, 6.84)  # the hybrid trip also stored petrol
    rounded = PHEV_E.replace('"3984","3990","6"', '"3984","3990","5.6"')
    rows, _ = importer.parse_file("x.csv", phev(rounded), importer.get_tz("Europe/Berlin"))
    assert rows[0]["distance_km"] == 5.6  # "Mileage in km" wins over the rounded end-minus-start difference


def test_a_derived_phev_start_crosses_midnight_and_the_dst_switch():
    midnight = ('"01.08.2026 00:10","100","130","30","30","60","1.00","EUR","10.0","1.00","EUR","0.27","","","0.0","0.0",'
                '"EUR","1.919"')
    rows, rep = importer.parse_file("x.csv", phev(midnight), importer.get_tz("Europe/Berlin"))
    assert not rep.errors and rows[0]["start"].isoformat() == "2026-07-31T21:40:00+00:00"  # 23:40 CEST the day before
    dst = midnight.replace("01.08.2026 00:10", "25.10.2026 03:10")
    rows, rep = importer.parse_file("x.csv", phev(dst), importer.get_tz("Europe/Berlin"))
    # 03:10 CET is 02:10 UTC; 30 minutes earlier (02:40 CET) is across the switch at 01:00 UTC
    assert not rep.errors and rows[0]["start"].isoformat() == "2026-10-25T01:40:00+00:00"
    assert rows[0]["end"].isoformat() == "2026-10-25T02:10:00+00:00"


def test_the_phev_export_imports_fuel_and_cost_and_keeps_empty_cost_fields():
    conn, vid = setup()
    text = phev(PHEV_E, PHEV_H, PHEV_FREE) + "\n\n"  # the real file ends with two empty lines
    preview = run(conn, vid, [f("tripStatistics_x.csv", text)], dry=True)
    assert preview["new"] == 3 and trips(conn) == []  # the preview writes nothing
    done = run(conn, vid, [f("tripStatistics_x.csv", text)])
    assert (done["new"], done["skipped_no_distance"], done["files"][0]["parsed"]) == (3, 0, 3)
    assert done["km"] == 96.0
    by_km = {t["distance_km"]: t for t in trips(conn)}
    assert set(by_km) == {6, 30, 60}
    h = by_km[60]
    assert (h["fuel_l_100km"], h["cost"], h["avg_kwh_100km"], h["energy_kwh"]) == (3.2, 5.53, 11.4, 6.84)
    assert h["aux_kwh_100km"] is None and h["recup_kwh_100km"] is None  # empty in every row
    free = by_km[30]  # all cost/price/currency fields empty, still a trip
    assert free["cost"] is None and free["fuel_l_100km"] is None and free["energy_kwh"] == 4.5
    snapshot = trips(conn)
    again = run(conn, vid, [f("tripStatistics_x.csv", text)])
    assert (again["new"], again["unchanged"]) == (0, 3)
    assert trips(conn) == snapshot


def test_a_phev_row_enriches_an_english_trip_without_clearing_what_only_that_export_has():
    conn, vid = setup()
    run(conn, vid, [f("english.csv", csv(A))])
    phev_a = ('"01.07.2026 08:30","1000","1030","30","30","60","1.50","EUR","20.0","1.50","EUR","0.27","","","0.0","0.0",'
              '"EUR","1.919"')
    r = run(conn, vid, [f("phev.csv", phev(phev_a))])
    assert (r["new"], r["updated"]) == (0, 1) and len(trips(conn)) == 1
    t = trips(conn)[0]
    assert (t["started_at"], t["ended_at"]) == ("2026-07-01T06:00:00+00:00", "2026-07-01T06:30:00+00:00")  # derived start matches
    assert (t["cost"], t["start_soc"], t["end_soc"]) == (1.5, 80, 70)  # new column added, absent values kept
    assert t["start_place"].startswith("Home St 1") and t["driving_min"] == 28


def test_a_166_row_phev_export_parses_every_row():
    rows = []
    for i in range(166):
        day, month = 1 + i % 28, 1 + i // 28
        rows.append(f'"{day:02d}.{month:02d}.2026 15:00","1000","1006","6","16","24","0.69","EUR","42.9","0.69","EUR",'
                    f'"0.27","","","0.0","0.0","EUR","1.919"')
    parsed, rep = importer.parse_file("tripStatistics_x.csv", phev(*rows) + "\n\n", importer.get_tz("Europe/Berlin"))
    assert not rep.errors and rep.rows == 166 and rep.parsed == 166
    assert len({r["start"] for r in parsed}) == 166  # newest-first order needs no sorting to parse


# ------------------------------------------------------------------ duplicates (the point of the exercise)
def test_a_dry_run_writes_nothing():
    conn, vid = setup()
    r = run(conn, vid, [f("t.csv", csv(A, B))], dry=True)
    assert r["dry_run"] and r["new"] == 2 and trips(conn) == [] and conn.execute("SELECT COUNT(*) FROM charges").fetchone()[0] == 0


def test_importing_the_same_file_twice_adds_nothing_the_second_time():
    conn, vid = setup()
    first = run(conn, vid, [f("t.csv", csv(A, B, D))])
    assert (first["new"], first["unchanged"], first["updated"]) == (3, 0, 0) and len(trips(conn)) == 3
    snapshot = trips(conn)
    second = run(conn, vid, [f("t.csv", csv(A, B, D))])
    assert (second["new"], second["unchanged"], second["updated"]) == (0, 3, 0)
    assert trips(conn) == snapshot  # not a single column changed
    assert conn.execute("SELECT COUNT(*) FROM charges WHERE source='import-trip'").fetchone()[0] == 1  # the public charge too


def test_overlapping_files_in_one_upload_count_each_trip_once():
    """The full export plus a range export (or two ranges sharing a boundary day) repeat trips."""
    conn, vid = setup()
    r = run(conn, vid, [f("full.csv", csv(A, B, D)), f("range.csv", csv(B, D, E))])
    assert r["unique"] == 4 and r["duplicates_in_upload"] == 2 and r["new"] == 4 and len(trips(conn)) == 4


def test_a_later_overlapping_import_only_adds_what_is_new():
    conn, vid = setup()
    run(conn, vid, [f("april_july.csv", csv(A, B))])
    r = run(conn, vid, [f("july_on.csv", csv(B, D, E))])
    assert (r["new"], r["unchanged"]) == (2, 1) and len(trips(conn)) == 4


def test_a_trip_mate_already_has_is_enriched_not_duplicated_and_keeps_its_note():
    conn, vid = setup()
    # what the old cloud importer stored: exact seconds, no odometer, a user note
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,energy_kwh,start_soc,end_soc,note) VALUES(?,?,?,?,?,?,?,?,?)",
                 (vid, "01a207a9-cloud", "2026-07-01T06:00:44.974000+00:00", "2026-07-01T06:30:06.972000+00:00", 30.0, 6.0, 80, 70, "to work"))
    conn.commit()
    r = run(conn, vid, [f("t.csv", csv(A))])
    assert r["new"] == 0 and len(trips(conn)) == 1
    t = trips(conn)[0]
    assert t["note"] == "to work" and t["started_at"] == "2026-07-01T06:00:44.974000+00:00"  # the user's note and the exact time are kept
    assert (t["odo_start"], t["odo_end"], t["source"], t["energy_basis"]) == (1000, 1030, "import", "car")  # the car's own figures added
    assert run(conn, vid, [f("t.csv", csv(A))])["unchanged"] == 1  # and now it is stable


def test_a_derived_trip_is_matched_by_its_odometer_and_gets_the_exact_times():
    conn, vid = setup()
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km,odo_start,odo_end,approx) VALUES(?,?,?,?,?,?,?,1)",
                 (vid, "odo-x", "2026-07-01T05:35:00+00:00", "2026-07-01T06:30:00+00:00", 30.0, 1000, 1030))  # start estimated 25 min early
    conn.commit()
    r = run(conn, vid, [f("t.csv", csv(A))])
    assert r["new"] == 0 and r["updated"] == 1 and len(trips(conn)) == 1
    t = trips(conn)[0]
    assert t["started_at"] == "2026-07-01T06:00:00+00:00" and t["approx"] == 0  # Mate's estimate replaced by the export's exact time


def test_distinct_trips_are_never_merged_and_a_stored_trip_matches_only_once():
    conn, vid = setup()
    conn.execute("INSERT INTO trips(vehicle_id,cloud_id,started_at,ended_at,distance_km) VALUES(?,?,?,?,?)",
                 (vid, "x", "2026-07-01T06:00:00+00:00", "2026-07-01T06:30:00+00:00", 30.0))
    conn.commit()
    twin = A.replace("08:00", "08:01").replace("08:30", "08:31").replace('"1000","1030"', '"1000","1031"').replace('"30","1000"', '"31","1000"')
    r = run(conn, vid, [f("t.csv", csv(A, twin, B))])  # two rows near one stored trip + one clearly different trip
    assert (r["new"], r["unchanged"] + r["updated"]) == (2, 1) and len(trips(conn)) == 3


def test_another_cars_export_is_refused():
    conn, vid = setup()
    r = run(conn, vid, [f("tripStatistics_TMBXXXXXXXXXXXXXX.csv", csv(A)), f(f"tripStatistics_{VIN}.csv", csv(B))])
    assert r["new"] == 1 and "another car" in r["files"][0]["errors"][0] and len(trips(conn)) == 1


# ------------------------------------------------------------------ what the import adds
def test_public_charging_stops_become_one_charge_and_overnight_charges_are_inferred():
    conn, vid = setup(kwh=77.0)
    next_day_high = B.replace("01.07.2026 17:00", "02.07.2026 17:00").replace("01.07.2026 17:35", "02.07.2026 17:35").replace('"70","60"', '"95","85"').replace('"1030","1060"', '"1030","1060"')
    r = run(conn, vid, [f("t.csv", csv(A, next_day_high, D))])
    assert r["public_charges"] == 1 and r["charges_inferred"] >= 1
    pub = conn.execute("SELECT * FROM charges WHERE source='import-trip'").fetchone()
    assert pub["place_kind"] == "public" and abs(pub["energy_battery_kwh"] - 80 * 77 / 100) < 0.01 and "2 stop" in pub["note"]
    over = conn.execute("SELECT * FROM charges WHERE source='inferred'").fetchone()
    assert over["start_soc"] == 70 and over["end_soc"] == 95  # A ended at 70 %, the next trip started at 95 %: charged overnight


def test_without_battery_capacity_energy_is_unknown_but_nothing_breaks():
    conn, vid = setup(kwh=None)
    r = run(conn, vid, [f("t.csv", csv(D))])
    assert r["new"] == 1 and conn.execute("SELECT energy_kwh FROM charges WHERE source='import-trip'").fetchone()[0] is None


def test_an_imported_trip_is_linked_to_the_places_it_touched():
    conn, vid = setup()
    home = places.create(conn, {"name": "Home", "kind": "home", "lat": 50.1, "lon": 8.6, "radius_m": 150})
    work = places.create(conn, {"name": "Work", "kind": "work", "lat": 50.2, "lon": 8.7, "radius_m": 150})
    run(conn, vid, [f("t.csv", csv(A))])
    t = trips(conn)[0]
    assert (t["start_geofence_id"], t["end_geofence_id"]) == (home["id"], work["id"])


# ------------------------------------------------------------------ through the API
def test_api_preview_then_import_and_validation():
    c, conn, api, vid = connected()
    files = [f(f"tripStatistics_{VIN}.csv", csv(A, B, ZERO, D))]
    p = c.post(f"/api/vehicles/{vid}/import/trips", json={"files": files, "tz": "Europe/Berlin"}).json()  # dry_run defaults to true
    assert p["dry_run"] and p["new"] == 3 and p["skipped_no_distance"] == 1 and p["unique"] == 3
    assert conn.execute("SELECT COUNT(*) FROM trips WHERE source='import'").fetchone()[0] == 0  # the preview wrote nothing
    done = c.post(f"/api/vehicles/{vid}/import/trips", json={"files": files, "tz": "Europe/Berlin", "dry_run": False}).json()
    assert not done["dry_run"] and done["new"] == 3 and done["km"] == 260.0 and done["files"][0]["parsed"] == 3
    again = c.post(f"/api/vehicles/{vid}/import/trips", json={"files": files, "tz": "Europe/Berlin", "dry_run": False}).json()
    assert again["new"] == 0 and again["unchanged"] == 3
    listed = c.get(f"/api/vehicles/{vid}/trips?from=2026-07-01&to=2026-07-31").json()
    assert listed["total"] == 3 and listed["items"][0]["energy_kwh"] == 40.0
    ch = c.get(f"/api/vehicles/{vid}/charges").json()["items"]
    assert any(x["inferred"] and x["place_kind_resolved"] == "public" for x in ch)  # shown as inferred, not as a measured charge
    assert c.post(f"/api/vehicles/{vid}/import/trips", json={"files": files, "tz": "Mars/Olympus"}).status_code == 400
    assert c.post(f"/api/vehicles/{vid}/import/trips", json={"files": [], "tz": "UTC"}).status_code == 400
    assert c.post(f"/api/vehicles/{vid}/import/trips", json={"files": [f("a.csv", "x")] * 13, "tz": "UTC"}).status_code == 400
    c.cookies.clear()
    assert c.post(f"/api/vehicles/{vid}/import/trips", json={"files": files}).status_code == 401  # needs a session


def test_an_imported_charge_exposes_its_trips_route_for_the_map():
    c, conn, api, vid = connected()
    c.post(f"/api/vehicles/{vid}/import/trips", json={"files": [f(f"tripStatistics_{VIN}.csv", csv(D))], "tz": "Europe/Berlin", "dry_run": False})
    cid = conn.execute("SELECT id FROM charges WHERE source='import-trip'").fetchone()[0]
    ch = c.get(f"/api/vehicles/{vid}/charges/{cid}").json()
    tr = ch["trip_route"]
    assert (tr["start_lat"], tr["end_lat"]) == (50.1, 50.2) and tr["id"] and ch["lat"] is None
    assert ch["soc_gained"] == 80 and ch["start_soc"] is None  # only the rise is known, never invented levels
    other = conn.execute("INSERT INTO charges(vehicle_id,started_at,source) VALUES(?,?,'detected')", (vid, "2027-01-01T00:00:00+00:00")).lastrowid
    assert c.get(f"/api/vehicles/{vid}/charges/{other}").json()["trip_route"] is None
