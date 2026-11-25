"""Command line helpers:  python -m skoda_mate reset-password [--email you@example.com]

Resets the dashboard login (the one you chose in the browser) when the password is forgotten. It works on the
database directly, so run it where the data lives (DDEV: `ddev exec ...`, Docker: `docker compose exec mate ...`).
The password is only ever read from a hidden prompt, never from an argument, so it stays out of the shell history."""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth, schema
from .config import Config
from .store import get_setting


def reset_password(email: str | None, db_path: str, ask=getpass.getpass, say=print) -> int:
    conn = schema.connect(db_path)
    current = get_setting(conn, "auth_email", "") or ""
    email = (email or current).strip().lower()
    if not email:
        say("No login exists yet. Run again with --email you@example.com to create one.")
        return 2
    a = auth.Auth(b"cli")
    for _ in range(3):
        pw = ask(f"New password for {email}: ")
        if ask("Repeat the password: ") != pw:
            say("The two entries differ, try again.")
            continue
        try:
            a.set_credentials(conn, email, pw)
        except auth.SetupError as e:
            say(str(e))
            continue
        say(f"Done. {email} can sign in with the new password now. All other sessions were signed out.")
        return 0
    say("Nothing was changed.")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skoda_mate", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("reset-password", help="set a new dashboard password")
    rp.add_argument("--email", help="sign-in e-mail (default: the current one; needed only to change it or to create the login)")
    args = ap.parse_args(argv)
    cfg = Config.from_env()
    return reset_password(args.email, cfg.db_path)


if __name__ == "__main__":
    sys.exit(main())
