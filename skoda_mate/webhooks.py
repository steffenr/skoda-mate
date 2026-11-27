"""Webhooks: signed JSON sent to the user's own URL when something happens.

Every delivery is a row first, so one that is waiting survives a restart. The `Worker` sends the rows that are due,
one queue per webhook, so a receiver that hangs holds up only itself. Delivery is at least once: a receiver
recognises a repeat by `X-Skoda-Mate-Delivery`.

The signing secret is stored encrypted, is shown when it is made and never again, and is never logged. The URL is
not a secret, which is why one with a user name or password in it is refused.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from . import __version__, messages
from .automation import EVENT_TYPES
from .secrets_store import SecretBox

_LOG = logging.getLogger(__name__)

TIMEOUT_S = 10.0
RETRY_DELAYS_S = (60, 300, 900, 3600, 6 * 3600)  # after the first attempt; then the delivery is given up
KEEP_DAYS = 30
LISTED = 20
NAME_MAX, URL_MAX = 60, 2000
IDLE_S = 5.0  # how often the worker looks for a retry that has become due
TEST_EVENT = "test"

NO_ANSWER = messages.WEBHOOK_NO_ANSWER
NO_CONNECTION = messages.WEBHOOK_NO_CONNECTION
REDIRECTED = messages.WEBHOOK_REDIRECTED
NO_SECRET = messages.WEBHOOK_NO_SECRET
DISABLED = messages.WEBHOOK_DISABLED
INTERRUPTED = messages.WEBHOOK_INTERRUPTED
BAD_NAME = messages.WEBHOOK_NAME
BAD_URL = messages.WEBHOOK_URL
URL_LOGIN = messages.WEBHOOK_URL_LOGIN
BAD_EVENTS = messages.WEBHOOK_EVENTS
ENABLE_FIRST = messages.WEBHOOK_ENABLE_FIRST
ALREADY_WAITING = messages.WEBHOOK_ALREADY_WAITING

_DELIVERY_COLUMNS = "id, webhook_id, event, status, attempts, next_at, last_code, last_error, created_at"


class WebhookError(ValueError):
    """A request the user can correct; the message is shown to them."""


class WebhookNotFound(WebhookError):
    def __init__(self):
        super().__init__(messages.WEBHOOK_NOT_FOUND)


# ------------------------------------------------------------------ the store
def validate(data: dict) -> dict:
    name = str(data.get("name") or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise WebhookError(BAD_NAME)
    url = str(data.get("url") or "").strip()
    if len(url) > URL_MAX or any(c.isspace() or ord(c) < 32 for c in url):
        raise WebhookError(BAD_URL)
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises for a port out of range
        host, login = parts.hostname, parts.username or parts.password
        httpx.URL(url)  # what will send it must be able to read it
    except (ValueError, httpx.InvalidURL):
        raise WebhookError(BAD_URL) from None
    if parts.scheme not in ("http", "https") or not host:
        raise WebhookError(BAD_URL)
    if login:
        raise WebhookError(URL_LOGIN)
    chosen = data.get("events")
    if not isinstance(chosen, list) or not chosen or any(e not in EVENT_TYPES for e in chosen):
        raise WebhookError(BAD_EVENTS)
    return {"name": name, "url": url, "events": [e for e in EVENT_TYPES if e in chosen],
            "enabled": bool(data.get("enabled", True))}


def _row(conn, webhook_id: int):
    row = conn.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
    if row is None:
        raise WebhookNotFound()
    return row


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds")


def _delivery(row) -> dict:
    out = dict(row)
    out["created_at"] = _iso(out["created_at"])
    out["next_at"] = _iso(out["next_at"]) if out["status"] == "pending" else None
    return out


def _view(conn, box: SecretBox, row) -> dict:
    """What the dashboard and the API may see: everything but the secret."""
    last = conn.execute(f"SELECT {_DELIVERY_COLUMNS} FROM webhook_deliveries WHERE webhook_id=? ORDER BY id DESC LIMIT 1",
                        (row["id"],)).fetchone()
    return {"id": row["id"], "name": row["name"], "url": row["url"], "events": json.loads(row["events"]),
            "enabled": bool(row["enabled"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
            "secret_unreadable": box.decrypt(row["secret_enc"]) is None,
            "last_delivery": _delivery(last) if last else None}


def listing(conn, box: SecretBox) -> list[dict]:
    return [_view(conn, box, r) for r in conn.execute("SELECT * FROM webhooks ORDER BY id").fetchall()]


def create(conn, box: SecretBox, data: dict) -> tuple[dict, str]:
    """Store a new webhook. Returns it and its secret: this is the only time the secret leaves the server."""
    clean = validate(data)
    secret = secrets.token_urlsafe(32)
    cur = conn.execute("INSERT INTO webhooks(name,url,secret_enc,events,enabled) VALUES(?,?,?,?,?)",
                       (clean["name"], clean["url"], box.encrypt(secret), json.dumps(clean["events"]), int(clean["enabled"])))
    conn.commit()
    return _view(conn, box, _row(conn, int(cur.lastrowid or 0))), secret


def update(conn, box: SecretBox, webhook_id: int, data: dict) -> dict:
    _row(conn, webhook_id)
    clean = validate(data)
    conn.execute("UPDATE webhooks SET name=?, url=?, events=?, enabled=?, "
                 "updated_at=strftime('%Y-%m-%dT%H:%M:%S+00:00','now') WHERE id=?",
                 (clean["name"], clean["url"], json.dumps(clean["events"]), int(clean["enabled"]), webhook_id))
    if not clean["enabled"]:
        _drop_waiting(conn, webhook_id)
    conn.commit()
    return _view(conn, box, _row(conn, webhook_id))


def _drop_waiting(conn, webhook_id: int) -> None:
    """A disabled webhook must not send old events when it is enabled again."""
    conn.execute("UPDATE webhook_deliveries SET status='failed', last_error=? WHERE webhook_id=? AND status='pending'",
                 (DISABLED, webhook_id))


def delete(conn, webhook_id: int) -> None:
    _row(conn, webhook_id)
    conn.execute("DELETE FROM webhook_deliveries WHERE webhook_id=?", (webhook_id,))
    conn.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))
    conn.commit()


def rotate(conn, box: SecretBox, webhook_id: int) -> str:
    _row(conn, webhook_id)
    secret = secrets.token_urlsafe(32)
    conn.execute("UPDATE webhooks SET secret_enc=? WHERE id=?", (box.encrypt(secret), webhook_id))
    conn.commit()
    return secret


def deliveries(conn, webhook_id: int, limit: int = LISTED) -> list[dict]:
    _row(conn, webhook_id)
    found = conn.execute(f"SELECT {_DELIVERY_COLUMNS} FROM webhook_deliveries WHERE webhook_id=? ORDER BY id DESC LIMIT ?",
                         (webhook_id, limit)).fetchall()
    return [_delivery(r) for r in found]


def _one_delivery(conn, delivery_id: int) -> dict:
    row = conn.execute(f"SELECT {_DELIVERY_COLUMNS} FROM webhook_deliveries WHERE id=?", (delivery_id,)).fetchone()
    if row is None:
        raise WebhookNotFound()
    return _delivery(row)


def retry(conn, delivery_id: int, now: float) -> dict:
    """Queue a finished delivery again, with the same id and body and a fresh set of attempts."""
    found = _one_delivery(conn, delivery_id)
    if not _row(conn, found["webhook_id"])["enabled"]:
        raise WebhookError(ENABLE_FIRST)
    if found["status"] not in ("ok", "failed"):
        raise WebhookError(ALREADY_WAITING)
    conn.execute("UPDATE webhook_deliveries SET status='pending', attempts=0, next_at=?, last_code=NULL, last_error=NULL "
                 "WHERE id=?", (now, delivery_id))
    conn.commit()
    return _one_delivery(conn, delivery_id)


# ------------------------------------------------------------------ queueing and sending
def body_of(event: dict) -> str:
    return json.dumps({"version": 1, "event": event["event"], "at": event["at"], "vehicle": event["vehicle"],
                       "data": event["data"]}, ensure_ascii=False, separators=(",", ":"))


def _insert(conn, webhook_id: int, event: dict, status: str, now: float) -> int:
    cur = conn.execute("INSERT INTO webhook_deliveries(webhook_id,event,payload,status,next_at,created_at) "
                       "VALUES(?,?,?,?,?,?)", (webhook_id, event["event"], body_of(event), status, now, now))
    return int(cur.lastrowid or 0)


def enqueue(conn, events: list[dict], now: float) -> int:
    """One pending delivery per event and enabled webhook that subscribed to it. Returns how many."""
    hooks = conn.execute("SELECT id, events FROM webhooks WHERE enabled=1 ORDER BY id").fetchall()
    n = 0
    for event in events:
        for hook in hooks:
            if event["event"] in json.loads(hook["events"]):
                _insert(conn, hook["id"], event, "pending", now)
                n += 1
    conn.commit()
    return n


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Worker:
    """Sends the deliveries that are due. Runs on the app's event loop; `wake()` may be called from any thread."""

    def __init__(self, conn, box: SecretBox, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.time):
        self.conn, self.box, self.transport, self.clock = conn, box, transport, clock
        self._http: httpx.AsyncClient | None = None
        self._queues: dict[int, asyncio.Task] = {}  # webhook id -> the task sending its due deliveries
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    # ---- lifecycle
    def start(self) -> bool:
        """True when this call started it; only that caller (on the same event loop) may `stop()` it."""
        if self._task:
            return False
        self.conn.execute("UPDATE webhook_deliveries SET status='failed', last_error=? WHERE status='sending'",
                          (INTERRUPTED,))
        self.conn.commit()
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        self._task = asyncio.create_task(self._run())
        return True

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        """What is still pending stays pending and is sent by the next start."""
        running = [t for t in [self._task, *self._queues.values()] if t]
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        self._task, self._queues, self._loop, self._wake = None, {}, None, None
        if self._http:
            await self._http.aclose()
            self._http = None

    def wake(self) -> None:
        loop, wake = self._loop, self._wake
        if loop and wake and not loop.is_closed():
            loop.call_soon_threadsafe(wake.set)

    async def _run(self) -> None:
        wake = self._wake
        assert wake is not None
        while True:
            wake.clear()
            try:
                self._start_due()
            except Exception:
                _LOG.exception("webhook worker")
            with suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=IDLE_S)

    async def run_once(self) -> None:
        """Send everything that is due now and wait for it."""
        self._start_due()
        await asyncio.gather(*self._queues.values())

    # ---- sending
    def _start_due(self) -> None:
        now = self.clock()
        oldest = now - KEEP_DAYS * 86400
        # Write only when there is something to prune: this runs every few seconds on the connection everyone shares,
        # and a commit would also save whatever another writer has half done.
        if self.conn.execute("SELECT 1 FROM webhook_deliveries WHERE created_at<? LIMIT 1", (oldest,)).fetchone():
            self.conn.execute("DELETE FROM webhook_deliveries WHERE created_at<?", (oldest,))
            self.conn.commit()
        due = self.conn.execute("SELECT DISTINCT d.webhook_id id FROM webhook_deliveries d JOIN webhooks w "
                                "ON w.id=d.webhook_id WHERE w.enabled=1 AND d.status='pending' AND d.next_at<=?",
                                (now,)).fetchall()
        for row in due:
            task = self._queues.get(row["id"])
            if task is None or task.done():
                self._queues[row["id"]] = asyncio.create_task(self._drain(row["id"]))

    async def _drain(self, webhook_id: int) -> None:
        try:
            while True:
                row = self.conn.execute(
                    "SELECT d.*, w.url, w.secret_enc FROM webhook_deliveries d JOIN webhooks w ON w.id=d.webhook_id "
                    "WHERE d.webhook_id=? AND w.enabled=1 AND d.status='pending' AND d.next_at<=? ORDER BY d.id LIMIT 1",
                    (webhook_id, self.clock())).fetchone()
                if row is None:
                    return
                await self._deliver(dict(row), retries=True)
        except Exception:
            _LOG.exception("webhook %s: sending failed", webhook_id)

    async def _post(self, row: dict) -> tuple[int | None, str | None]:
        """One attempt: (HTTP status or None, why it failed or None). The answer's body is never read."""
        secret = self.box.decrypt(row["secret_enc"])
        if secret is None:
            return None, NO_SECRET  # never send unsigned
        body = row["payload"].encode()
        headers = {"Content-Type": "application/json", "User-Agent": f"skoda-mate/{__version__}",
                   "X-Skoda-Mate-Event": row["event"], "X-Skoda-Mate-Delivery": str(row["id"]),
                   "X-Skoda-Mate-Signature": sign(secret, body)}
        if self._http is None:
            self._http = httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT_S, follow_redirects=False)
        try:
            async with asyncio.timeout(TIMEOUT_S):  # the whole attempt, however slowly the receiver trickles
                async with self._http.stream("POST", row["url"], content=body, headers=headers) as answer:
                    code = answer.status_code
        except (TimeoutError, httpx.TimeoutException):
            return None, NO_ANSWER
        except Exception as e:  # refused, unknown host, TLS: the type is enough, the text could quote the request
            _LOG.info("webhook delivery %s: %s", row["id"], type(e).__name__)
            return None, NO_CONNECTION
        return code, REDIRECTED if 300 <= code < 400 else None

    async def _deliver(self, row: dict, retries: bool) -> None:
        code, error = await self._post(row)
        attempts = row["attempts"] + 1
        ok = code is not None and 200 <= code < 300
        gone = code == 410
        final = error == NO_SECRET or gone or (code is not None and 400 <= code < 500 and code not in (408, 429))
        status, next_at = "ok" if ok else "failed", row["next_at"]
        if not ok and not final and retries and attempts <= len(RETRY_DELAYS_S):
            status, next_at = "pending", self.clock() + RETRY_DELAYS_S[attempts - 1]
        # Only a row that is still ours: disabling the webhook while it was on its way has already closed it.
        self.conn.execute("UPDATE webhook_deliveries SET status=?, attempts=?, next_at=?, last_code=?, last_error=? "
                          "WHERE id=? AND status=?", (status, attempts, next_at, code, error, row["id"], row["status"]))
        if gone:
            self.conn.execute("UPDATE webhooks SET enabled=0 WHERE id=?", (row["webhook_id"],))
            _drop_waiting(self.conn, row["webhook_id"])
            _LOG.warning("webhook %s disabled: the receiver answered 410 Gone", row["webhook_id"])
        self.conn.commit()

    async def send_test(self, webhook_id: int) -> dict:
        """Send a test event now, once, also to a disabled webhook, and return how it went."""
        _row(self.conn, webhook_id)
        car = self.conn.execute("SELECT id, name, vin FROM vehicles ORDER BY id LIMIT 1").fetchone()
        event = {"event": TEST_EVENT, "at": _iso(self.clock()),
                 "vehicle": {"id": car["id"], "name": car["name"] or car["vin"], "vin": car["vin"]} if car else None,
                 "data": {"message": "Test delivery from Škoda Mate"}}
        delivery_id = _insert(self.conn, webhook_id, event, "sending", self.clock())
        self.conn.commit()
        row = self.conn.execute("SELECT d.*, w.url, w.secret_enc FROM webhook_deliveries d JOIN webhooks w "
                                "ON w.id=d.webhook_id WHERE d.id=?", (delivery_id,)).fetchone()
        await self._deliver(dict(row), retries=False)
        return _one_delivery(self.conn, delivery_id)
