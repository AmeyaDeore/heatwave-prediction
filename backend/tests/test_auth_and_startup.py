from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakePredictor, FakeWeather
from fastapi.testclient import TestClient
from pydantic import SecretStr

from heatwave_api.app import create_app
from heatwave_api.auth import TokenService, User, hash_password, verify_password
from heatwave_api.config import Settings
from heatwave_api.errors import ModelUnavailable, Unauthorized


def login(client, username, password):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_login_returns_a_token_that_opens_me(client, auth):
    me = client.get("/api/v1/auth/me", headers=auth).json()["data"]
    assert me["username"] == "official"
    assert "password" not in str(me)


def test_wrong_password_and_unknown_user_give_the_same_answer(client):
    wrong = login(client, "official", "nope")
    unknown = login(client, "nobody", "nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_is_rate_limited(client):
    limit = client.app_ctx.settings.rate_limit_login_per_minute
    codes = [login(client, "official", "nope").status_code for _ in range(limit + 1)]
    assert codes[-1] == 429


def test_me_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_hashes_are_salted_and_verify():
    a, b = hash_password("s3cret"), hash_password("s3cret")
    assert a != b
    assert verify_password("s3cret", a)
    assert not verify_password("other", a)


def _user():
    return User("u1", "x", "X", "official", "h")


def test_tokens_expire_and_reject_tampering():
    tokens = TokenService("k" * 32, ttl_minutes=60)
    now = datetime.now(UTC)
    token, _ = tokens.issue(_user(), now)
    assert tokens.verify(token, now + timedelta(minutes=59)) == "u1"
    with pytest.raises(Unauthorized, match="expired"):
        tokens.verify(token, now + timedelta(minutes=61))
    body, sig = token.split(".")
    with pytest.raises(Unauthorized):
        tokens.verify(f"{body}.{sig[:-2]}xx", now)
    with pytest.raises(Unauthorized):
        TokenService("different-secret" * 2, 60).verify(token, now)
    with pytest.raises(Unauthorized):
        tokens.verify("garbage", now)


def test_liveness_is_independent_of_the_model(client):
    assert client.get("/health").json()["status"] == "ok"


def test_readiness_reports_model_and_data(client):
    data = client.get("/api/v1/health/ready").json()["data"]
    assert data["ready"] is True
    assert data["model_version"] == "fake-model-v1"
    assert data["weather_data"] == "ok"


def test_readiness_is_503_when_weather_is_unavailable(client, weather):
    weather.fail = True
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["data"]["weather_data"] == "unavailable"


def test_startup_fails_fast_when_the_model_cannot_load(tmp_path):
    settings = Settings(app_env="test", model_registry_dir=tmp_path, _env_file=None)
    app = create_app(settings, weather=FakeWeather())
    with pytest.raises(ModelUnavailable, match="production model"), TestClient(app):
        pass


def test_startup_refuses_the_default_secret_outside_local():
    settings = Settings(app_env="production", _env_file=None)
    app = create_app(settings, predictor=FakePredictor(), weather=FakeWeather())
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"), TestClient(app):
        pass


def test_no_demo_user_exists_outside_local_and_test():
    settings = Settings(app_env="staging", auth_secret_key=SecretStr("x" * 40), _env_file=None)
    app = create_app(settings, predictor=FakePredictor(), weather=FakeWeather())
    with TestClient(app) as c:
        assert login(c, "official", "demo-official-local").status_code == 401
