"""Settings table access and at-rest encryption for the Škoda credentials.

The Škoda password has to be read back (the cloud needs it), so it is encrypted with a per-install
Fernet key kept in `secret.key` next to the database (mode 0600). A copy of the DB alone therefore
leaks nothing usable; the dashboard password is only ever stored as a salted hash (see auth.py).
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .store import del_setting, get_setting, set_setting


class SecretBox:
    def __init__(self, key_path: str | None):
        """`key_path=None` keeps the key in memory only (tests)."""
        self.key_path = key_path
        self.key = self._load_or_create()
        self._f = Fernet(self.key)

    def _load_or_create(self) -> bytes:
        if not self.key_path:
            return Fernet.generate_key()
        p = Path(self.key_path)
        if p.exists():
            return p.read_bytes().strip()
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)  # a data directory Mate creates is private
        key = Fernet.generate_key()
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key

    def encrypt(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        """None when the token was made with another key (e.g. secret.key was lost)."""
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            return None


def save_api_login(conn, box: SecretBox, api_key: str, vins: list[str], spin: str | None = None) -> None:
    """The API key (and S-PIN) are secrets: encrypted at rest. VINs are identifiers: kept readable."""
    set_setting(conn, "skoda_api_key", box.encrypt(api_key))
    set_setting(conn, "skoda_vins", ",".join(vins))
    if spin is not None:
        set_setting(conn, "skoda_spin", box.encrypt(spin) if spin else "")


def load_api_login(conn, box: SecretBox) -> tuple[str, list[str], str] | None:
    key, vins, spin = (get_setting(conn, k) for k in ("skoda_api_key", "skoda_vins", "skoda_spin"))
    if not (key and vins):
        return None
    api_key = box.decrypt(key)
    if api_key is None:  # secret.key was lost: the stored key cannot be read, ask again
        return None
    return api_key, [v for v in vins.split(",") if v], (box.decrypt(spin) if spin else "") or ""


def stored_vins(conn) -> list[str]:
    return [v for v in (get_setting(conn, "skoda_vins", "") or "").split(",") if v]


def clear_api_login(conn) -> None:
    del_setting(conn, "skoda_api_key", "skoda_vins", "skoda_spin")
