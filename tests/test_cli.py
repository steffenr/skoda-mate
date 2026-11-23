import time

from skoda_mate import __main__ as cli
from skoda_mate import auth, schema


def _db(tmp_path):
    path = str(tmp_path / "m.db")
    conn = schema.connect(path)
    a = auth.Auth(b"k", conn)
    a.set_credentials(conn, "me@example.com", "old-password-1")
    return path, conn


def answers(*given):
    it = iter(given)
    return lambda prompt: next(it)


def test_reset_keeps_the_email_and_sets_the_new_password(tmp_path):
    path, _ = _db(tmp_path)
    out = []
    assert cli.reset_password(None, path, ask=answers("new-password-2", "new-password-2"), say=out.append) == 0
    a = auth.Auth(b"k", schema.connect(path))
    assert a.check("me@example.com", "new-password-2") and not a.check("me@example.com", "old-password-1")
    assert not any("new-password-2" in line for line in out)  # the password is never printed


def test_reset_rejects_mismatch_and_short_passwords_then_gives_up(tmp_path):
    path, _ = _db(tmp_path)
    assert cli.reset_password(None, path, ask=answers("aaaaaaaa1", "bbbbbbbb2", "short", "short", "x", "y"), say=lambda *_: None) == 1
    assert auth.Auth(b"k", schema.connect(path)).check("me@example.com", "old-password-1")  # untouched


def test_reset_can_change_the_email_or_create_the_first_login(tmp_path):
    path, _ = _db(tmp_path)
    assert cli.reset_password("New@Example.com", path, ask=answers("another-pass-3", "another-pass-3"), say=lambda *_: None) == 0
    assert auth.Auth(b"k", schema.connect(path)).check("new@example.com", "another-pass-3")
    empty = str(tmp_path / "empty.db")
    assert cli.reset_password(None, empty, ask=answers(), say=lambda *_: None) == 2  # no login and no --email


def test_a_running_server_notices_the_reset_and_signs_old_sessions_out(tmp_path):
    path, conn = _db(tmp_path)
    live = auth.Auth(b"k", conn)
    token = live.make_token()
    assert live.valid_token(token)
    cli.reset_password(None, path, ask=answers("new-password-2", "new-password-2"), say=lambda *_: None)
    live._loaded_at = time.monotonic() - 5  # the refresh is throttled to once per second
    assert not live.valid_token(token)
    assert live.check("me@example.com", "new-password-2") and not live.check("me@example.com", "old-password-1")
