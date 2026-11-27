import ast
import asyncio
import re
from pathlib import Path

import pytest

from skoda_mate import commands, ha_mqtt, messages
from skoda_mate.client import ApiError

from .fixtures import VIN, bev
from .test_mqtt_settings import _answering
from .test_poller import setup as poller_setup
from .test_web import connected

PACKAGE = Path(__file__).parent.parent / "skoda_mate"
# Refusals the signed-in dashboard never shows as text: the login and first-run pages (English on purpose), ids and
# values the dashboard itself fills in, and the redirect to the login page.
ENGLISH_ONLY = {
    "login is not enabled", "too many attempts", "wrong e-mail or password", "not signed in",
    "no such vehicle", "no such trip", "no such charge", "unknown export", "place_kind must be home, public or empty",
    "The current password is wrong.",
    "Wrong setup code. It is in Mate's log and in setup-code.txt in the data folder (or it is your SETUP_CODE).",
}


def _calls():
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                yield path.relative_to(PACKAGE).as_posix(), node


def test_a_fixed_refusal_keeps_its_english_text_and_adds_the_template():
    c, conn, api, vid = connected()
    r = c.get("/api/places/9999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Place not found.", "detail_i18n": {"message": "Place not found.", "params": {}}}


def test_a_refusal_with_values_sends_them_as_parameters():
    c, conn, api, vid = connected()
    r = c.put("/api/settings", json={"poll_idle_s": 10})
    assert r.status_code == 400
    assert r.json() == {"detail": "poll_idle_s must be between 180 and 21600",
                        "detail_i18n": {"message": "{key} must be between {lo} and {hi}",
                                        "params": {"key": "poll_idle_s", "lo": 180, "hi": 21600}}}


def test_a_refusal_raised_deeper_down_keeps_its_template():
    c, conn, api, vid = connected()
    r = c.put("/api/settings", json={"tariff": {"currency": "much too long"}})
    assert r.status_code == 400 and r.json()["detail_i18n"]["message"] == r.json()["detail"]
    r = c.post("/api/places", json={"name": "A", "lat": 50, "lon": 8, "kind": "home"})
    r = c.post("/api/places", json={"name": "B", "lat": 50, "lon": 8, "kind": "home"})
    assert r.status_code == 409 and r.json()["detail_i18n"]["message"] == "Only one home place is allowed."


def test_the_security_headers_stay_on_a_translatable_refusal():
    c, conn, api, vid = connected()
    assert "content-security-policy" in c.get("/api/places/9999").headers


def test_a_value_that_looks_like_a_placeholder_stays_literal():
    found = messages.of(ValueError(messages.INVALID_VIN(vin="{vin} <b>")))
    assert str(found).startswith("'{vin} <b>' is not a valid VIN")
    assert str(messages.of(ValueError("a {brace} from elsewhere"))) == "a {brace} from elsewhere"


def test_a_message_can_carry_another_message_as_a_value():
    inner = messages.PLACE_NOT_FOUND()
    outer = messages.VIN_ERROR(vin="TMB…1234", error=inner)
    assert str(outer) == "TMB…1234: Place not found."
    assert messages.i18n(outer) == {"message": "{vin}: {error}",
                                    "params": {"vin": "TMB…1234", "error": {"message": "Place not found.", "params": {}}}}


def test_a_poll_error_from_skoda_keeps_its_detail_literally():
    p, api, conn, clock, vid = poller_setup([ApiError(418, "teapot", "<i>{x}</i>")])
    out = asyncio.run(p.poll(VIN, reason="manual"))
    assert out["error"] == "Škoda API error 418: <i>{x}</i>"
    assert out["error_i18n"] == {"message": "Škoda API error {status}: {detail}", "params": {"status": 418, "detail": "<i>{x}</i>"}}
    status = p.status(VIN)
    assert (status["error"], status["error_i18n"]) == (out["error"], out["error_i18n"])


def test_the_poll_error_template_goes_away_with_the_error():
    p, api, conn, clock, vid = poller_setup([ApiError(429, "rate-limit-exceeded", "x", 60), bev()])
    asyncio.run(p.poll(VIN))
    assert p.status(VIN)["error_i18n"]["message"] == "Škoda's request limit is used up. Mate waits for it to reset."
    clock.advance(4000)
    asyncio.run(p.poll(VIN))
    assert (p.status(VIN)["error"], p.status(VIN)["error_i18n"]) == (None, None)


def test_a_budget_refusal_says_how_long_to_wait_as_a_parameter():
    p, api, conn, clock, vid = poller_setup()
    for _ in range(40):
        out = asyncio.run(p.poll(VIN, reason="manual"))
        if not out["ok"]:
            break
    assert out["kind"] == "budget" and out["error"] == f"Request limit reached; next slot in {out['retry_in']} s"
    assert out["error_i18n"] == {"message": "Request limit reached; next slot in {seconds} s", "params": {"seconds": out["retry_in"]}}


def test_a_failed_command_is_translatable_and_the_log_keeps_english():
    p, api, conn, clock, vid = poller_setup()
    api.operate_error = ApiError(403, "operation-disabled", "x")
    out = asyncio.run(p.run_command(VIN, "start_charging"))
    assert out["error_i18n"]["message"] == out["error"]
    assert conn.execute("SELECT error FROM commands").fetchone()[0] == out["error"]


def test_the_mqtt_test_answer_carries_its_template():
    gone = ha_mqtt.probe("10.255.255.1", 1883, client_factory=lambda: _answering("unreachable"), timeout=1)
    assert gone["message"].startswith("Cannot reach 10.255.255.1:1883.")
    assert gone["message_i18n"]["params"] == {"host": "10.255.255.1", "port": 1883}
    ok = ha_mqtt.probe("ha", 1883, client_factory=lambda: _answering("ok"), timeout=1)
    assert ok["message_i18n"] == {"message": "Connected to the broker.", "params": {}}
    refused = ha_mqtt.probe("ha", 1883, "mate", "bad", client_factory=lambda: _answering("refused"), timeout=1)
    assert refused["message_i18n"]["message"] == refused["message"]


def test_the_mqtt_publisher_status_carries_its_template():
    publisher = ha_mqtt.Publisher.__new__(ha_mqtt.Publisher)
    publisher.host, publisher.port, publisher.connected, publisher.entities, publisher.vehicles = "ha", 1883, False, 0, {}
    publisher.last_publish = None
    publisher._on_fail()
    status = publisher.status()
    assert status["error"] == "Cannot reach ha:1883."
    assert status["error_i18n"] == {"message": "Cannot reach {host}:{port}.", "params": {"host": "ha", "port": 1883}}


def test_an_import_report_carries_templates():
    c, conn, api, vid = connected()
    report = c.post(f"/api/vehicles/{vid}/import/trips", json={"files": [{"name": "a.csv", "text": "nothing;here\n1;2"}]}).json()
    file = report["files"][0]
    assert file["errors_i18n"][0]["message"].startswith("This does not look like a MyŠkoda trip export")
    assert len(file["errors"]) == len(file["errors_i18n"]) and "{columns}" not in file["errors"][0]


def test_quotes_belong_to_the_template_so_each_language_can_use_its_own():
    cases = ((messages.BAD_DATE(day="x1"), "bad date 'x1', expected YYYY-MM-DD"),
             (messages.CMD_UNKNOWN(name="x1"), "unknown command 'x1'"),
             (messages.IMPORT_TIME_ZONE(name="x1"), "Unknown time zone 'x1'. Use a name like Europe/Berlin."),
             (messages.IMPORT_BAD_DATE(line=3, start="a", end="b"), "line 3: unreadable date 'a' / 'b'"))
    for message, english in cases:
        assert str(message) == english
    p, api, conn, clock, vid = poller_setup()
    with pytest.raises(commands.CommandError) as refused:
        commands.build("nonsense", {})
    assert messages.i18n(refused.value)["params"] == {"name": "nonsense"}


def test_a_number_range_is_sent_as_numbers():
    with pytest.raises(commands.CommandError) as refused:
        commands.build("start_climate", {"temperature": 99})
    assert str(refused.value) == "'temperature' must be between 15.5 and 30"
    assert messages.i18n(refused.value)["params"] == {"key": "temperature", "lo": 15.5, "hi": 30}


def test_templates_are_all_listed():
    defined = {value for name, value in vars(messages).items() if isinstance(value, messages.Template)}
    assert defined == set(messages.TEMPLATES) and len(messages.TEMPLATES) == len(set(messages.TEMPLATES))


def test_every_filled_template_gets_exactly_its_placeholders():
    wrong = []
    for path, call in _calls():
        f = call.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "messages" and f.attr.isupper()):
            continue
        expected = set(re.findall(r"\{(\w+)\}", getattr(messages, f.attr)))
        given = {k.arg for k in call.keywords}
        if expected != given or call.args:
            wrong.append((path, call.lineno, f.attr, sorted(expected), sorted(k or "**" for k in given)))
    assert not wrong


def test_every_refusal_the_dashboard_can_show_is_a_template():
    plain = []
    for path, call in _calls():
        if not (isinstance(call.func, ast.Name) and call.func.id == "HTTPException") or path == "messages.py":
            continue
        detail = call.args[1] if len(call.args) > 1 else None
        if not (isinstance(detail, ast.Constant) and detail.value in ENGLISH_ONLY):
            plain.append((path, call.lineno))
    assert not plain
