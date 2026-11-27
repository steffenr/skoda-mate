import re
from pathlib import Path

from skoda_mate import languages, store

from .test_web import connected

STATIC = Path(__file__).parent.parent / "skoda_mate" / "static"


def test_settings_list_the_languages_and_the_locale():
    c, conn, api, vid = connected()
    s = c.get("/api/settings").json()
    assert s["languages"] == [{"code": "en", "name": "English", "locale": "en"}, {"code": "de", "name": "Deutsch", "locale": "de"}]
    assert (s["language"], s["locale"]) == ("en", "en")
    assert c.put("/api/settings", json={"language": "de"}).json()["locale"] == "de"


def test_a_language_that_is_not_offered_is_refused():
    c, conn, api, vid = connected()
    r = c.put("/api/settings", json={"language": "xx"})
    assert r.status_code == 400 and r.json()["detail"] == "language must be one of en, de"


def test_a_stored_language_that_is_no_longer_offered_reads_as_english():
    """After a downgrade or a hand edit the dashboard still works and the settings can still be saved."""
    c, conn, api, vid = connected()
    store.set_setting(conn, "language", "xx")
    conn.commit()
    s = c.get("/api/settings").json()
    assert (s["language"], s["locale"]) == ("en", "en")
    assert c.put("/api/settings", json={"units": "mi"}).status_code == 200


def test_every_offered_language_has_a_catalog_and_nothing_else_has():
    source = (STATIC / "i18n.js").read_text(encoding="utf-8")
    block = re.search(r"export const CATALOGS = \{(.*?)\};", source, re.S).group(1)
    catalogs = set(re.findall(r"([A-Za-z_]+): jsonCatalog\('([A-Za-z_]+)'\)", block))
    assert all(key == code for key, code in catalogs)
    assert {key for key, _ in catalogs} | {"en"} == set(languages.BY_CODE)
    assert {p.stem for p in (STATIC / "i18n").glob("*.json")} - {"keys"} == {key for key, _ in catalogs}
