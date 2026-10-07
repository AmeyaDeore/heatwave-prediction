"""Part 08: schema, migrations, constraints, persistence across restarts, and the CLI."""

import sqlite3
from uuid import uuid4

import pytest
from fakes import FakePredictor, FakeWeather
from fastapi.testclient import TestClient
from pydantic import SecretStr

from heatwave_api.app import create_app
from heatwave_api.config import Settings
from heatwave_api.db import cli
from heatwave_api.db.connection import DatabaseError, connect, resolve_sqlite_path
from heatwave_api.db.migrate import (
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
    migration_status,
)
from heatwave_api.db.repository import Database, SqliteRepository

DEMO_PASSWORD = "demo-official-local"  # pragma: allowlist secret
MESSAGE = "Heatwave conditions expected. Stay indoors between noon and 4 PM."
TABLES = {
    "regions", "weather_snapshots", "model_metadata", "users", "user_regions", "predictions",
    "prediction_factors", "alert_sequences", "alerts", "alert_channel_deliveries",
    "schema_migrations",
}  # fmt: skip


def alert_body(**overrides):
    return {
        "client_request_id": str(uuid4()),
        "region_id": "mumbai",
        "severity": "HEATWAVE",
        "message": MESSAGE,
        "channels": ["public_mobile", "hospitals"],
        **overrides,
    }


def login(c, settings):
    r = c.post(
        "/api/v1/auth/login",
        json={
            "username": settings.demo_user_username,
            "password": settings.demo_user_password.get_secret_value(),
        },
    )
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture
def conn():
    c = connect("sqlite:///:memory:")
    apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def file_settings(tmp_path):
    return Settings(
        app_env="test", database_url=f"sqlite:///{tmp_path.as_posix()}/hw.db", _env_file=None
    )


def app_for(settings):
    return create_app(settings, predictor=FakePredictor(), weather=FakeWeather())


# -- connection and migrations --------------------------------------------------------


def test_url_resolution():
    assert resolve_sqlite_path("sqlite:///:memory:") == ":memory:"
    assert resolve_sqlite_path("sqlite:///data/local/x.db").is_absolute()
    with pytest.raises(DatabaseError, match="Only SQLite"):
        resolve_sqlite_path("postgresql+psycopg://u@h/db")


def test_foreign_keys_are_enforced(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO user_regions (user_id, region_id) VALUES ('nobody', 'nowhere')")


def test_first_migration_creates_every_table_and_is_applied_once(conn):
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= TABLES
    assert apply_migrations(conn) == []  # second run: nothing to do
    status = migration_status(conn)
    assert status.current == 1 and status.pending == []


def test_planned_indexes_exist(conn):
    indexes = {
        r[0]: r[1]
        for r in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
    }
    for name in (
        "ix_predictions_region_created",
        "ix_weather_snapshots_region_date",
        "ix_alerts_status",
        "ix_alerts_region",
    ):
        assert name in indexes
    plan = " ".join(
        r[3]
        for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM predictions WHERE region_id = ? AND lead_days = ? "
            "ORDER BY created_at DESC LIMIT 1",
            ("mumbai", 0),
        )
    )
    assert "ix_predictions_region_lead_created" in plan


def test_an_edited_applied_migration_is_refused(tmp_path):
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (x INTEGER);")
    c = connect("sqlite:///:memory:")
    assert apply_migrations(c, tmp_path) == [1]
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (x INTEGER, y TEXT);")
    with pytest.raises(MigrationError, match="edited after it was applied"):
        apply_migrations(c, tmp_path)


def test_a_failing_migration_changes_nothing(tmp_path):
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE a (x INTEGER);")
    (tmp_path / "0002_broken.sql").write_text("CREATE TABLE b (y INTEGER); NOT VALID SQL;")
    c = connect("sqlite:///:memory:")
    with pytest.raises(MigrationError, match="0002_broken.sql failed"):
        apply_migrations(c, tmp_path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables and "b" not in tables
    assert migration_status(c, tmp_path).current == 1


def test_numbering_gaps_and_a_newer_database_are_refused(tmp_path):
    (tmp_path / "0001_first.sql").write_text("SELECT 1;")
    (tmp_path / "0003_third.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="without gaps"):
        migration_status(connect("sqlite:///:memory:"), tmp_path)
    c = connect("sqlite:///:memory:")
    apply_migrations(c)  # the real 0001
    empty = tmp_path / "none"
    empty.mkdir()
    with pytest.raises(MigrationError, match="this code does not have"):
        migration_status(c, empty)


def test_migration_files_are_numbered_from_0001():
    assert sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))[0] == "0001_initial_schema.sql"


# -- constraints that protect the record ----------------------------------------------


def test_predictions_are_append_only_and_round_trip_exactly(client):
    sent = client.post("/api/v1/predict", json={"region_id": "mumbai", "lead_days": 1}).json()
    repo = client.app_ctx.repo
    stored = repo.get_prediction(sent["data"]["prediction_id"])
    assert stored.model_dump(mode="json") == sent["data"]  # nothing lost in storage

    conn = repo.db.conn
    factors = conn.execute(
        "SELECT rank, feature FROM prediction_factors WHERE prediction_id = ? ORDER BY rank",
        (stored.prediction_id,),
    ).fetchall()
    assert [tuple(f) for f in factors] == [(1, "temp_deviation_c"), (2, "tmax_c")]
    for sql in (
        "UPDATE predictions SET risk_class = 'NORMAL'",
        "DELETE FROM predictions",
        "DELETE FROM prediction_factors",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(sql)
    snapshot = conn.execute(
        "SELECT kind, tmax_c FROM weather_snapshots w JOIN predictions p "
        "ON p.weather_snapshot_id = w.snapshot_id"
    ).fetchone()
    assert tuple(snapshot) == ("FORECAST", 42.0)


def test_check_constraints_reject_out_of_vocabulary_values(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, display_name, role, "
            "created_at, updated_at) VALUES ('u', 'u', 'plaintext', 'U', 'official', 'x', 'x')"
        )


def test_an_issued_alert_is_frozen_in_the_database(client, auth):
    a = client.post("/api/v1/alerts", json=alert_body(status="ISSUED"), headers=auth).json()["data"]
    conn = client.app_ctx.repo.db.conn
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
        conn.execute(
            "UPDATE alerts SET message = 'rewritten history' WHERE alert_id = ?", (a["alert_id"],)
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute("DELETE FROM alerts WHERE alert_id = ?", (a["alert_id"],))
    deliveries = conn.execute(
        "SELECT channel, status FROM alert_channel_deliveries WHERE alert_id = ? ORDER BY position",
        (a["alert_id"],),
    ).fetchall()
    assert [tuple(d) for d in deliveries] == [
        ("public_mobile", "NOTIFIED"),
        ("hospitals", "NOTIFIED"),
    ]


def test_one_active_model_row(conn):
    repo = SqliteRepository(Database(conn))
    from heatwave_api.services import model_performance

    perf = model_performance(FakePredictor())
    repo.record_active_model(perf)
    repo.record_active_model(perf.model_copy(update={"model_version": "fake-model-v2"}))
    rows = conn.execute("SELECT model_version, is_active FROM model_metadata ORDER BY 1").fetchall()
    assert [tuple(r) for r in rows] == [("fake-model-v1", 0), ("fake-model-v2", 1)]
    assert repo.active_model().model_version == "fake-model-v2"


# -- persistence across restarts and startup policy -----------------------------------


def test_everything_survives_a_restart(file_settings):
    with TestClient(app_for(file_settings)) as c:
        pred = c.post("/api/v1/predict", json={"region_id": "kurla"}).json()["data"]
        auth = login(c, file_settings)
        body = alert_body(region_id="kurla", prediction_id=pred["prediction_id"])
        first = c.post("/api/v1/alerts", json=body, headers=auth).json()["data"]

    with TestClient(app_for(file_settings)) as c:  # a new process on the same file
        assert c.get(f"/api/v1/predictions/{pred['prediction_id']}").json()["data"] == pred
        auth = login(c, file_settings)
        replay = c.post("/api/v1/alerts", json=body, headers=auth).json()["data"]
        assert replay["alert_id"] == first["alert_id"] and replay["idempotent_replay"]
        second = c.post("/api/v1/alerts", json=alert_body(), headers=auth).json()["data"]
        year = first["alert_id"].split("-")[1]
        assert second["alert_id"] == f"HW-{year}-0002"  # the sequence did not restart
        assert c.get("/api/v1/health/ready").json()["data"]["ready"] in (True, False)


def test_staging_refuses_to_start_with_pending_migrations(tmp_path):
    settings = Settings(
        app_env="staging",
        auth_secret_key=SecretStr("x" * 40),
        database_url=f"sqlite:///{tmp_path.as_posix()}/staging.db",
        _env_file=None,
    )
    with pytest.raises(RuntimeError, match="pending migrations"), TestClient(app_for(settings)):
        pass


def test_a_local_database_promoted_to_staging_loses_the_demo_login(file_settings):
    with TestClient(app_for(file_settings)):
        pass  # local/test: migrated, demo user seeded
    staging = file_settings.model_copy(
        update={"app_env": "staging", "auth_secret_key": SecretStr("x" * 40)}
    )
    with TestClient(app_for(staging)) as c:
        r = c.post(
            "/api/v1/auth/login",
            json={"username": "official", "password": DEMO_PASSWORD},
        )
        assert r.status_code == 401


# -- CLI ------------------------------------------------------------------------------


def test_cli_migrate_status_seed_import_and_backup(file_settings, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: file_settings)
    assert cli.main(["migrate"]) == 0
    assert cli.main(["seed"]) == 0
    csv_path = tmp_path / "hist.csv"
    csv_path.write_text(
        "region_id,date,lead_days,issued_at,tmax_c,normal_tmax_c,rh_pct,wind_ms,solar_mj_m2,precip_mm\n"
        "mumbai,2026-05-01,0,,38.5,34.0,60,3.2,24.1,0\n"
        "colaba,2026-05-01,0,,37.0,33.5,65,4.0,23.0,\n"
    )
    assert cli.main(["import-weather", str(csv_path), "--source", "imd"]) == 0
    assert cli.main(["import-weather", str(csv_path), "--source", "imd"]) == 0  # idempotent
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "regions upserted: 5" in out
    assert "inserted: 2, already present: 0" in out and "inserted: 0, already present: 2" in out
    assert "version:  1" in out

    backups = tmp_path / "backups"
    for _ in range(3):
        cli.backup(file_settings, keep=2, dest_dir=backups)
    kept = list(backups.glob("hw-*.db"))
    assert 1 <= len(kept) <= 2  # same-second names collapse; never more than --keep
    copy = sqlite3.connect(kept[0])
    assert copy.execute("SELECT count(*) FROM weather_snapshots").fetchone()[0] == 2
    copy.close()
