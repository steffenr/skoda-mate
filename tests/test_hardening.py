import csv
import io
import os
import stat
import sys

import pytest

from skoda_mate import schema
from skoda_mate.presenters import csv_cell
from skoda_mate.secrets_store import SecretBox

from .test_web import connected, seed_trip

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def test_csv_cell_neutralises_formulas_but_keeps_numbers():
    for bad in ("=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tx", "\rx"):
        assert csv_cell(bad) == "'" + bad
    assert csv_cell("Home") == "Home" and csv_cell("") == "" and csv_cell(None) == ""
    assert csv_cell(-12.5) == -12.5 and csv_cell(-3) == -3 and csv_cell(0) == 0


def test_export_escapes_formula_text_in_notes():
    c, conn, api, vid = connected()
    seed_trip(conn, vid)
    conn.execute("UPDATE trips SET note=?, start_place=? WHERE vehicle_id=?", ('=HYPERLINK("http://evil","x")', "@cmd", vid))
    conn.commit()
    rows = list(csv.DictReader(io.StringIO(c.get(f"/api/vehicles/{vid}/export/trips.csv").text)))
    assert rows[0]["note"] == '\'=HYPERLINK("http://evil","x")' and rows[0]["start_place"] == "'@cmd"
    assert rows[0]["distance_km"] == "40.0"


@posix_only
def test_new_data_dir_is_private_and_db_is_0600(tmp_path):
    old = os.umask(0o022)
    try:
        db = tmp_path / "data" / "skoda_mate.db"
        conn = schema.connect(str(db))
        conn.close()
        SecretBox(str(db.with_name("secret.key")))
    finally:
        os.umask(old)
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.with_name("secret.key").stat().st_mode) == 0o600


@posix_only
def test_existing_world_readable_db_is_tightened(tmp_path):
    db = tmp_path / "skoda_mate.db"
    schema.connect(str(db)).close()
    os.chmod(db, 0o644)
    schema.connect(str(db)).close()
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_memory_db_is_untouched():
    schema.connect(":memory:").close()
