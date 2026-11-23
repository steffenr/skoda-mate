import copy

from skoda_mate.client import ApiError, RateInfo

from .fixtures import BEV
from .helpers import FakeApi, client_for, make_app, sign_up

KEY = "sk-live-0123456789abcdef"
VIN1, VIN2, VIN3 = "TMBJB9NY5RF111111", "TMBJB9NY5RF222222", "TMBJB9NY5RF333333"


class PerVinApi(FakeApi):
    """A key that covers VIN1 and VIN2 only; each car answers with its own VIN."""
    covers = {VIN1, VIN2}

    async def get_vehicle(self, vin, include=None):
        self.calls.append(("get", vin))
        if vin not in self.covers:
            raise ApiError(403, "api-key-not-authorized", "x", None, RateInfo())
        data = copy.deepcopy(BEV)
        data["vehicle"]["vin"] = vin
        data["vehicle"]["name"] = f"Car {vin[-1]}"
        from skoda_mate.client import ApiResult
        return ApiResult(data=data, rate=RateInfo(20, 19, 3000, self.clock()), key_expires_at="2027-06-01T00:00:00Z")


def app():
    apis = []

    def factory(key):
        apis.append(PerVinApi())
        return apis[-1]

    return make_app(api_factory=factory)


def test_two_cars_at_setup_have_separate_data_and_budgets():
    a, conn = app()
    with client_for(a) as c:
        sign_up(c)
        assert c.post("/api/setup/skoda", json={"api_key": KEY, "vins": f"{VIN1}, {VIN2}"}).status_code == 200
        cars = c.get("/api/vehicles").json()
        assert [x["vin"] for x in cars] == [VIN1, VIN2] and all(x["active"] for x in cars) and cars[0]["soc"] == 55
        o1, o2 = (c.get(f"/api/vehicles/{x['id']}/overview").json() for x in cars)
        assert o1["vehicle"]["vin"] == VIN1 and o2["vehicle"]["vin"] == VIN2
        assert o1["poller"]["budget"]["used"] == 1 and o2["poller"]["budget"]["used"] == 1  # each car has its own quota
        c.post(f"/api/vehicles/{cars[0]['id']}/refresh")
        assert c.get(f"/api/vehicles/{cars[0]['id']}/overview").json()["poller"]["budget"]["used"] == 2
        assert c.get(f"/api/vehicles/{cars[1]['id']}/overview").json()["poller"]["budget"]["used"] == 1  # untouched
        # capacity is per car
        c.put(f"/api/vehicles/{cars[0]['id']}", json={"battery_kwh": 77})
        assert c.get(f"/api/vehicles/{cars[1]['id']}/overview").json()["needs_capacity"] is True


def test_add_and_remove_a_car_with_the_stored_key():
    a, conn = app()
    with client_for(a) as c:
        sign_up(c)
        c.post("/api/setup/skoda", json={"api_key": KEY, "vins": VIN1})
        assert c.post("/api/setup/vehicles", json={"vin": VIN1}).status_code == 400  # already there
        assert c.post("/api/setup/vehicles", json={"vin": "BAD"}).status_code == 400
        r = c.post("/api/setup/vehicles", json={"vin": VIN3})  # the key does not cover it: refused, nothing left behind
        assert r.status_code == 400 and "not allowed" in r.json()["detail"]
        assert conn.execute("SELECT COUNT(*) FROM vehicles WHERE vin=?", (VIN3,)).fetchone()[0] == 0
        assert c.get("/api/setup/status").json()["vehicles"][0]["vin"] == VIN1 and len(c.get("/api/setup/status").json()["vehicles"]) == 1
        assert c.post("/api/setup/vehicles", json={"vin": VIN2}).status_code == 200
        st = c.get("/api/setup/status").json()
        assert [v["vin"] for v in st["vehicles"]] == [VIN1, VIN2] and st["spin_set"] is False
        assert len(c.get("/api/vehicles").json()) == 2
        # remove: history stays, reading stops
        assert c.delete(f"/api/setup/vehicles/{VIN2}").status_code == 200
        cars = {x["vin"]: x for x in c.get("/api/vehicles").json()}
        assert cars[VIN2]["active"] is False and cars[VIN1]["active"] is True and cars[VIN2]["soc"] == 55
        assert [v["vin"] for v in c.get("/api/setup/status").json()["vehicles"]] == [VIN1]
        assert c.delete(f"/api/setup/vehicles/{VIN1}").status_code == 400  # the last car cannot be removed
        assert c.delete(f"/api/setup/vehicles/{VIN3}").status_code == 404
        # adding it back resumes with the old history intact
        assert c.post("/api/setup/vehicles", json={"vin": VIN2}).status_code == 200
        assert {x["vin"]: x["active"] for x in c.get("/api/vehicles").json()} == {VIN1: True, VIN2: True}


def test_adding_needs_a_connection_and_a_session():
    a, conn = app()
    with client_for(a) as c:
        sign_up(c)
        assert c.post("/api/setup/vehicles", json={"vin": VIN1}).status_code == 400  # no key stored yet
        c.cookies.clear()
        assert c.post("/api/setup/vehicles", json={"vin": VIN1}).status_code == 401
        assert c.delete(f"/api/setup/vehicles/{VIN1}").status_code == 401
