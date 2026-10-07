"""Fixtures: the API wired to fakes and an in-memory SQLite database (fresh per test)."""

import pytest
from fakes import FakeNotifier, FakePredictor, FakeWeather
from fastapi.testclient import TestClient

from heatwave_api.app import create_app
from heatwave_api.config import Settings


@pytest.fixture(autouse=True)
def _never_the_real_database(monkeypatch):
    """Any Settings() a test builds gets an in-memory database, never data/local/heatwave.db."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def settings():
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)


@pytest.fixture
def predictor():
    return FakePredictor()


@pytest.fixture
def weather():
    return FakeWeather()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def client(settings, predictor, weather, notifier):
    app = create_app(settings, predictor=predictor, weather=weather, notifier=notifier)
    # raise_server_exceptions=False: exercise the real 500 handler, as a client would see it.
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app_ctx = app.state.ctx
        yield c


@pytest.fixture
def auth(client, settings):
    r = client.post(
        "/api/v1/auth/login",
        json={
            "username": settings.demo_user_username,
            "password": settings.demo_user_password.get_secret_value(),
        },
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
