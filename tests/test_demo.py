from skoda_mate import demo, schema
from skoda_mate.config import Config
from skoda_mate.web import create_app

from .helpers import client_for


def demo_client():
    cfg = Config(db_path=":memory:", demo=True)
    return client_for(create_app(cfg, schema.connect(":memory:")))


def test_demo_mode_needs_no_login_or_account_and_has_history():
    with demo_client() as c:
        assert c.get("/").status_code == 200  # straight to the dashboard
        v = c.get("/api/vehicles").json()
        assert v[0]["vin"] == demo.DEMO_VIN and v[0]["name"] == "Demo Enyaq"
        vid = v[0]["id"]
        o = c.get(f"/api/vehicles/{vid}/overview").json()
        assert o["demo"] is True and o["snapshot"]["soc"] is not None and o["features"]["charge_control"]["available"]
        trips = c.get(f"/api/vehicles/{vid}/trips?limit=500").json()
        assert trips["total"] >= 25 and all(t["distance_km"] and t["start_place"] for t in trips["items"][:10])
        charges = c.get(f"/api/vehicles/{vid}/charges").json()
        assert charges["total"] >= 3 and {x["charge_type"] for x in charges["items"]} >= {"AC"}
        months = c.get(f"/api/vehicles/{vid}/stats").json()["monthly"]
        assert len(months) >= 2 and sum(m["km"] for m in months) > 500
        assert c.get(f"/api/vehicles/{vid}/map").json()["parked"]
        assert c.get(f"/api/vehicles/{vid}/battery").json()["samples"] >= 1


def test_demo_commands_change_the_demo_car_and_setup_is_refused():
    with demo_client() as c:
        vid = c.get("/api/vehicles").json()[0]["id"]
        r = c.post(f"/api/vehicles/{vid}/command", json={"name": "set_charge_limit", "params": {"percent": 90}})
        assert r.status_code == 200 and r.json()["ok"]
        r = c.post(f"/api/vehicles/{vid}/refresh").json()
        assert r["ok"]
        assert c.get(f"/api/vehicles/{vid}/overview").json()["snapshot"]["target_soc"] == 90
        assert c.post("/api/setup/skoda", json={"api_key": "x" * 20, "vins": demo.DEMO_VIN}).status_code == 400
