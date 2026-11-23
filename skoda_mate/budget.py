"""Request budget per vehicle (the official API allows ~20 requests/hour per VIN; "not final").

The `RateLimit-*` response headers are the authoritative quota. A local ledger of our own calls (persisted
in `api_calls`, so a restart cannot overspend) is the fallback until the first response arrives and a
safety net if a header is ever missing. Background polling may not touch the slots reserved for commands.
"""
from __future__ import annotations

import time
from collections import deque

WINDOW_S = 3600


class RequestBudget:
    def __init__(self, per_hour: int = 20, reserve: int = 4, clock=time.time):
        self.per_hour, self.reserve, self.clock = per_hour, reserve, clock
        self._stamps: deque[float] = deque()
        self._hdr_remaining: int | None = None
        self._hdr_reset_at: float | None = None
        self.limited_until: float = 0.0  # set by a 429: nothing is sent before this

    # -- configuration / persistence
    def configure(self, per_hour: int | None = None, reserve: int | None = None) -> None:
        if per_hour is not None:
            self.per_hour = max(1, min(int(per_hour), 60))
        if reserve is not None:
            self.reserve = max(0, min(int(reserve), self.per_hour - 1))

    def load(self, stamps: list[float]) -> None:
        self._stamps = deque(sorted(stamps))
        self._trim()

    def _trim(self) -> None:
        cutoff = self.clock() - WINDOW_S
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()

    # -- observations
    def spend(self) -> float:
        now = self.clock()
        self._stamps.append(now)
        return now

    def refund(self) -> None:
        """Give back the slot just taken: the request was rejected (401/403) or never reached the API,
        and the documentation says those do not consume quota."""
        if self._stamps:
            self._stamps.pop()

    def observe(self, limit: int | None, remaining: int | None, reset_at: float | None) -> None:
        """Take the API's own word for the quota (headers on every response)."""
        if limit:
            self.per_hour = max(1, int(limit))
            self.reserve = min(self.reserve, self.per_hour - 1)
        if remaining is not None:
            self._hdr_remaining, self._hdr_reset_at = int(remaining), reset_at

    def rate_limited(self, retry_after_s: float | None) -> None:
        self.limited_until = self.clock() + float(retry_after_s if retry_after_s is not None else 300)
        self._hdr_remaining, self._hdr_reset_at = 0, self.limited_until

    # -- decisions
    def used(self) -> int:
        self._trim()
        return len(self._stamps)

    def _slots(self) -> int:
        """Slots the API itself says are left (header), else what our ledger implies."""
        ledger = max(0, self.per_hour - self.used())
        if self._hdr_remaining is None:
            return ledger
        if self._hdr_reset_at is not None and self.clock() >= self._hdr_reset_at:
            return ledger  # the window the header described is over
        return min(ledger, self._hdr_remaining) if self.used() else self._hdr_remaining

    def remaining(self, command: bool = False) -> int:
        if self.clock() < self.limited_until:
            return 0
        s = self._slots()
        return s if command else max(0, s - self.reserve)

    def can_spend(self, command: bool = False) -> bool:
        return self.remaining(command) >= 1

    def wait_s(self, command: bool = False) -> float:
        """0 if a request may go now, else seconds until it may (a good time to sleep until)."""
        if self.can_spend(command):
            return 0.0
        now = self.clock()
        waits = [self.limited_until - now]
        if self._hdr_reset_at is not None:
            waits.append(self._hdr_reset_at - now)
        self._trim()
        if self._stamps:  # the oldest of our calls ages out of the hour
            waits.append(self._stamps[0] + WINDOW_S - now)
        return max(1.0, min(w for w in waits if w > 0) if any(w > 0 for w in waits) else 60.0)

    def status(self) -> dict:
        return {"limit": self.per_hour, "reserve": self.reserve, "used": self.used(),
                "remaining": self.remaining(), "remaining_for_commands": self.remaining(command=True),
                "header_remaining": self._hdr_remaining, "next_free_s": round(self.wait_s()),
                "limited": self.clock() < self.limited_until}
