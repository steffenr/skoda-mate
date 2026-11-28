"""The polling loop and command execution against the official MyŠkoda Public API.

One poll is ONE request (all parts come back together), which makes the 20-requests/hour quota workable:
a parked car is read every 20 minutes (3/h), a charging/climatising/driving car every 5 (12/h), and four
slots stay free for commands and the "Refresh now" button. Intervals are tunable in Settings.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

from . import automation, commands, messages, normalise, recorder, store
from .budget import RequestBudget
from .client import ApiError, RateInfo

_LOG = logging.getLogger(__name__)

DEFAULT_IDLE_S = 1200
DEFAULT_ACTIVE_S = 300
MIN_INTERVAL_S = 180  # 20 requests/hour can never be sustained faster than every 180 s
AFTER_COMMAND_S = 45  # a 202 only means "request performed": look again shortly
MAX_BACKOFF_S = 1800


@dataclass
class Runtime:
    vin: str
    vid: int
    budget: RequestBudget
    next_poll: float = 0.0
    last_ok: str | None = None
    last_poll_at: float | None = None
    last_error: str | None = None
    last_error_i18n: dict | None = None  # the template behind last_error, for the dashboard
    error_kind: str | None = None
    blocked: bool = False  # key rejected (401/403): polling stops until the key is replaced
    backoff: int = 60
    active: bool = False
    operation_params: dict[str, list[str]] | None = None  # see normalise.Parsed.operation_params
    operations: list[str] | None = None
    key_expires_at: str | None = None
    part_state: dict = field(default_factory=dict)
    api_errors: list = field(default_factory=list)
    captured_at: str | None = None
    polls: int = 0
    failures: int = 0  # failed readings in a row


class Poller:
    def __init__(self, conn, api, *, spin_getter=None, publisher=None, clock=time.time, utcnow=None):
        self.conn, self.api, self.publisher, self.clock = conn, api, publisher, clock
        self.on_events: Callable[[int, list[dict]], None] | None = None  # MQTT events and webhooks (see cloud.py)
        self.spin_getter = spin_getter or (lambda: "")
        self.utcnow = utcnow or (lambda: time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(self.clock())))
        self.rt: dict[str, Runtime] = {}
        self.wake = asyncio.Event()
        self._stop = False

    # ------------------------------------------------------------------ setup
    def intervals(self) -> tuple[int, int]:
        idle = store.int_setting(self.conn, "poll_idle_s", DEFAULT_IDLE_S, MIN_INTERVAL_S, 6 * 3600)
        active = store.int_setting(self.conn, "poll_active_s", DEFAULT_ACTIVE_S, MIN_INTERVAL_S, 3600)
        return idle, min(active, idle)

    def add_vehicle(self, vin: str, vid: int) -> Runtime:
        b = RequestBudget(clock=self.clock)
        b.configure(reserve=store.int_setting(self.conn, "command_reserve", 4, 0, 10))
        calls = store.recent_calls(self.conn, vid, self.clock() - 3600)
        b.load(calls)
        # A restart is not a reason to ask again: wait the shorter interval since the last request (issue #8).
        first = max(self.clock(), max(calls) + self.intervals()[1]) if calls else self.clock()
        r = self.rt[vin] = Runtime(vin=vin, vid=vid, budget=b, next_poll=first)
        saved = store.load_sections(self.conn, vid)
        if "operations" in saved:
            r.operations = saved["operations"].get("list")
            r.operation_params = saved["operations"].get("params")
        return r

    def remove_vehicle(self, vin: str) -> None:
        self.rt.pop(vin, None)

    def reset_block(self) -> None:
        """A new API key was entered: try again."""
        for r in self.rt.values():
            r.blocked, r.last_error, r.last_error_i18n, r.error_kind, r.next_poll = False, None, None, None, self.clock()
        self.wake.set()

    # ------------------------------------------------------------------ polling
    async def poll(self, vin: str, reason: str = "schedule") -> dict:
        """One request. Returns {ok, error?, kind?}. Never raises for API errors."""
        r = self.rt[vin]
        manual = reason != "schedule"
        wait = r.budget.wait_s(command=manual)
        if wait > 0:
            r.next_poll = self.clock() + wait
            refusal = messages.BUDGET_NEXT_SLOT(seconds=round(wait))
            return {"ok": False, "kind": "budget", "error": str(refusal), "error_i18n": messages.i18n(refusal),
                    "retry_in": round(wait)}
        now = r.budget.spend()
        try:
            res = await self.api.get_vehicle(vin)
        except ApiError as e:
            out = self._failed(r, e, now, "get_vehicle")
            r.failures += 1  # readings only: a refused command says nothing about whether the car can be read
            if r.failures == automation.POLL_FAILURES:
                self._emit(r, [{"event": "poll.failed", "at": self.utcnow(),
                                "data": {"failures": r.failures, "kind": e.kind, "error": r.last_error}}])
            return out
        store.log_call(self.conn, r.vid, now, "get_vehicle", True)
        self._rate(r, res.rate)
        r.key_expires_at = res.key_expires_at or r.key_expires_at
        parsed = normalise.parse(res.data, self.utcnow())
        events = recorder.ingest(self.conn, r.vid, parsed.snapshot)
        store.save_sections(self.conn, r.vid, parsed.sections, parsed.snapshot["ts"])
        store.save_sections(self.conn, r.vid, {
            "operations": {"list": parsed.operations, "params": parsed.operation_params}, "part_state": parsed.part_state, "api_errors": {"list": parsed.errors},
            "raw": res.data}, parsed.snapshot["ts"])
        info = parsed.sections.get("info") or {}
        if info.get("name"):
            recorder.upsert_vehicle(self.conn, vin, info["name"])
        self.conn.commit()
        r.operations, r.part_state, r.api_errors = parsed.operations, parsed.part_state, parsed.errors
        r.operation_params = parsed.operation_params
        r.captured_at, r.last_ok, r.last_poll_at = parsed.captured_at, parsed.snapshot["ts"], now
        r.last_error = r.last_error_i18n = r.error_kind = None
        r.backoff, r.polls, r.failures = 60, r.polls + 1, 0
        r.active = normalise.running_actively(parsed)
        idle, active = self.intervals()
        r.next_poll = self.clock() + (active if r.active else idle)
        if self.publisher:
            try:
                self.publisher.publish_state(vin, parsed.snapshot, parsed.sections)
            except Exception:  # an MQTT hiccup must never stop polling
                _LOG.exception("MQTT publish failed")
        self._emit(r, events)  # after the state, so a consumer of an event sees the car as it is now
        return {"ok": True, "captured_at": parsed.captured_at, "active": r.active}

    def _emit(self, r: Runtime, events: list[dict]) -> None:
        if events and self.on_events:
            try:
                self.on_events(r.vid, events)
            except Exception:  # MQTT or webhooks must never stop polling
                _LOG.exception("could not pass on events")

    def _rate(self, r: Runtime, rate: RateInfo) -> None:
        r.budget.observe(rate.limit, rate.remaining, rate.reset_at())

    def _failed(self, r: Runtime, e: ApiError, now: float, endpoint: str) -> dict:
        counts = e.status not in (401, 403, 0)  # per the docs: 401/403 do not consume quota; network errors never arrived
        if counts:
            store.log_call(self.conn, r.vid, now, endpoint, False, e.kind)
        else:
            r.budget.refund()
        self._rate(r, e.rate)
        why = e.user_msg()
        r.last_error, r.last_error_i18n, r.error_kind = str(why), messages.i18n(why), e.kind
        if e.status in (401, 403) and e.kind in ("api-key-expired", "api-key-not-authorized", "http-401", "http-403"):
            r.blocked = True  # retrying cannot help; the user must fix the key
            r.next_poll = float("inf")
        elif e.status == 429:
            r.budget.rate_limited(e.retry_after)
            r.next_poll = self.clock() + (e.retry_after if e.retry_after is not None else 300)
        else:
            r.backoff = min(r.backoff * 2, MAX_BACKOFF_S)
            r.next_poll = self.clock() + r.backoff
        _LOG.warning("poll failed (%s): %s", e.kind, e)
        return {"ok": False, "kind": e.kind, "error": r.last_error, "error_i18n": r.last_error_i18n, "retryable": e.retryable}

    async def tick(self) -> int:
        """Poll every vehicle that is due. Returns how many requests were attempted."""
        n = 0
        for vin, r in list(self.rt.items()):
            if r.blocked or self.clock() < r.next_poll:
                continue
            if not r.budget.can_spend():
                r.next_poll = self.clock() + r.budget.wait_s()
                continue
            await self.poll(vin)
            n += 1
        return n

    async def run(self) -> None:
        while not self._stop:
            try:
                await self.tick()
            except Exception:
                _LOG.exception("tick failed")
            due = [r.next_poll for r in self.rt.values() if not r.blocked]
            timeout = 30.0 if not due else max(1.0, min(30.0, min(due) - self.clock()))
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=timeout)
            self.wake.clear()

    def stop(self) -> None:
        self._stop = True
        self.wake.set()

    # ------------------------------------------------------------------ commands
    async def run_command(self, vin: str, name: str, params: dict | None = None, source: str = "dashboard") -> dict:
        """Validate, send, log. Raises commands.CommandError for bad input (nothing sent); API failures are
        returned as {ok: False, ...} and logged, so the dashboard can show Škoda's own reason."""
        r = self.rt.get(vin)
        if r is None:
            raise commands.CommandError(messages.CMD_UNKNOWN_VEHICLE)
        commands.check_supported(name, r.operations, params, r.operation_params)
        raw = (store.load_sections(self.conn, r.vid).get("profiles") or None)
        op, body, path_args = commands.build(name, params, spin=self.spin_getter(), raw_profiles=raw)
        wait = r.budget.wait_s(command=True)
        if wait > 0:
            raise commands.CommandError(messages.CMD_BUDGET(minutes=round(wait / 60) or 1))
        now = r.budget.spend()
        try:
            res = await self.api.operate(vin, op, body, **path_args)
        except ApiError as e:
            self._failed(r, e, now, op)
            self._log_command(r, name, params, False, e.user_message(), e.status, e.kind, source)
            return {"ok": False, "kind": e.kind, "error": e.user_message(), "error_i18n": messages.i18n(e.user_msg()),
                    "status": e.status}
        store.log_call(self.conn, r.vid, now, op, True)
        self._rate(r, res.rate)
        self._log_command(r, name, params, True, None, res.status, None, source)
        r.next_poll = min(r.next_poll, self.clock() + AFTER_COMMAND_S)  # look again shortly: 202 = "performed", not "done"
        self.wake.set()
        return {"ok": True, "status": res.status, "refresh_in": AFTER_COMMAND_S}

    def log_rejected(self, vin: str, name: str, params: dict | None, error: str, source: str) -> None:
        """Record a command Mate refused before sending (unsupported, bad value, budget used up). The dashboard shows that
        refusal itself; for commands from MQTT nobody would otherwise see it."""
        r = self.rt.get(vin)
        if r is not None:
            self._log_command(r, name, params, False, error, None, "rejected", source)

    def _log_command(self, r, name, params, ok, error, status, kind, source):
        shown = {k: v for k, v in (params or {}).items() if k != "spin"}
        self.conn.execute("INSERT INTO commands(vehicle_id,name,ok,error,params,http_status,kind,source) VALUES(?,?,?,?,?,?,?,?)",
                          (r.vid, name, int(ok), error, json.dumps(shown) if shown else None, status, kind, source))
        self.conn.execute("INSERT INTO events(vehicle_id,at,kind,detail) VALUES(?,?,?,?)",
                          (r.vid, self.utcnow(), "command", f"{name} {'sent' if ok else 'failed: ' + (error or '')}"))
        self.conn.commit()

    # ------------------------------------------------------------------ status for the dashboard
    def status(self, vin: str) -> dict:
        r = self.rt.get(vin)
        if r is None:
            return {"known": False}
        idle, active = self.intervals()
        return {"known": True, "last_ok": r.last_ok, "captured_at": r.captured_at, "error": r.last_error,
                "error_i18n": r.last_error_i18n,
                "error_kind": r.error_kind, "blocked": r.blocked, "active": r.active, "polls": r.polls,
                "next_poll_in": None if r.next_poll == float("inf") else max(0, round(r.next_poll - self.clock())),
                "interval": {"idle": idle, "active": active}, "budget": r.budget.status(),
                "key_expires_at": r.key_expires_at, "operations": r.operations}
