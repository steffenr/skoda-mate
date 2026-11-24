import time

import pytest
from fastapi.testclient import TestClient

from skoda_mate import schema
from skoda_mate.auth import Auth, SetupError, hash_password, verify_password

from .helpers import client_for, make_app, sign_up


def fresh():
    conn = schema.connect(":memory:")
    return Auth(b"k" * 32, conn), conn


def test_hash_is_salted_and_verifies():
    a, b = hash_password("pw-12345"), hash_password("pw-12345")
    assert a != b and "pw-12345" not in a
    assert verify_password("pw-12345", a) and not verify_password("nope", a)
    assert not verify_password("x", "garbage")


def test_set_credentials_validates_and_persists():
    a, conn = fresh()
    assert not a.enabled
    for bad in (("nope", "pw-12345"), ("a@b.io", "short")):
        with pytest.raises(SetupError):
            a.set_credentials(conn, *bad)
    a.set_credentials(conn, " Me@X.io ", "pw-12345")
    assert a.enabled and a.email == "me@x.io"
    again = Auth(b"k" * 32, conn)  # a restart reads it back
    assert again.check("ME@x.io", "pw-12345") and not again.check("me@x.io", "wrong")


def test_token_roundtrip_tamper_and_password_change():
    a, conn = fresh()
    a.set_credentials(conn, "me@x.io", "pw-12345")
    t = a.make_token(now=1000)
    assert a.valid_token(t, now=1001)
    assert not a.valid_token(t, now=1000 + 15 * 86400)  # expired
    assert not a.valid_token(t[:-2] + "00", now=1001)  # bad signature
    assert not a.valid_token("junk") and not a.valid_token(None)
    a.set_credentials(conn, "me@x.io", "another-pw-1")
    assert not a.valid_token(t, now=1001)  # password change signs everyone out


def test_first_run_redirects_to_setup():
    app, _ = make_app()
    with client_for(app) as c:
        assert c.get("/").headers["location"] == "/setup"
        assert c.get("/login").headers["location"] == "/setup"
        assert "Dashboard login" in c.get("/setup").text
        assert c.get("/api/setup/status").json()["login_set"] is False
        assert c.post("/api/login", json={"email": "a@b.io", "password": "x"}).status_code == 404


def test_login_flow_and_guard():
    app, _ = make_app()
    with client_for(app) as c:
        sign_up(c)
        c.post("/api/logout")
        assert c.get("/health").status_code == 200  # public
        assert c.get("/api/vehicles").status_code == 401
        assert c.post("/api/vehicles/1/command", json={"name": "lock"}).status_code == 401
        assert c.get("/").headers["location"] == "/login"
        assert c.get("/setup").headers["location"] == "/login"
        assert "Sign in" in c.get("/login").text
        assert c.post("/api/login", json={"email": "me@example.com", "password": "nope"}).status_code == 401
        r = c.post("/api/login", json={"email": " ME@example.com ", "password": "pw-12345"})
        assert r.status_code == 200
        ck = r.headers["set-cookie"].lower()
        assert "httponly" in ck and "samesite=strict" in ck
        assert c.get("/api/vehicles").status_code == 200


def test_cookie_secure_flag_follows_the_connection():
    """Regression: a Secure cookie over plain http is dropped by the browser, so login 'worked' and then bounced back."""
    def flag(headers=None, **cfg):
        app, _ = make_app(**cfg)
        with client_for(app) as c:
            r = c.post("/api/setup/login", json={"email": "me@example.com", "password": "pw-12345", "setup_code": app.state.setup_code()},
                       headers=headers or {})
            assert r.status_code == 200
            return "secure" in r.headers["set-cookie"].lower()

    assert flag() is False  # plain http: must NOT be Secure
    assert flag({"X-Forwarded-Proto": "https"}) is True  # behind a TLS-terminating proxy (DDEV, nginx, Caddy)
    assert flag({"X-Forwarded-Proto": "https, http"}) is True
    assert flag({"X-Forwarded-Proto": "http"}) is False
    assert flag(cookie_secure=True) is True  # COOKIE_SECURE=true still forces it


def test_changing_login_requires_session():
    app, _ = make_app()
    with client_for(app) as c:
        sign_up(c)
        c.cookies.clear()
        r = c.post("/api/setup/login", json={"email": "evil@x.io", "password": "takeover-1"})
        assert r.status_code == 401
        c.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"})
        new = {"email": "me@example.com", "password": "new-pass-99"}
        assert c.post("/api/setup/login", json=new).status_code == 403  # a signed-in browser alone is not enough
        assert c.post("/api/setup/login", json={**new, "current_password": "wrong-one"}).status_code == 403
        assert c.post("/api/setup/login", json={**new, "current_password": "pw-12345"}).status_code == 200
        assert c.post("/api/setup/login", json={"email": "me@example.com", "password": "short", "current_password": "new-pass-99"}).status_code == 400


def test_wrong_current_password_is_throttled():
    app, _ = make_app()
    with client_for(app) as c:
        sign_up(c)
        for _ in range(5):
            assert c.post("/api/setup/login", json={"email": "a@b.io", "password": "pw-123456", "current_password": "x"}).status_code == 403
        r = c.post("/api/setup/login", json={"email": "a@b.io", "password": "pw-123456", "current_password": "pw-12345"})
        assert r.status_code == 429


def test_first_run_needs_the_setup_code_from_the_log(caplog):
    with caplog.at_level("WARNING"):
        app, conn = make_app()
    code = app.state.setup_code()
    assert len(code) == 10 and f"{code[:5]}-{code[5:]}" in caplog.text
    with client_for(app) as c:
        assert c.get("/api/setup/status").json()["setup_code_required"] is True
        body = {"email": "me@example.com", "password": "pw-12345"}
        assert c.post("/api/setup/login", json=body).status_code == 403
        assert c.post("/api/setup/login", json={**body, "setup_code": "AAAAA-AAAAA"}).status_code == 403
        assert c.app.state.setup_code() == code  # a wrong guess does not burn the code
        r = c.post("/api/setup/login", json={**body, "setup_code": f" {code[:5].lower()}-{code[5:]} "})  # as copied from the log
        assert r.status_code == 200
        assert c.app.state.setup_code() is None and c.get("/api/setup/status").json()["setup_code_required"] is False


BODY = {"email": "me@example.com", "password": "pw-12345"}


@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.20", "10.1.2.3", "172.17.0.1", "::1", "fe80::1", "fd00::5", "::ffff:192.168.0.9"])
def test_no_setup_code_from_the_home_network(host):
    app, _ = make_app()
    with TestClient(app, client=(host, 5000), follow_redirects=False) as c:
        assert c.get("/api/setup/status").json()["setup_code_required"] is False
        assert c.post("/api/setup/login", json=BODY).status_code == 200


@pytest.mark.parametrize("host,xff", [("203.0.113.7", None), ("8.8.8.8", "192.168.1.2"), ("172.17.0.1", "203.0.113.7"),
                                      ("127.0.0.1", "203.0.113.7, 10.0.0.1"), ("100.64.0.1", None),
                                      ("172.17.0.1", "192.168.1.5, 203.0.113.7")])  # forged private entry, proxy appended the real one
def test_setup_code_from_public_addresses_and_through_a_proxy(host, xff):
    app, _ = make_app()
    headers = {"X-Forwarded-For": xff} if xff else {}
    with TestClient(app, client=(host, 5000), follow_redirects=False) as c:
        assert c.get("/api/setup/status", headers=headers).json()["setup_code_required"] is True
        assert c.post("/api/setup/login", json=BODY, headers=headers).status_code == 403
        assert c.post("/api/setup/login", json={**BODY, "setup_code": app.state.setup_code()}, headers=headers).status_code == 200


def test_setup_code_from_the_environment(tmp_path):
    app, _ = make_app(db_path=str(tmp_path / "t.db"), setup_code="my-own-code-42")
    assert not (tmp_path / "setup-code.txt").exists()  # nothing written when the owner chose the code
    with client_for(app) as c:
        assert c.post("/api/setup/login", json={**BODY, "setup_code": "wrong"}).status_code == 403
        assert c.post("/api/setup/login", json={**BODY, "setup_code": "MY-OWN-CODE-42"}).status_code == 200


def test_setup_code_file_is_private_and_removed_after_setup(tmp_path):
    app, _ = make_app(db_path=str(tmp_path / "t.db"))
    f = tmp_path / "setup-code.txt"
    assert f.read_text().strip().replace("-", "") == app.state.setup_code() and f.stat().st_mode & 0o077 == 0
    with client_for(app) as c:
        assert c.post("/api/setup/login", json={**BODY, "setup_code": f.read_text()}).status_code == 200
    assert not f.exists()
    f.write_text("STALE-CODE")  # e.g. left over from a crash
    make_app(db_path=str(tmp_path / "t.db"))  # a restart with a login writes no new code and removes a stale one
    assert not f.exists()


def test_setup_code_guesses_are_throttled():
    app, _ = make_app()
    with client_for(app) as c:
        body = {"email": "me@example.com", "password": "pw-12345"}
        for _ in range(5):
            assert c.post("/api/setup/login", json={**body, "setup_code": "WRONGCODE2"}).status_code == 403
        assert c.post("/api/setup/login", json={**body, "setup_code": app.state.setup_code()}).status_code == 429


def test_first_run_exposes_nothing_but_the_setup():
    app, _ = make_app()
    with client_for(app) as c:
        assert c.get("/api/vehicles").status_code == 401
        assert c.get("/api/settings").status_code == 401
        assert c.put("/api/settings", json={"units": "mi"}).status_code == 401
        assert c.post("/api/setup/skoda", json={"api_key": "x" * 20, "vins": "TMBJB9NY5RF999999"}).status_code == 401
        assert c.get("/api/setup/status").status_code == 200 and c.get("/setup").status_code == 200
        assert c.get("/health").status_code == 200


def test_login_created_on_the_command_line_needs_no_code(tmp_path):
    from skoda_mate import __main__ as cli

    db = str(tmp_path / "t.db")
    app, conn = make_app(db_path=db)
    with client_for(app) as c:
        assert app.state.setup_code() and (tmp_path / "setup-code.txt").exists()
        pw = iter(["pw-12345"] * 2)
        assert cli.reset_password("me@example.com", db, ask=lambda _: next(pw), say=lambda *_: None) == 0
        time.sleep(1.1)  # the app re-reads the login at most once per second
        assert c.get("/api/setup/status").status_code == 401  # a login exists now: the setup needs a session
        assert c.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"}).status_code == 200
        assert c.get("/api/setup/status").json()["setup_code_required"] is False
        assert app.state.setup_code() is None and not (tmp_path / "setup-code.txt").exists()
        assert c.get("/api/vehicles").status_code == 200


def test_demo_needs_no_setup_code():
    app, _ = make_app(demo=True)
    assert app.state.setup_code() is None


def test_logout_signs_out_every_session():
    app, _ = make_app()
    with client_for(app) as c, client_for(app) as other:
        sign_up(c)
        assert other.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"}).status_code == 200
        stolen = c.cookies.get("skoda_mate_session")
        assert c.post("/api/logout").status_code == 200
        assert other.get("/api/vehicles").status_code == 401  # the other browser is signed out too
        c.cookies.set("skoda_mate_session", stolen)
        assert c.get("/api/vehicles").status_code == 401  # and an old copy of the token no longer works
        c.cookies.clear()
        assert c.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"}).status_code == 200
        assert c.get("/api/vehicles").status_code == 200


def test_logout_without_session_revokes_nothing():
    app, _ = make_app()
    with client_for(app) as c, client_for(app) as stranger:
        sign_up(c)
        assert stranger.post("/api/logout").status_code == 200
        assert c.get("/api/vehicles").status_code == 200


def test_session_generation_survives_restart(tmp_path):
    db = str(tmp_path / "t.db")
    a = Auth(b"k" * 32, schema.connect(db))
    conn = a._conn
    a.set_credentials(conn, "me@x.io", "pw-12345")
    t = a.make_token()
    a.revoke_sessions(conn)
    assert not a.valid_token(t) and not Auth(b"k" * 32, schema.connect(db)).valid_token(t)
    t2 = a.make_token()
    assert Auth(b"k" * 32, schema.connect(db)).valid_token(t2)


def test_throttle_global_cap_and_pruning():
    a, _ = fresh()
    for i in range(29):
        a.fail(f"10.0.0.{i}", now=1000)
    assert not a.locked("10.9.9.9", now=1000)
    a.fail("10.0.0.99", now=1000)
    assert a.locked("10.9.9.9", now=1000)  # 30 failures from many addresses lock everyone out for a while
    assert not a.locked("10.9.9.9", now=1000 + 301) and a._fails == {}  # and are forgotten afterwards


def test_throttle_memory_is_bounded(monkeypatch):
    from skoda_mate import auth

    monkeypatch.setattr(auth, "MAX_TRACKED_IPS", 10)
    a, _ = fresh()
    for i in range(50):
        a.fail(f"ip{i}", now=1000 + i)
    assert len(a._fails) == 10


def test_email_with_separator_or_space_is_rejected():
    a, conn = fresh()
    for bad in ("a|b@x.io", "a b@x.io", "a@x.io|9999999999", "a@b", "@x.io", "a@x." , "a" * 250 + "@x.io"):
        with pytest.raises(SetupError):
            a.set_credentials(conn, bad, "pw-12345")


def test_email_check_is_linear_and_accepts_subdomains():
    """The domain part must not backtrack polynomially on long runs without a dot (CodeQL py/polynomial-redos)."""
    from skoda_mate.auth import EMAIL_RE

    for good in ("me@x.io", "first.last+tag@mail.example.co.uk"):
        assert EMAIL_RE.fullmatch(good), good
    for bad in ("a@x..io", "a@.x.io", "a@x.io.", "a@b"):
        assert not EMAIL_RE.fullmatch(bad), bad
    start = time.monotonic()
    assert not EMAIL_RE.fullmatch("!@" + "!" * 20000)
    assert time.monotonic() - start < 0.5


def test_health_details_only_when_signed_in():
    app, _ = make_app(api_token="tok-123")
    with client_for(app) as c:
        assert c.get("/health").json() == {"ok": True}
        assert "version" in c.get("/health", headers={"Authorization": "Bearer tok-123"}).json()
        sign_up(c)
        assert "version" in c.get("/health").json()
        c.cookies.clear()
        assert c.get("/health").json() == {"ok": True}


def test_security_headers_and_csp():
    app, _ = make_app()
    with client_for(app) as c:
        for path in ("/setup", "/health", "/static/app.js"):
            h = c.get(path).headers
            assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "strict-origin-when-cross-origin"  # OSM tiles need a Referer
            csp = h["content-security-policy"]
            assert "script-src 'self' https://cdnjs.cloudflare.com;" in csp and "frame-ancestors 'none'" in csp
            img = next(d for d in csp.split(";") if d.strip().startswith("img-src")).split()  # exact sources, not substrings
            assert {"https://tile.openstreetmap.org", "https://iprenders.blob.core.windows.net"} <= set(img)  # map, car picture


def test_pages_have_no_inline_scripts():
    """The CSP allows no inline script, so every page must load its code from /static."""
    from html.parser import HTMLParser
    from pathlib import Path

    class Scan(HTMLParser):  # a real parser: tag and attribute names come lower-cased, whatever the source's case
        def __init__(self):
            super().__init__()
            self.inline, self.handlers, self.in_script = [], [], False

        def handle_starttag(self, tag, attrs):
            names = [n for n, _ in attrs]
            if tag == "script":
                self.in_script = True
                if "src" not in names:
                    self.inline.append(self.get_starttag_text())
            self.handlers += [f"{tag} {n}" for n in names if n.startswith("on")]

        def handle_endtag(self, tag):
            if tag == "script":
                self.in_script = False

        def handle_data(self, data):
            if self.in_script and data.strip():
                self.inline.append(data.strip()[:60])

    for page in ("index.html", "login.html", "setup.html"):
        scan = Scan()
        scan.feed((Path(__file__).parent.parent / "skoda_mate" / page).read_text())
        assert not scan.inline, (page, scan.inline)
        assert not scan.handlers, (page, scan.handlers)  # no inline event handlers either

    caught = Scan()
    caught.feed('<SCRIPT>alert(1)</SCRIPT><div OnClick="x()"></div>')
    assert caught.inline and caught.handlers == ["div onclick"]  # the check itself catches upper-case markup


def test_oversized_bodies_are_refused_before_parsing():
    from skoda_mate import web

    app, _ = make_app()
    with client_for(app) as c:
        big = "x" * (web.MAX_ANON_BODY + 10)
        assert c.post("/api/login", json={"email": big, "password": "x"}).status_code == 413  # a stranger: small limit
        sign_up(c)
        r = c.put("/api/settings", content=b"{" + b" " * (web.MAX_ANON_BODY + 10) + b"}", headers={"content-type": "application/json"})
        assert r.status_code != 413  # signed in: room for the history import
        assert c.post("/api/login", headers={"content-length": "abc"}).status_code in (400, 413)


def test_chunked_bodies_are_counted_too():
    from skoda_mate import web

    app, _ = make_app()

    def chunks(n):
        for _ in range(n):
            yield b" " * 8192

    with client_for(app) as c:
        assert c.post("/api/login", content=chunks(20), headers={"content-type": "application/json"}).status_code == 413
        r = c.post("/api/login", content=iter([b'{"email":"a@b.io",', b'"password":"x"}']), headers={"content-type": "application/json"})
        assert r.status_code == 404  # small chunked body passes through intact (no login yet: 404)
        assert web.MAX_BODY > 8_000_000 * 1.2


def test_bruteforce_lockout():
    app, _ = make_app()
    with client_for(app) as c:
        sign_up(c)
        c.cookies.clear()
        for _ in range(5):
            assert c.post("/api/login", json={"email": "me@example.com", "password": "x"}).status_code == 401
        assert c.post("/api/login", json={"email": "me@example.com", "password": "pw-12345"}).status_code == 429
