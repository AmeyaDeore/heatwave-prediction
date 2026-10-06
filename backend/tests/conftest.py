"""Fixtures: the real app and the real startup (migrations, region sync, model
metadata) around a fake model, a fake forecast source and the mock notifier.

Each test gets its own SQLite file, so tests are independent and need no cleanup.
"""

import pytest
from api_support import PASSWORD, Clock, FakeForecast, FakeModel
from fastapi.testclient import TestClient

from heatwave_api.config import Settings
from heatwave_api.db.repository import Repository
from heatwave_api.main import create_app
from heatwave_api.notifications import MockNotifier
from heatwave_api.security import hash_password
from heatwave_api.services import assemble_services


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        rate_limit_predict="1000/minute",
        rate_limit_alert_writes="1000/minute",
        rate_limit_login="1000/minute",
        notifications_mock_fail_channels=[],
        auth_secret_key="test-secret-key-that-is-long-enough-123",  # pragma: allowlist secret
    )


@pytest.fixture
def fakes():
    class Fakes:
        model = FakeModel()
        forecast = FakeForecast()
        notifier = MockNotifier()
        clock = Clock()

    return Fakes()


@pytest.fixture
def make_client(settings, fakes):
    """make_client(**setting_overrides) -> a started TestClient (lifespan runs)."""
    clients = []

    def make(**overrides) -> TestClient:
        s = settings.model_copy(update=overrides)

        def factory(s_):
            return assemble_services(
                s_,
                model=fakes.model,
                provider=fakes.forecast,
                notifier=fakes.notifier,
                weather_clock=fakes.clock,
            )

        client = TestClient(create_app(s, factory, configure_logs=False))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def repo(client) -> Repository:
    services = client.app.state.services
    with services.db.connect() as conn:
        yield Repository(conn)


@pytest.fixture
def user(repo) -> dict:
    repo.create_user("officer", hash_password(PASSWORD), "Duty Officer")
    return repo.user_by_username("officer")


@pytest.fixture
def auth(client, user) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": "officer", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}
