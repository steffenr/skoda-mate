"""Storage helpers: the key/value `settings` table, the latest copy of each API section and the request ledger."""
from __future__ import annotations

import json
from typing import overload


def save_sections(conn, vid: int, sections: dict, at: str) -> None:
    for key, obj in sections.items():
        conn.execute("INSERT INTO vehicle_state(vehicle_id,key,json,fetched_at) VALUES(?,?,?,?) "
                     "ON CONFLICT(vehicle_id,key) DO UPDATE SET json=excluded.json, fetched_at=excluded.fetched_at",
                     (vid, key, json.dumps(obj), at))


def delete_section(conn, vid: int, key: str) -> None:
    conn.execute("DELETE FROM vehicle_state WHERE vehicle_id=? AND key=?", (vid, key))


def load_sections(conn, vid: int) -> dict:
    return {r["key"]: json.loads(r["json"]) for r in
            conn.execute("SELECT key,json FROM vehicle_state WHERE vehicle_id=?", (vid,))}


def section_times(conn, vid: int) -> dict:
    return {r["key"]: r["fetched_at"] for r in
            conn.execute("SELECT key,fetched_at FROM vehicle_state WHERE vehicle_id=?", (vid,))}


def log_call(conn, vid: int | None, at: float, endpoint: str, ok: bool, error: str | None = None) -> None:
    conn.execute("INSERT INTO api_calls(vehicle_id,at,endpoint,ok,error) VALUES(?,?,?,?,?)",
                 (vid, at, endpoint, int(ok), error))
    conn.execute("DELETE FROM api_calls WHERE at < ?", (at - 7 * 86400,))  # a week is plenty for diagnostics
    conn.commit()


def recent_calls(conn, vid: int | None, since: float) -> list[float]:
    q, args = "SELECT at FROM api_calls WHERE at>=?", [since]
    if vid is not None:
        q, args = q + " AND vehicle_id=?", args + [vid]
    return [r["at"] for r in conn.execute(q, args)]


@overload
def get_setting(conn, key: str, default: str) -> str: ...


@overload
def get_setting(conn, key: str, default: None = None) -> str | None: ...


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()


def del_setting(conn, *keys: str) -> None:
    for k in keys:
        conn.execute("DELETE FROM settings WHERE key=?", (k,))
    conn.commit()


def int_setting(conn, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(get_setting(conn, key, str(default)))))
    except (TypeError, ValueError):
        return default
