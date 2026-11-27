"""Prices. The official API reports no costs, so charge and trip costs are computed here from a tariff
the user sets (Settings) and, for a charge, the rate of its place. Manual overrides always win, and every figure
says it is an estimate."""
from __future__ import annotations

import json
import math
from contextlib import suppress

from . import messages
from .store import get_setting

DEFAULT_TARIFF = {"currency": "EUR", "home_kwh": 0.30, "public_ac_kwh": 0.55, "public_dc_kwh": 0.79,
                  "home_lat": None, "home_lon": None, "home_radius_m": 150}

# A place may set its own rate; any price field being set (or free) takes precedence over the tariff.
PLACE_PRICE_FIELDS = ("price_kwh", "price_minute", "session_fee")

# Charges that were read off other data, not measured while charging.
INFERRED_SOURCES = ("inferred", "import-trip")


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
                raise ValueError(messages.TARIFF_PRICE_RANGE(key=k))
            out[k] = v
    if raw.get("currency"):
        cur = str(raw["currency"]).strip().upper()
        if not 1 <= len(cur) <= 4:
            raise ValueError(messages.TARIFF_CURRENCY)
        out["currency"] = cur
    for k in ("home_lat", "home_lon"):
        if k in raw:
            out[k] = None if raw[k] in (None, "") else float(raw[k])
    if "home_radius_m" in raw and raw["home_radius_m"] not in (None, ""):
        r = int(raw["home_radius_m"])
        if not 20 <= r <= 5000:
            raise ValueError(messages.TARIFF_HOME_RADIUS)
        out["home_radius_m"] = r
    return out


def distance_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def place_kind(charge: dict, tariff: dict, place: dict | None = None) -> str:
    """'home' / 'public': a manual choice wins, then the linked place, else guessed: DC is public; AC next to home is home."""
    if charge.get("place_kind") in ("home", "public"):
        return charge["place_kind"]
    if place is not None:
        return "home" if place.get("kind") == "home" else "public"
    if charge.get("charge_type") == "DC":
        return "public"
    if None not in (tariff.get("home_lat"), tariff.get("home_lon"), charge.get("lat"), charge.get("lon")):
        near = distance_m(tariff["home_lat"], tariff["home_lon"], charge["lat"], charge["lon"]) <= tariff["home_radius_m"]
        return "home" if near else "public"
    return "unknown"


def _priced(place: dict) -> bool:
    """A place sets its own rate when it is free or has any price field set."""
    return bool(place.get("free")) or any(place.get(f) is not None for f in PLACE_PRICE_FIELDS)


def _place_amount(charge: dict, place: dict) -> float | None:
    """The place's rate for one charge: energy and minutes at their prices plus the session fee; a free place is zero."""
    if place.get("free"):
        return 0.0
    price_kwh, price_minute = place.get("price_kwh") or 0, place.get("price_minute") or 0
    kwh, minutes = charge.get("energy_kwh"), charge.get("duration_min")
    if (price_kwh and not kwh) or (price_minute and not minutes):
        return None  # the rate needs a value this charge does not have: unknown, never zero
    return round((kwh or 0) * price_kwh + (minutes or 0) * price_minute + (place.get("session_fee") or 0), 2)


def charge_cost(charge: dict, tariff: dict, place: dict | None = None) -> dict:
    """-> {amount, kind, basis} where basis is manual | place | tariff | tariff-guess | none."""
    kind = place_kind(charge, tariff, place)
    if charge.get("cost_manual") is not None:
        return {"amount": charge["cost_manual"], "kind": kind, "basis": "manual"}
    if place is not None and _priced(place):
        return {"amount": _place_amount(charge, place), "kind": kind, "basis": "place"}
    return _tariff_cost(charge, tariff, kind)


def _tariff_cost(charge: dict, tariff: dict, kind: str) -> dict:
    """The tariff's price per kWh for the place kind; no energy is an unknown amount, never zero."""
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


def energy_cost(charge: dict, tariff: dict, place: dict | None = None) -> dict:
    """Energy alone, priced like `charge_cost` but never by the minute or with a session fee (parked loss: energy that
    left the battery, not a charging session). A free place costs 0, a place's price per kWh wins, else the tariff for
    the place kind. -> {amount, kind, basis}."""
    kind = place_kind(charge, tariff, place)
    if place is not None and place.get("free"):
        return {"amount": 0.0, "kind": kind, "basis": "place"}
    if place is not None and place.get("price_kwh") is not None and charge.get("energy_kwh"):
        return {"amount": round(charge["energy_kwh"] * place["price_kwh"], 2), "kind": kind, "basis": "place"}
    return _tariff_cost(charge, tariff, kind)


def trip_cost(trip: dict, tariff: dict) -> float | None:
    return None if not trip.get("energy_kwh") else round(trip["energy_kwh"] * tariff["home_kwh"], 2)
