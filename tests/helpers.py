import copy

from fastapi.testclient import TestClient

from skoda_mate import schema
from skoda_mate.client import ApiError, ApiResult, RateInfo
from skoda_mate.config import Config
from skoda_mate.web import create_app

from .fixtures import BEV


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakeApi:
    """Stands in for SkodaApi: scripted answers, no network. `responses` are consumed in order; the last repeats."""

    def __init__(self, responses=None, clock=None):
        self.responses = list(responses or [copy.deepcopy(BEV)])
        self.calls: list[tuple] = []
        self.operate_error: ApiError | None = None
        self.clock = clock or Clock()
        self.closed = False
        self.remaining = 20

    async def get_vehicle(self, vin, include=None):
        self.calls.append(("get", vin))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, ApiError):
            raise r
        self.remaining -= 1
        return ApiResult(data=copy.deepcopy(r), rate=RateInfo(20, self.remaining, 3000, self.clock()),
                         key_expires_at="2027-06-01T00:00:00Z")

    async def operate(self, vin, operation, body=None, **path_args):
        self.calls.append(("op", vin, operation, body, path_args))
        if self.operate_error:
            raise self.operate_error
        return ApiResult(data={}, rate=RateInfo(20, 10, 3000, self.clock()), status=202)

    async def close(self):
        self.closed = True


def make_app(db_path=":memory:", conn=None, poller=None, api_factory=None, **cfg_kw):
    cfg = Config(db_path=db_path, **cfg_kw)
    conn = conn or schema.connect(db_path)
    return create_app(cfg, conn, poller, api_factory=api_factory or (lambda key: FakeApi())), conn


def client_for(app) -> TestClient:
    return TestClient(app, follow_redirects=False)


def sign_up(c: TestClient, email="me@example.com", password="pw-12345") -> None:
    """Create the first login the way the owner does: with the setup code from the server log."""
    r = c.post("/api/setup/login", json={"email": email, "password": password, "setup_code": c.app.state.setup_code()})
    assert r.status_code == 200, r.text
