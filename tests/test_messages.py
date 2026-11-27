import ast
import re
from pathlib import Path

from skoda_mate import messages

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
