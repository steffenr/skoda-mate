import time

from skoda_mate.client import ApiError, RateInfo

from .fixtures import BEV, VIN
from .helpers import FakeApi, client_for, make_app, sign_up

KEY = "sk-live-0123456789abcdef"
BODY = {"api_key": KEY, "vins": VIN, "spin": "1234"}


class Factory:
    """api_factory that records what it was asked for and hands out scripted FakeApis."""

    def __init__(self, responses=None):
        self.keys, self.apis, self.responses = [], [], responses

    def __call__(self, key):
        self.keys.append(key)
        api = FakeApi(list(self.responses) if self.responses else None)  # FakeApi copies dict answers itself
        self.apis.append(api)
        return api


def err(status, kind):
    return ApiError(status, kind, "x", None, RateInfo())


def test_skoda_needs_dashboard_login_first():
    f = Factory()
    app, _ = make_app(api_factory=f)
    with client_for(app) as c:
        assert c.post("/api/setup/skoda", json=BODY).status_code == 401  # first run: only creating the login is open
        assert f.keys == []


def test_input_validation_never_reaches_the_api():
    f = Factory()
    app, _ = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        for bad, why in (({**BODY, "api_key": "short"}, "API key"), ({**BODY, "api_key": "has space inside key"}, "API key"),
                         ({**BODY, "vins": "TMB123"}, "valid VIN"), ({**BODY, "vins": "TMBJB9NY5RF99999I"}, "valid VIN"),
                         ({**BODY, "vins": " , "}, "at least one"), ({**BODY, "spin": "12"}, "S-PIN"),
                         ({**BODY, "vins": ",".join(f"TMBJB9NY5RF99999{i}" for i in range(6))}, "At most")):
            r = c.post("/api/setup/skoda", json=bad)
            assert r.status_code == 400 and why.lower() in r.json()["detail"].lower(), (bad, r.json())
        assert f.keys == []


def test_successful_connect_stores_secrets_encrypted_and_polls_immediately():
    f = Factory()
    app, conn = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        assert c.get("/").headers["location"] == "/setup"  # logged in but no car yet
        r = c.post("/api/setup/skoda", json=BODY)
        assert r.status_code == 200 and r.json()["vehicles"] == [{"vin": VIN, "key_expires_at": "2027-06-01T00:00:00Z"}]
        raw = " ".join(x["value"] for x in conn.execute("SELECT value FROM settings"))
        assert KEY not in raw and "1234" not in raw and "pw-12345" not in raw  # no plaintext secrets
        assert VIN in raw  # the VIN is an identifier, not a secret
        st = c.get("/api/setup/status").json()
        assert st["skoda_set"] and st["connected"] and st["spin_set"] and st["vehicles"][0]["name"] == "My Enyaq"
        assert st["vehicles"][0]["key_expires_at"] == "2027-06-01T00:00:00Z"
        assert KEY not in c.get("/api/setup/status").text
        assert c.get("/").status_code == 200
        v = c.get("/api/vehicles").json()
        assert v[0]["vin"] == VIN and v[0]["soc"] == 55  # data is there right away, not after the first interval
        assert f.keys == [KEY] and len(f.apis[0].calls) == 1  # exactly one request for the connection test


def test_rejected_key_stores_nothing_and_explains():
    f = Factory([err(401, "api-key-expired")])
    app, conn = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        r = c.post("/api/setup/skoda", json=BODY)
        assert r.status_code == 400 and "expired" in r.json()["detail"] and VIN[:3] in r.json()["detail"]
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'skoda_%'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0  # nothing left behind
        assert c.get("/api/setup/status").json()["skoda_set"] is False and f.apis[0].closed


def test_key_not_covering_the_vin_is_reported():
    f = Factory([err(403, "api-key-not-authorized")])
    app, _ = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        assert "not allowed to access that vehicle" in c.post("/api/setup/skoda", json=BODY).json()["detail"]


def test_one_bad_vin_among_several_aborts_the_whole_setup():
    second = "TMBJB9NY5RF111111"
    f = Factory([BEV, err(404, "http-404")])
    app, conn = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        r = c.post("/api/setup/skoda", json={**BODY, "vins": f"{VIN}, {second}"})
        assert r.status_code == 400 and second[:3] in r.json()["detail"]
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key='skoda_api_key'").fetchone()[0] == 0


def test_a_failed_change_does_not_disturb_the_working_connection():
    keys = iter([FakeApi(), FakeApi([err(401, "api-key-expired")])])
    app, conn = make_app(api_factory=lambda key: next(keys))
    with client_for(app) as c:
        sign_up(c)
        assert c.post("/api/setup/skoda", json=BODY).status_code == 200
        assert c.post("/api/setup/skoda", json={**BODY, "api_key": "another-key-1234567"}).status_code == 400
        assert c.get("/api/setup/status").json()["connected"] is True


def test_credentials_survive_restart(tmp_path):
    db = str(tmp_path / "t.db")
    f = Factory()
    app, conn = make_app(db_path=db, api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        assert c.post("/api/setup/skoda", json=BODY).status_code == 200
    assert (tmp_path / "secret.key").stat().st_mode & 0o077 == 0  # key file is private
    conn.execute("UPDATE api_calls SET at = at - 600")  # the restart comes after the poll interval, so it polls at once
    conn.commit()
    f2 = Factory()
    app2, _ = make_app(db_path=db, api_factory=f2)  # a fresh process: nothing in memory
    with client_for(app2) as c:
        assert f2.keys == [KEY]
        for _ in range(60):
            if f2.apis[0].calls:
                break
            time.sleep(0.05)
        assert f2.apis[0].calls[0] == ("get", VIN)  # polling resumed on its own
        assert c.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"}).status_code == 200
        assert c.get("/api/setup/status").json()["connected"] is True


def test_spin_can_be_changed_and_cleared_separately():
    app, conn = make_app(api_factory=Factory())
    with client_for(app) as c:
        sign_up(c)
        assert c.put("/api/setup/spin", json={"spin": "1234"}).status_code == 400  # no key yet
        c.post("/api/setup/skoda", json={**BODY, "spin": None})
        assert c.get("/api/setup/status").json()["spin_set"] is False
        assert c.put("/api/setup/spin", json={"spin": "4711"}).json() == {"ok": True, "spin_set": True}
        assert "4711" not in " ".join(x["value"] for x in conn.execute("SELECT value FROM settings"))
        assert c.put("/api/setup/spin", json={"spin": "47"}).status_code == 400
        assert c.put("/api/setup/spin", json={"spin": ""}).json()["spin_set"] is False
        # re-entering the key without a S-PIN keeps the stored one
        c.put("/api/setup/spin", json={"spin": "4711"})
        c.post("/api/setup/skoda", json={"api_key": KEY, "vins": VIN})
        assert c.get("/api/setup/status").json()["spin_set"] is True


def test_forget_account():
    f = Factory()
    app, conn = make_app(api_factory=f)
    with client_for(app) as c:
        sign_up(c)
        c.post("/api/setup/skoda", json=BODY)
        assert c.delete("/api/setup/skoda").status_code == 200
        assert conn.execute("SELECT COUNT(*) FROM settings WHERE key LIKE 'skoda_%'").fetchone()[0] == 0
        assert c.get("/api/setup/status").json()["connected"] is False and f.apis[0].closed
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1  # history stays


def test_vin_parsing_accepts_common_separators():
    from skoda_mate.routers.setup import parse_vins

    assert parse_vins(f"{VIN.lower()}\n tmbjb9ny5rf111111;{VIN}") == [VIN, "TMBJB9NY5RF111111"]  # normalised, de-duplicated
    assert parse_vins([VIN]) == [VIN]
