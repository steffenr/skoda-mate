"""Dashboard login: e-mail + password chosen in the browser, stored as a salted PBKDF2 hash,
signed session cookie, brute-force throttle. Stdlib only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import time

from .secrets_store import get_setting, set_setting

SESSION_TTL = 14 * 86400
COOKIE = "skoda_mate_session"
MAX_FAILS, WINDOW_S = 5, 300
# Behind a reverse proxy all clients may share one address, and a guesser can rotate addresses. A global cap across all
# addresses stops both and bounds the memory (worst case: everyone waits five minutes).
GLOBAL_MAX_FAILS, MAX_TRACKED_IPS = 30, 1000
MIN_PASSWORD = 8
# No "|": it separates the fields of a session token. Domain labels exclude "." so the match cannot backtrack (ReDoS).
EMAIL_RE = re.compile(r"[^\s@|]+@[^\s@|.]+(?:\.[^\s@|.]+)+")
SETUP_CODE_ALPHABET, SETUP_CODE_LEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 10  # no 0/O or 1/I: read off a log, typed by hand
ITERATIONS = 200_000  # tests lower this


class SetupError(ValueError):
    pass


def hash_password(password: str, iterations: int | None = None) -> str:
    n = iterations or ITERATIONS
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, n)
    return f"pbkdf2${n}${salt.hex()}${dk.hex()}"


def new_setup_code() -> str:
    """One-time code (~50 bits) that creating the first login from a public address requires. Only the server log and
    setup-code.txt in the data folder show it, so a stranger who reaches a fresh install first cannot claim it."""
    return "".join(secrets.choice(SETUP_CODE_ALPHABET) for _ in range(SETUP_CODE_LEN))


def normalise_setup_code(code: str | None) -> str:
    return re.sub(r"[\s-]", "", code or "").upper()


PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                                                  "::1/128", "fc00::/7", "fe80::/10")]


def is_private_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip().strip("[]").split("%")[0])
    except ValueError:
        return False  # not an address (unknown): treat as public
    ip = getattr(ip, "ipv4_mapped", None) or ip
    return any(ip in n for n in PRIVATE_NETS)


def from_private_network(client_host: str | None, forwarded_for: str | None = None) -> bool:
    """Home network or this machine? A proxy forwarding a public client (X-Forwarded-For) makes the request public,
    even though the proxy itself connects from a private address. Every listed address counts, not just the first: a
    client can send its own X-Forwarded-For: 192.168.x.x, and a proxy appends the real address after it."""
    hosts = [client_host or ""] + (forwarded_for.split(",") if forwarded_for else [])
    return all(is_private_address(h) for h in hosts)


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(n))
        return hmac.compare_digest(got, bytes.fromhex(dk))
    except Exception:
        return False


class Auth:
    """`secret` is the per-install key; the token key also depends on the password hash and a session generation, so
    changing the password, or signing out (which bumps the generation), invalidates every session."""

    def __init__(self, secret: bytes, conn=None):
        self.secret = secret
        self.email = ""
        self._hash = ""
        self._gen = "0"
        self._fails: dict[str, list[float]] = {}
        self._all_fails: list[float] = []
        self._dummy = hash_password("x")  # so a wrong e-mail costs the same time as a wrong password
        self._conn, self._loaded_at = conn, time.monotonic()
        if conn is not None:
            self.load(conn)

    @property
    def enabled(self) -> bool:
        self._refresh()  # a login created on the command line counts without a restart
        return bool(self.email and self._hash)

    def load(self, conn) -> None:
        self.email = get_setting(conn, "auth_email", "") or ""
        self._hash = get_setting(conn, "auth_hash", "") or ""
        self._gen = get_setting(conn, "auth_session_gen", "0") or "0"

    def _refresh(self) -> None:
        """Pick up a password reset done from the command line while the server runs (at most once per second)."""
        if self._conn is not None and time.monotonic() - self._loaded_at > 1:
            self._loaded_at = time.monotonic()
            self.load(self._conn)

    def set_credentials(self, conn, email: str, password: str) -> None:
        email = email.strip().lower()
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            raise SetupError("Enter a valid e-mail address.")
        if len(password) < MIN_PASSWORD:
            raise SetupError(f"The password needs at least {MIN_PASSWORD} characters.")
        h = hash_password(password)
        set_setting(conn, "auth_email", email)
        set_setting(conn, "auth_hash", h)
        self.email, self._hash = email, h

    def revoke_sessions(self, conn) -> None:
        """Sign every session out, in all browsers: a new generation changes the token key."""
        self._gen = str(int(self._gen or 0) + 1)
        set_setting(conn, "auth_session_gen", self._gen)

    def check(self, email: str, password: str) -> bool:
        self._refresh()
        if not self.enabled:
            verify_password(password, self._dummy)
            return False
        ok_e = hmac.compare_digest(email.strip().lower().encode(), self.email.encode())
        ok_p = verify_password(password, self._hash)
        return ok_e and ok_p  # both are always evaluated

    def _prune(self, now: float) -> None:
        for ip in [ip for ip, ts in self._fails.items() if not ts or now - ts[-1] >= WINDOW_S]:
            del self._fails[ip]
        self._all_fails = [t for t in self._all_fails if now - t < WINDOW_S][-GLOBAL_MAX_FAILS:]

    def locked(self, ip: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self._prune(now)
        recent = [t for t in self._fails.get(ip, []) if now - t < WINDOW_S]
        if recent:
            self._fails[ip] = recent
        return len(recent) >= MAX_FAILS or len(self._all_fails) >= GLOBAL_MAX_FAILS

    def fail(self, ip: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if ip not in self._fails and len(self._fails) >= MAX_TRACKED_IPS:
            self._fails.pop(next(iter(self._fails)))  # forget the oldest address; the global cap still holds
        self._fails.setdefault(ip, []).append(now)
        self._all_fails.append(now)

    def clear(self, ip: str) -> None:
        self._fails.pop(ip, None)

    def _sig(self, payload: str) -> str:
        key = hashlib.sha256(self.secret + b"\0" + self._hash.encode() + b"\0" + self._gen.encode()).digest()
        return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

    def make_token(self, now: float | None = None) -> str:
        exp = int((time.time() if now is None else now) + SESSION_TTL)
        payload = base64.urlsafe_b64encode(f"{self.email}|{exp}".encode()).decode()
        return f"{payload}.{self._sig(payload)}"

    def valid_token(self, token: str | None, now: float | None = None) -> bool:
        self._refresh()
        if not self.enabled or not token or "." not in token:
            return False
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sig(payload)):
            return False
        try:
            email, exp = base64.urlsafe_b64decode(payload.encode()).decode().split("|")
            return email == self.email and int(exp) > (time.time() if now is None else now)
        except Exception:
            return False
