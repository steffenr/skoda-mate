import pytest

from skoda_mate import auth


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1000)  # PBKDF2 at production cost makes the suite crawl
