"""SQLite schema. Imports nothing from the rest of the app (web and poller both use it).

`migrate()` is additive and idempotent: new tables via CREATE IF NOT EXISTS, new columns via
`EXTRA_COLUMNS`, so a database from an older version upgrades in place and nothing is ever dropped.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY, vin TEXT UNIQUE NOT NULL, name TEXT, model TEXT,
    battery_kwh REAL, created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    recorded_at TEXT NOT NULL, soc REAL, range_km REAL,
    charging INTEGER DEFAULT 0, charge_power_kw REAL, charge_type TEXT, charge_state TEXT,
    target_soc REAL, remaining_min INTEGER,
    locked INTEGER, doors_open INTEGER, windows_open INTEGER, trunk_open INTEGER,
    climate_state TEXT, lat REAL, lon REAL
);
CREATE INDEX IF NOT EXISTS idx_snap_v_t ON snapshots(vehicle_id, recorded_at);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    cloud_id TEXT NOT NULL, started_at TEXT, ended_at TEXT, distance_km REAL, duration_min INTEGER,
    avg_speed_kmh REAL, avg_kwh_100km REAL, energy_kwh REAL,
    start_soc REAL, end_soc REAL, start_place TEXT, end_place TEXT, note TEXT,
    UNIQUE(vehicle_id, cloud_id)
);
CREATE INDEX IF NOT EXISTS idx_trips_v_t ON trips(vehicle_id, started_at);
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    started_at TEXT NOT NULL, ended_at TEXT, start_soc REAL, end_soc REAL,
    energy_kwh REAL DEFAULT 0, max_power_kw REAL DEFAULT 0, charge_type TEXT,
    lat REAL, lon REAL, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_charges_v_t ON charges(vehicle_id, started_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_v_t ON events(vehicle_id, at);
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER, at TEXT DEFAULT (datetime('now')),
    name TEXT NOT NULL, ok INTEGER NOT NULL, error TEXT
);
-- Latest normalised copy of each slow-changing cloud section (info, ac, maintenance, health, ...).
CREATE TABLE IF NOT EXISTS vehicle_state (
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id), key TEXT NOT NULL,
    json TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (vehicle_id, key)
);
-- Every cloud request, so the 20-per-hour budget survives restarts and can be shown.
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER, at REAL NOT NULL, endpoint TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_calls_at ON api_calls(at);
-- Cloud confirmation of remote operations (MQTT operation events).
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY, vehicle_id INTEGER, request_id TEXT UNIQUE, name TEXT NOT NULL,
    status TEXT NOT NULL, error_code TEXT, at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

# table -> {column: sql type}. Added when missing (older databases).
EXTRA_COLUMNS: dict[str, dict[str, str]] = {
    "snapshots": {
        "charging_rate_kmh": "REAL", "bonnet_open": "INTEGER", "sunroof_open": "INTEGER", "lights_on": "INTEGER",
        "climate_target": "REAL", "outside_temp": "REAL", "plug_connected": "INTEGER", "plug_locked": "INTEGER",
        "mileage_km": "REAL", "fuel_pct": "REAL", "fuel_range_km": "REAL", "address": "TEXT",
        "in_motion": "INTEGER", "ignition_on": "INTEGER", "reachable": "INTEGER", "battery_protection": "INTEGER",
        "doors_json": "TEXT", "captured_at": "TEXT",
        "aux_state": "TEXT", "vent_state": "TEXT", "fully_charged_at": "TEXT", "park_captured_at": "TEXT",
    },
    "trips": {
        # Trips are derived by Mate (the official API has no trip data): odometer + PARKED/IN_MOTION snapshots.
        "route_json": "TEXT", "cost": "REAL", "fuel_l_100km": "REAL", "recup_kwh_100km": "REAL",
        "aux_kwh_100km": "REAL", "short_trip": "INTEGER", "start_lat": "REAL", "start_lon": "REAL",
        "end_lat": "REAL", "end_lon": "REAL", "odo_start": "REAL", "odo_end": "REAL",
        "approx": "INTEGER DEFAULT 0",  # 1 = found from an odometer jump between two parked snapshots
        "energy_basis": "TEXT",  # how energy_kwh was obtained (soc_delta | fuel | none)
        "start_fuel_pct": "REAL", "end_fuel_pct": "REAL",
        # Provenance and the extra figures of the app's CSV export (see importer.py)
        "source": "TEXT", "driving_min": "INTEGER", "public_stops": "INTEGER", "public_soc_gained": "REAL",
        "merged_json": "TEXT",  # the trips this one was merged from (kept so a merge can be undone and a re-import does not re-add them)
    },
    "commands": {"params": "TEXT", "http_status": "INTEGER", "kind": "TEXT", "source": "TEXT"},
    "charges": {
        "source": "TEXT DEFAULT 'detected'", "cost": "REAL", "cost_manual": "REAL", "place_kind": "TEXT",
        "duration_min": "INTEGER", "address": "TEXT", "target_soc": "REAL",
        "energy_battery_kwh": "REAL",  # soc delta x battery capacity: what reached the pack
    },
}


class _Result:
    """A fully fetched result, so nothing touches the shared connection after the lock is released."""

    def __init__(self, rows, lastrowid, description, rowcount):
        self._rows, self.lastrowid, self.description, self.rowcount = rows, lastrowid, description, rowcount
        self._i = 0

    def fetchall(self):
        rows, self._rows = self._rows[self._i:], []
        self._i = 0
        return rows

    def fetchone(self):
        if self._i < len(self._rows):
            self._i += 1
            return self._rows[self._i - 1]
        return None

    def __iter__(self):
        return iter(self.fetchall())


class SafeConnection:
    """One SQLite connection shared by the poller (event-loop thread) and FastAPI's worker threads.

    The sqlite3 module raises "bad parameter or other API misuse" when two threads use one connection at once, so every
    call takes a lock and results are fetched before it is released. Statements are tiny and local; this costs nothing
    noticeable and removes a class of rare, hard-to-reproduce failures.
    """

    def __init__(self, path: str):
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def execute(self, sql, params=()):
        with self._lock:
            cur = self._c.execute(sql, params)
            return _Result(cur.fetchall() if cur.description else [], cur.lastrowid, cur.description, cur.rowcount)

    def executescript(self, sql):
        with self._lock:
            self._c.executescript(sql)

    def commit(self):
        with self._lock:
            self._c.commit()

    def rollback(self):
        with self._lock:
            self._c.rollback()

    def backup(self, dst):
        with self._lock:
            self._c.backup(dst)

    def close(self):
        with self._lock:
            self._c.close()


def connect(path: str) -> SafeConnection:
    on_disk = path != ":memory:" and not path.startswith("file:")
    if on_disk:
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)  # only a directory Mate creates gets 0700
    conn = SafeConnection(path)
    conn.execute("PRAGMA journal_mode=WAL")
    migrate(conn)
    if on_disk:
        make_private(path)
    return conn


def make_private(path: str) -> None:
    """chmod the database (and its WAL/SHM files) to 0600 when group or others can read it. Best effort: a volume
    owned by someone else, or Windows, may refuse; the app works either way."""
    for p in (path, f"{path}-wal", f"{path}-shm"):
        try:
            if os.stat(p).st_mode & 0o077:
                os.chmod(p, 0o600)
        except OSError:
            pass


def migrate(conn) -> None:
    conn.executescript(SCHEMA)
    for table, cols in EXTRA_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    dedupe_trips(conn)
    conn.commit()


def dedupe_trips(conn) -> int:
    """Remove trips that are the same drive stored twice. Returns how many rows were removed.

    The old private API gave the same drive a new id on a later fetch and the old importer de-duplicated by id only, so
    some databases hold two rows with identical vehicle, start and end (to the millisecond). That double-counts the
    drive in every total. The oldest row is kept; a note on a removed copy is carried over if the kept row has none."""
    dupes = conn.execute(
        "SELECT vehicle_id, started_at, ended_at, MIN(id) keep FROM trips WHERE started_at IS NOT NULL AND ended_at IS NOT NULL "
        "GROUP BY vehicle_id, started_at, ended_at HAVING COUNT(*) > 1").fetchall()
    removed = 0
    for d in dupes:
        note = conn.execute("SELECT note FROM trips WHERE vehicle_id=? AND started_at=? AND ended_at=? AND note IS NOT NULL AND note!='' LIMIT 1",
                            (d["vehicle_id"], d["started_at"], d["ended_at"])).fetchone()
        if note:
            conn.execute("UPDATE trips SET note=COALESCE(NULLIF(note,''), ?) WHERE id=?", (note["note"], d["keep"]))
        cur = conn.execute("DELETE FROM trips WHERE vehicle_id=? AND started_at=? AND ended_at=? AND id!=?",
                           (d["vehicle_id"], d["started_at"], d["ended_at"], d["keep"]))
        removed += cur.rowcount
    return removed
