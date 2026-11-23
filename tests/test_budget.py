from skoda_mate.budget import RequestBudget


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_ledger_limits_and_command_reserve():
    c = Clock()
    b = RequestBudget(per_hour=20, reserve=4, clock=c)
    for _ in range(16):
        assert b.can_spend()
        b.spend()
    assert not b.can_spend()  # polling stops at 16: four are kept for commands
    assert b.can_spend(command=True)
    for _ in range(4):
        b.spend()
    assert not b.can_spend(command=True)
    c.t += 3601
    assert b.used() == 0 and b.can_spend()


def test_headers_are_authoritative_and_override_the_ledger():
    c = Clock()
    b = RequestBudget(per_hour=20, reserve=4, clock=c)
    b.spend()
    b.observe(limit=20, remaining=5, reset_at=c.t + 1200)  # someone else (the phone app) used the quota
    assert b.remaining() == 1 and b.remaining(command=True) == 5
    b.observe(limit=10, remaining=9, reset_at=c.t + 600)  # the API can change its limit ("not final")
    assert b.per_hour == 10
    c.t += 601  # the window the header described is over: fall back to the ledger
    assert b.remaining(command=True) == 10 - b.used()


def test_429_blocks_everything_until_retry_after():
    c = Clock()
    b = RequestBudget(clock=c)
    b.rate_limited(120)
    assert not b.can_spend() and not b.can_spend(command=True) and 100 < b.wait_s() <= 120
    assert b.status()["limited"]
    c.t += 121
    assert b.can_spend() and b.wait_s() == 0
    b.rate_limited(None)  # no Retry-After: wait a cautious five minutes
    assert 290 < b.wait_s() <= 300


def test_wait_time_and_persistence():
    c = Clock()
    b = RequestBudget(per_hour=5, reserve=1, clock=c)
    for _ in range(4):
        c.t += 60
        b.spend()
    assert not b.can_spend()
    assert 3300 < b.wait_s() <= 3600  # until the oldest call is an hour old
    b2 = RequestBudget(per_hour=5, reserve=1, clock=c)
    b2.load(list(b._stamps))  # a restart forgets nothing
    assert b2.used() == 4 and not b2.can_spend()
    b.configure(per_hour=500)
    assert b.per_hour == 60
