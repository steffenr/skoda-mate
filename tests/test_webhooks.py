"""Webhooks: what is stored, what is sent, how it is signed and retried."""
import asyncio
import copy
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from skoda_mate import __version__, recorder, schema, webhooks
from skoda_mate.cloud import Cloud
from skoda_mate.config import Config
from skoda_mate.secrets_store import SecretBox

from .helpers import FakeApi, client_for, make_app, sign_up
from .test_web import bev, connected

NOW = 1_800_000_000.0
EVENT = {"id": "abc", "event": "charge.ended", "at": "2026-11-26T18:04:00+00:00",
         "vehicle": {"id": 1, "name": "Enyaq", "vin": "VIN1"}, "data": {"charge_id": 42, "place": "Zuhause für alle"}}


def make(path=":memory:"):
    return schema.connect(path), SecretBox(None)


def hook(conn, box, name="Hook", url="http://receiver.test/in", events=("charge.ended",), enabled=True):
    return webhooks.create(conn, box, {"name": name, "url": url, "events": list(events), "enabled": enabled})


def rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM webhook_deliveries ORDER BY id")]


class Receiver:
    """An httpx transport that answers from a script and keeps what it got."""

    def __init__(self, *answers):
        self.answers, self.got = list(answers) or [200], []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.got.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, headers={"location": "http://elsewhere.test/"} if 300 <= answer < 400 else {})


def worker(conn, box, receiver=None, now=None):
    clock = now or [NOW]
    return webhooks.Worker(conn, box, transport=None if receiver is None else httpx.MockTransport(receiver),
                           clock=lambda: clock[0])


def run(w):
    async def go():
        try:
            await w.run_once()
        finally:
            await w.stop()
    asyncio.run(go())


# ------------------------------------------------------------------ the store

@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": "x" * 61}, {"url": "ftp://host/x"}, {"url": "http://"}, {"url": "javascript:alert(1)"},
    {"url": "http://user:pw@host/"}, {"url": "http://ho st/"}, {"url": "http://[::1"}, {"url": "http://h:99999/"},
    {"url": "http://host/" + "x" * 2000}, {"events": []}, {"events": ["nope"]}, {"events": "charge.ended"},
])
def test_bad_webhooks_are_refused_with_a_message(change):
    conn, box = make()
    with pytest.raises(webhooks.WebhookError):
        webhooks.create(conn, box, {"name": "A", "url": "https://host/x", "events": ["charge.ended"], **change})
    assert webhooks.listing(conn, box) == []


def test_lan_receivers_are_allowed():
    conn, box = make()
    for url in ("http://192.168.1.10:8123/api/webhook/x", "http://homeassistant.local:8123/x", "http://[fd00::1]/x"):
        hook(conn, box, url=url)
    assert len(webhooks.listing(conn, box)) == 3


def test_the_secret_is_returned_once_and_stored_encrypted():
    conn, box = make()
    saved, secret = hook(conn, box)
    stored = conn.execute("SELECT secret_enc FROM webhooks").fetchone()[0]
    assert len(secret) >= 32 and secret not in stored and box.decrypt(stored) == secret
    for view in (saved, webhooks.listing(conn, box)):
        assert secret not in json.dumps(view) and "secret_enc" not in json.dumps(view)
    new = webhooks.rotate(conn, box, saved["id"])
    assert new != secret and box.decrypt(conn.execute("SELECT secret_enc FROM webhooks").fetchone()[0]) == new


def test_only_enabled_hooks_that_subscribed_get_a_delivery():
    conn, box = make()
    wanted, _ = hook(conn, box)
    hook(conn, box, events=["trip.ended"])
    hook(conn, box, enabled=False)
    assert webhooks.enqueue(conn, [EVENT], NOW) == 1
    assert [(r["webhook_id"], r["status"]) for r in rows(conn)] == [(wanted["id"], "pending")]


def test_deleting_a_webhook_removes_its_deliveries_and_unknown_ids_are_reported():
    conn, box = make()
    saved, _ = hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    webhooks.delete(conn, saved["id"])
    assert rows(conn) == [] and webhooks.listing(conn, box) == []
    for call in (lambda: webhooks.delete(conn, 9), lambda: webhooks.rotate(conn, box, 9),
                 lambda: webhooks.retry(conn, 9, NOW), lambda: webhooks.deliveries(conn, 9)):
        with pytest.raises(webhooks.WebhookNotFound):
            call()


# ------------------------------------------------------------------ delivery

def test_a_delivery_reaches_a_local_receiver_with_a_valid_signature():
    got = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((dict(self.headers), self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn, box = make()
        _, secret = hook(conn, box, url=f"http://127.0.0.1:{server.server_port}/in")
        webhooks.enqueue(conn, [EVENT], NOW)
        run(worker(conn, box))
    finally:
        server.shutdown()
        server.server_close()
    (headers, body), = got
    headers = {k.lower(): v for k, v in headers.items()}
    row, = rows(conn)
    assert headers["content-type"] == "application/json" and headers["user-agent"] == f"skoda-mate/{__version__}"
    assert headers["x-skoda-mate-event"] == "charge.ended" and headers["x-skoda-mate-delivery"] == str(row["id"])
    assert headers["x-skoda-mate-signature"] == "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert json.loads(body) == {"version": 1, **{k: EVENT[k] for k in ("event", "at", "vehicle", "data")}}
    assert (row["status"], row["attempts"], row["last_code"], row["last_error"]) == ("ok", 1, 204, None)


def test_failures_are_retried_after_1_min_5_min_15_min_1_h_and_6_h_then_given_up():
    conn, box = make()
    hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    now, receiver, waits = [NOW], Receiver(500), []
    for _ in range(5):
        run(worker(conn, box, receiver, now))
        row, = rows(conn)
        assert row["status"] == "pending"
        waits.append(row["next_at"] - now[0])
        now[0] = row["next_at"] - 1
        run(worker(conn, box, receiver, now))  # not due yet: nothing is sent
        now[0] += 1
    run(worker(conn, box, receiver, now))
    row, = rows(conn)
    assert waits == [60, 300, 900, 3600, 21600]
    assert (row["status"], row["attempts"], len(receiver.got)) == ("failed", 6, 6)
    assert len({r.headers["x-skoda-mate-delivery"] for r in receiver.got}) == 1  # the id to recognise repeats by


@pytest.mark.parametrize("answer, status", [
    (200, "ok"), (201, "ok"), (302, "pending"), (400, "failed"), (404, "failed"), (408, "pending"), (429, "pending"),
    (500, "pending"), (httpx.ConnectError("refused"), "pending"), (httpx.ReadTimeout("slow"), "pending"),
])
def test_which_answers_are_retried(answer, status):
    conn, box = make()
    hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    receiver = Receiver(answer)
    run(worker(conn, box, receiver))
    assert rows(conn)[0]["status"] == status and len(receiver.got) == 1  # a redirect is never followed


def test_410_disables_the_webhook_and_drops_what_was_waiting():
    conn, box = make()
    hook(conn, box)
    webhooks.enqueue(conn, [EVENT, {**EVENT, "id": "def"}], NOW)
    receiver = Receiver(410)
    run(worker(conn, box, receiver))
    assert [r["status"] for r in rows(conn)] == ["failed", "failed"] and len(receiver.got) == 1
    assert webhooks.listing(conn, box)[0]["enabled"] is False


def test_disabling_drops_pending_deliveries_so_old_events_are_not_sent_later():
    conn, box = make()
    saved, _ = hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    data = {"name": "Hook", "url": saved["url"], "events": saved["events"]}
    webhooks.update(conn, box, saved["id"], {**data, "enabled": False})
    webhooks.update(conn, box, saved["id"], {**data, "enabled": True})
    receiver = Receiver(200)
    run(worker(conn, box, receiver))
    assert receiver.got == [] and rows(conn)[0]["status"] == "failed"


def test_a_pending_delivery_is_sent_after_a_restart(tmp_path):
    path = str(tmp_path / "mate.db")
    box = SecretBox(str(tmp_path / "secret.key"))
    conn = schema.connect(path)
    hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    conn.close()
    conn = schema.connect(path)
    receiver = Receiver(200)
    run(worker(conn, SecretBox(str(tmp_path / "secret.key")), receiver))
    assert len(receiver.got) == 1 and rows(conn)[0]["status"] == "ok"


def test_the_running_worker_sends_new_deliveries_when_woken():
    conn, box = make()
    hook(conn, box)
    receiver = Receiver(200)

    async def go():
        w = worker(conn, box, receiver)
        w.start()
        await asyncio.sleep(0.05)
        webhooks.enqueue(conn, [EVENT], NOW)
        w.wake()
        for _ in range(100):
            if receiver.got:
                break
            await asyncio.sleep(0.01)
        await w.stop()

    asyncio.run(go())
    assert len(receiver.got) == 1


def test_a_receiver_that_hangs_does_not_delay_another():
    conn, box = make()
    hook(conn, box, name="slow", url="http://slow.test/")
    hook(conn, box, name="fast", url="http://fast.test/")
    webhooks.enqueue(conn, [EVENT], NOW)
    seen = []

    async def go():
        release = asyncio.Event()

        async def receive(request):
            if request.url.host == "slow.test":
                await release.wait()
            seen.append(request.url.host)
            return httpx.Response(200)

        w = worker(conn, box, receive)
        w.start()
        for _ in range(100):
            if seen:
                break
            await asyncio.sleep(0.01)
        webhooks.enqueue(conn, [{**EVENT, "id": "2"}], NOW)  # while the slow one still hangs
        w.wake()
        for _ in range(100):
            if len(seen) == 2:
                break
            await asyncio.sleep(0.01)
        before_release = list(seen)
        release.set()
        await asyncio.sleep(0.05)
        await w.stop()
        return before_release

    assert asyncio.run(go()) == ["fast.test", "fast.test"]


def test_nothing_is_sent_when_the_secret_cannot_be_read():
    conn, box = make()
    hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    receiver, lost = Receiver(200), SecretBox(None)  # another key: secret.key was lost
    run(worker(conn, lost, receiver))
    assert receiver.got == [] and rows(conn)[0]["status"] == "failed" and "secret" in rows(conn)[0]["last_error"].lower()
    assert webhooks.listing(conn, lost)[0]["secret_unreadable"] is True


def test_send_test_sends_once_even_when_disabled_and_a_retry_queues_it_again():
    conn, box = make()
    recorder.upsert_vehicle(conn, "VIN1", "Enyaq")
    saved, _ = hook(conn, box, enabled=False)
    receiver = Receiver(500)

    async def go():
        w = worker(conn, box, receiver)
        result = await w.send_test(saved["id"])
        await w.stop()
        return result

    result = asyncio.run(go())
    assert (result["event"], result["status"], result["last_code"], result["attempts"]) == ("test", "failed", 500, 1)
    assert json.loads(receiver.got[0].content)["event"] == "test"
    with pytest.raises(webhooks.WebhookError):
        webhooks.retry(conn, result["id"], NOW)  # disabled: nothing would send it
    webhooks.update(conn, box, saved["id"], {"name": "Hook", "url": saved["url"], "events": saved["events"], "enabled": True})
    assert webhooks.retry(conn, result["id"], NOW)["status"] == "pending"
    with pytest.raises(webhooks.WebhookError):
        webhooks.retry(conn, result["id"], NOW)  # already waiting


def test_deliveries_older_than_30_days_are_pruned_and_the_list_is_newest_first():
    conn, box = make()
    saved, _ = hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW - 31 * 86400)
    for n in range(25):
        webhooks.enqueue(conn, [{**EVENT, "id": str(n)}], NOW + n)
    run(worker(conn, box, Receiver(200), [NOW + 100]))
    assert len(rows(conn)) == 25
    listed = webhooks.deliveries(conn, saved["id"])
    assert len(listed) == 20 and listed[0]["id"] > listed[-1]["id"] and "payload" not in listed[0]
    assert webhooks.listing(conn, box)[0]["last_delivery"]["id"] == listed[0]["id"]


# ------------------------------------------------------------------ in the app

def test_dispatch_queues_a_delivery_even_when_mqtt_fails():
    conn, box = make()
    vid = recorder.upsert_vehicle(conn, "VIN1", "Enyaq")
    hook(conn, box)

    class Broken:
        publisher = type("P", (), {"publish_events": lambda *a: 1 / 0})()

    cloud = Cloud(conn, box, Config(db_path=":memory:"), Broken())
    with pytest.raises(ZeroDivisionError):  # the poller catches and logs this
        cloud.dispatch(vid, [{"event": "charge.ended", "at": EVENT["at"], "data": {"charge_id": 1}}])
    assert json.loads(rows(conn)[0]["payload"])["vehicle"]["vin"] == "VIN1"


def test_a_poll_of_the_running_app_reaches_the_receiver():
    """The whole way: reading -> event -> stored delivery -> worker -> signed request."""
    unplugged = bev(**{"charging.status.state": "READY_FOR_CHARGING"})
    low = copy.deepcopy(unplugged)
    low["vehicle"]["charging"]["status"]["battery"]["stateOfChargeInPercent"] = 12
    c, _, _, vid = connected(FakeApi([unplugged, low]))
    receiver = Receiver(200)
    try:
        c.app.state.ctx.cloud.webhooks.transport = httpx.MockTransport(receiver)
        secret = c.post("/api/webhooks", json={**BODY, "events": ["soc.low"]}).json()["secret"]
        assert c.post(f"/api/vehicles/{vid}/refresh").json()["ok"] is True
        for _ in range(200):
            if receiver.got:
                break
            time.sleep(0.01)
    finally:
        c.__exit__(None, None, None)
    request, = receiver.got
    assert request.headers["x-skoda-mate-signature"] == webhooks.sign(secret, request.content)
    assert json.loads(request.content)["data"] == {"soc": 12, "threshold": 20}


def test_the_worker_runs_as_long_as_the_app_also_without_a_connected_car():
    app, _ = make_app()
    worker_of_app = app.state.ctx.cloud.webhooks
    with client_for(app):
        assert worker_of_app.running
    assert not worker_of_app.running


def test_disconnecting_from_skoda_keeps_the_worker():
    app, _ = make_app()
    cloud = app.state.ctx.cloud

    async def go():
        cloud.webhooks.start()
        await cloud.stop()
        still = cloud.webhooks.running
        await cloud.webhooks.stop()
        return still

    assert asyncio.run(go())


# ------------------------------------------------------------------ the API

ROUTES = [("get", "/api/webhooks"), ("post", "/api/webhooks"), ("put", "/api/webhooks/options"),
          ("put", "/api/webhooks/1"), ("delete", "/api/webhooks/1"), ("post", "/api/webhooks/1/secret"),
          ("post", "/api/webhooks/1/test"), ("get", "/api/webhooks/1/deliveries"),
          ("post", "/api/webhooks/deliveries/1/retry")]
BODY = {"name": "HA", "url": "http://192.168.1.10:8123/api/webhook/x", "events": ["trip.ended"], "enabled": True}


@pytest.mark.parametrize("method, path", ROUTES)
def test_every_route_needs_a_session(method, path):
    app, _ = make_app()
    with client_for(app) as owner:
        sign_up(owner)
    stranger = client_for(app)
    assert stranger.request(method.upper(), path, json=BODY).status_code == 401


def signed_in():
    app, conn = make_app()
    c = client_for(app)
    sign_up(c)
    return app, conn, c


def test_create_edit_rotate_and_delete_over_the_api():
    _, _, c = signed_in()
    made = c.post("/api/webhooks", json=BODY).json()
    secret, hook_id = made["secret"], made["webhook"]["id"]
    got = c.get("/api/webhooks")
    assert secret not in got.text and [w["name"] for w in got.json()["webhooks"]] == ["HA"]
    assert [g["group"] for g in got.json()["event_groups"]] == ["Driving", "Charging", "Climate", "Security", "Places", "System"]
    assert c.put(f"/api/webhooks/{hook_id}", json={**BODY, "name": "New"}).json()["name"] == "New"
    new = c.post(f"/api/webhooks/{hook_id}/secret").json()["secret"]
    assert new != secret and new not in c.get("/api/webhooks").text
    assert c.get(f"/api/webhooks/{hook_id}/deliveries").json() == {"deliveries": []}
    assert c.delete(f"/api/webhooks/{hook_id}").status_code == 200 and c.get("/api/webhooks").json()["webhooks"] == []


def test_api_errors_are_plain_messages():
    _, _, c = signed_in()
    bad = c.post("/api/webhooks", json={**BODY, "url": "ftp://x"})
    assert (bad.status_code, bad.json()["detail"]) == (400, webhooks.BAD_URL)
    for method, path in ROUTES[3:]:
        assert c.request(method.upper(), path.replace("/1", "/99"), json=BODY).status_code == 404


def test_send_test_and_retry_over_the_api():
    app, _, c = signed_in()
    receiver = Receiver(500, 200)
    app.state.ctx.cloud.webhooks.transport = httpx.MockTransport(receiver)
    hook_id = c.post("/api/webhooks", json=BODY).json()["webhook"]["id"]
    result = c.post(f"/api/webhooks/{hook_id}/test").json()
    assert (result["status"], result["last_code"]) == ("failed", 500)
    assert c.post(f"/api/webhooks/deliveries/{result['id']}/retry").json()["status"] == "pending"
    assert c.post(f"/api/webhooks/deliveries/{result['id']}/retry").status_code == 400


def test_the_low_battery_threshold():
    _, _, c = signed_in()
    assert c.get("/api/webhooks").json()["soc_low_threshold"] == 20
    assert c.put("/api/webhooks/options", json={"soc_low_threshold": 35}).json() == {"soc_low_threshold": 35}
    assert c.get("/api/webhooks").json()["soc_low_threshold"] == 35
    for bad in (4, 51, "x", None, 20.5, True):
        assert c.put("/api/webhooks/options", json={"soc_low_threshold": bad}).status_code == 400


def test_an_idle_worker_only_reads_so_it_never_commits_another_writers_half_done_work(monkeypatch):
    """The connection is shared: a commit from the worker would also save whatever a request has half written."""
    conn, box = make()
    hook(conn, box)
    writes = []
    real = conn.execute

    def execute(sql, params=()):
        if not sql.lstrip().upper().startswith("SELECT"):
            writes.append(sql)
        return real(sql, params)

    monkeypatch.setattr(conn, "execute", execute)
    monkeypatch.setattr(conn, "commit", lambda: writes.append("commit"))
    run(worker(conn, box, Receiver(200)))
    assert writes == []


def test_the_log_never_shows_the_secret(caplog):
    caplog.set_level("DEBUG")
    conn, box = make()
    _, secret = hook(conn, box)
    webhooks.enqueue(conn, [EVENT], NOW)
    run(worker(conn, box, Receiver(httpx.ConnectError("refused"))))
    assert secret not in caplog.text
