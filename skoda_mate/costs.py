"""Prices. The official API reports no costs, so charge and trip costs are computed here from a tariff
the user sets (Settings). Manual overrides always win, and every figure says it is an estimate."""
from __future__ import annotations

import json
import math
from contextlib import suppress

from .store import get_setting

DEFAULT_TARIFF = {"currency": "EUR", "home_kwh": 0.30, "public_ac_kwh": 0.55, "public_dc_kwh": 0.79,
                  "home_lat": None, "home_lon": None, "home_radius_m": 150}


def load_tariff(conn) -> dict:
    t = dict(DEFAULT_TARIFF)
    with suppress(ValueError, TypeError):
        t.update({k: v for k, v in json.loads(get_setting(conn, "tariff", "{}")).items() if k in DEFAULT_TARIFF})
    return t


def clean_tariff(raw: dict) -> dict:
    """Validate user input; raises ValueError with a message the dashboard can show."""
    out: dict = {}
    for k in ("home_kwh", "public_ac_kwh", "public_dc_kwh"):
        if k in raw and raw[k] not in (None, ""):
            v = float(raw[k])
            if not 0 <= v <= 10:
                raise ValueError(f"{k} must be between 0 and 10 per kWh")
            out[k] = v
    if raw.get("currency"):
        cur = str(raw["currency"]).strip().upper()
        if not 1 <= len(cur) <= 4:
            raise ValueError("currency must be a short code such as EUR")
        out["currency"] = cur
    for k in ("home_lat", "home_lon"):
        if k in raw:
            out[k] = None if raw[k] in (None, "") else float(raw[k])
    if "home_radius_m" in raw and raw["home_radius_m"] not in (None, ""):
        r = int(raw["home_radius_m"])
        if not 20 <= r <= 5000:
            raise ValueError("home radius must be 20-5000 m")
        out["home_radius_m"] = r
    return out


def distance_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def place_kind(charge: dict, tariff: dict) -> str:
    """'home' / 'public' (manual choice wins), else guessed: DC is public; AC next to the home position is home."""
    if charge.get("place_kind") in ("home", "public"):
        return charge["place_kind"]
    if charge.get("charge_type") == "DC":
        return "public"
    if None not in (tariff.get("home_lat"), tariff.get("home_lon"), charge.get("lat"), charge.get("lon")):
        near = distance_m(tariff["home_lat"], tariff["home_lon"], charge["lat"], charge["lon"]) <= tariff["home_radius_m"]
        return "home" if near else "public"
    return "unknown"


def charge_cost(charge: dict, tariff: dict) -> dict:
    """-> {amount, kind, basis} where basis is manual | tariff | none."""
    kind = place_kind(charge, tariff)
    if charge.get("cost_manual") is not None:
        return {"amount": charge["cost_manual"], "kind": kind, "basis": "manual"}
    kwh = charge.get("energy_kwh")
    if not kwh:
        return {"amount": None, "kind": kind, "basis": "none"}
    if kind == "home":
        price = tariff["home_kwh"]
    elif kind == "public":
        price = tariff["public_dc_kwh"] if charge.get("charge_type") == "DC" else tariff["public_ac_kwh"]
    else:  # unknown place: assume the home price, flagged in `basis`
        price = tariff["home_kwh"]
    return {"amount": round(kwh * price, 2), "kind": kind, "basis": "tariff" if kind != "unknown" else "tariff-guess"}


def trip_cost(trip: dict, tariff: dict) -> float | None:
    return None if not trip.get("energy_kwh") else round(trip["energy_kwh"] * tariff["home_kwh"], 2)
