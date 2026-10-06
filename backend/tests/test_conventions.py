"""Cross-cutting conventions: envelope, errors, request ids, CORS, startup, migrations."""

import json
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from heatwave_api.config import REPO_ROOT, Settings
from heatwave_api.db import Database, MigrationError
from heatwave_api.inference import StartupError
from heatwave_api.main import create_app
from heatwave_api.observability import JsonFormatter
from heatwave_api.services import build_notifier, build_services


def test_every_error_uses_the_envelope(client):
    for response in (
        client.get("/api/v1/nope"),
        client.delete("/api/v1/alerts"),
        client.post(
            "/api/v1/predict", content="not json", headers={"Content-Type": "application/json"}
        ),
    ):
        body = response.json()
        assert set(body) == {"status", "data", "error", "meta"}
        assert body["status"] == "error" and body["data"] is None
        assert body["error"]["code"] and body["error"]["category"] == "client"
    assert client.get("/api/v1/nope").status_code == 404
    assert client.delete("/api/v1/alerts").status_code == 405


def test_an_unexpected_bug_is_a_500_with_a_request_id_and_no_trace(client, monkeypatch):
    def boom(*args, **kwargs):
        raise KeyError("internal detail /srv/secret")

    monkeypatch.setattr("heatwave_api.api.analytics_service.analytics", boom)
    response = client.get("/api/v1/analytics", headers={"X-Request-ID": "trace-me-12345"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text
    assert body["meta"]["request_id"] == "trace-me-12345"
    assert response.headers["X-Request-ID"] == "trace-me-12345"


def test_request_ids_are_echoed_or_generated(client):
    assert (
        client.get("/api/v1/health", headers={"X-Request-ID": "abc-123-xyz"}).headers[
            "X-Request-ID"
        ]
        == "abc-123-xyz"
    )
    generated = client.get("/api/v1/health", headers={"X-Request-ID": "bad id!"})
    assert len(generated.headers["X-Request-ID"]) == 32
    assert generated.json()["meta"]["request_id"] == generated.headers["X-Request-ID"]


def test_cors_allows_only_the_configured_origins(client):
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    }
    allowed = client.options(
        "/api/v1/alerts", headers={"Origin": "http://localhost:5173", **preflight}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options(
        "/api/v1/alerts", headers={"Origin": "http://evil.example", **preflight}
    )
    assert "access-control-allow-origin" not in denied.headers


def test_request_log_is_structured_and_carries_the_risk_class(client, caplog):
    caplog.set_level(logging.INFO, logger="heatwave_api")
    client.post(
        "/api/v1/predict",
        json={"region_id": "mumbai"},
        headers={"Authorization": "Bearer should-never-be-logged"},
    )
    record = next(r for r in caplog.records if r.getMessage() == "request")
    line = json.loads(JsonFormatter().format(record))
    assert line["path"] == "/api/v1/predict" and line["status"] == 201
    assert line["risk_class"] == "NORMAL" and line["region_id"] == "mumbai"
    assert line["model_version"] == "xgboost-test" and line["latency_ms"] >= 0
    assert "should-never-be-logged" not in caplog.text


# -- startup ----------------------------------------------------------------------------


def test_startup_fails_fast_when_the_model_cannot_load(settings):
    def broken(_settings):
        raise StartupError("Cannot load the model or its explainer: no production.json")

    with (
        pytest.raises(StartupError),
        TestClient(create_app(settings, broken, configure_logs=False)),
    ):
        pass


def test_real_startup_names_the_fix_when_the_registry_is_empty(settings, tmp_path):
    empty = settings.model_copy(update={"model_registry_dir": tmp_path / "registry"})
    with pytest.raises(StartupError, match="heatwave-evaluate run"):
        build_services(empty)


def test_production_refuses_the_default_secret(settings, fakes):
    from heatwave_api.services import assemble_services

    prod = settings.model_copy(
        update={"app_env": "production", "auth_secret_key": Settings().auth_secret_key}
    )
    with pytest.raises(StartupError, match="AUTH_SECRET_KEY"):
        assemble_services(prod, model=fakes.model, provider=fakes.forecast, notifier=fakes.notifier)


def test_notifier_modes(settings):
    with pytest.raises(StartupError, match="Part 09"):
        build_notifier(settings.model_copy(update={"notifications_mode": "live"}))
    with pytest.raises(StartupError, match="unknown channel"):
        build_notifier(settings.model_copy(update={"notifications_mock_fail_channels": ["FAX"]}))


def test_settings_validation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, rate_limit_predict="lots")
    with pytest.raises(ValueError, match="SQLite"):
        _ = Settings(_env_file=None, database_url="postgresql://db/heatwave").sqlite_path
    s = Settings(_env_file=None, cors_allowed_origins="http://a.test, http://b.test")
    assert s.cors_allowed_origins == ["http://a.test", "http://b.test"]
    assert s.sqlite_path == REPO_ROOT / "data" / "local" / "heatwave.db"


# -- migrations -------------------------------------------------------------------------


def test_migrations_apply_once_and_enforce_foreign_keys(tmp_path):
    db = Database(tmp_path / "m.db")
    assert db.migrate() == ["0001_initial"]
    assert db.migrate() == []
    assert db.applied() == ["0001_initial"]
    with db.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO weather_snapshots (region_id, date, kind, source, fetched_at) "
                "VALUES ('nowhere', '2026-05-01', 'ACTUAL', 'imd', '2026-05-01T00:00:00+00:00')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                "INSERT INTO regions (id, name, district, state, zone, lat, lon, active) "
                "VALUES ('x', 'X', 'd', 's', 'coastal', 0, 0, 2)"
            )


def test_an_edited_applied_migration_is_refused(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_a.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    db = Database(tmp_path / "m.db", migrations)
    db.migrate()
    (migrations / "0001_a.sql").write_text("CREATE TABLE a (y INTEGER);", encoding="utf-8")
    with pytest.raises(MigrationError, match="changed"):
        db.migrate()


def test_a_failing_migration_leaves_nothing_behind(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_a.sql").write_text(
        "CREATE TABLE a (x INTEGER);\nCREATE TABLE a (x INTEGER);", encoding="utf-8"
    )
    db = Database(tmp_path / "m.db", migrations)
    with pytest.raises(MigrationError, match="0001_a"):
        db.migrate()
    with db.connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" not in tables
    assert db.applied() == []
