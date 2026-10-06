"""All SQL the service runs, behind one class. Routes and services never write SQL.

Keeping data access in one place is what lets the endpoints be tested against a
throwaway database, and what a later PostgreSQL migration would have to touch.
Rows come back as plain dicts.
"""

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from heatwave_api.db import utcnow

FEATURE_FIELDS = (
    "tmax_c",
    "normal_tmax_c",
    "temp_deviation_c",
    "rh_pct",
    "wind_ms",
    "solar_mj_m2",
    "precip_mm",
)
SNAPSHOT_FIELDS = (
    "region_id",
    "date",
    "kind",
    "lead_days",
    "issued_at",
    "source",
    *FEATURE_FIELDS,
    "fetched_at",
)
PREDICTION_FIELDS = (
    "run_id",
    "region_id",
    "weather_snapshot_id",
    "target_date",
    "lead_days",
    "created_at",
    *FEATURE_FIELDS,
    "risk_class",
    "confidence",
    "p_normal",
    "p_heatwave",
    "p_severe_heatwave",
    "target_class",
    "quantity",
    "explained",
    "baseline",
    "output",
    "summary",
    "model_version",
    "explainer_id",
)
FACTOR_FIELDS = (
    "prediction_id",
    "rank",
    "feature",
    "label",
    "unit",
    "value",
    "display_value",
    "imputed",
    "contribution",
    "share_pct",
    "direction",
)
RUN_FIELDS = (
    "id",
    "region_id",
    "created_at",
    "window_start",
    "window_end",
    "source",
    "issued_at",
    "fetched_at",
    "peak_date",
    "risk_class",
    "confidence",
    "model_version",
    "explainer_id",
)


def _insert(conn: sqlite3.Connection, table: str, fields: tuple[str, ...], row: dict) -> int:
    placeholders = ", ".join("?" for _ in fields)
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})",
        [row.get(f) for f in fields],
    )
    return cursor.lastrowid


def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE takes the write lock up front, so read-then-write sequences
        (the next alert number, the idempotency check) cannot interleave."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return _dicts(self.conn.execute(sql, tuple(params)))

    # -- regions ------------------------------------------------------------------------

    def sync_regions(self, regions: list[dict]) -> None:
        """Make the table match config/regions.yaml: upsert those, deactivate the rest
        (never delete: predictions and alerts reference them)."""
        with self.transaction():
            self.conn.execute("UPDATE regions SET active = 0")
            for r in regions:
                self.conn.execute(
                    "INSERT INTO regions (id, name, district, state, zone, lat, lon, active) "
                    "VALUES (:id, :name, :district, :state, :zone, :lat, :lon, 1) "
                    "ON CONFLICT (id) DO UPDATE SET name = excluded.name, "
                    "district = excluded.district, state = excluded.state, "
                    "zone = excluded.zone, lat = excluded.lat, lon = excluded.lon, active = 1",
                    r,
                )

    def all_regions(self) -> list[dict]:
        return self._all(
            "SELECT id, name, district, state, zone, lat, lon FROM regions ORDER BY id"
        )

    # -- weather snapshots --------------------------------------------------------------

    def insert_snapshots(self, rows: list[dict]) -> list[int]:
        with self.transaction():
            return [_insert(self.conn, "weather_snapshots", SNAPSHOT_FIELDS, r) for r in rows]

    def latest_forecast(self, region_id: str, issued_on: str, fetched_since: str) -> list[dict]:
        """The newest stored forecast for ``region_id`` issued on ``issued_on`` (local
        date) and fetched at or after ``fetched_since``: every lead day of that fetch."""
        newest = self._one(
            "SELECT fetched_at FROM weather_snapshots WHERE region_id = ? AND kind = 'FORECAST' "
            "AND substr(issued_at, 1, 10) = ? AND fetched_at >= ? "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (region_id, issued_on, fetched_since),
        )
        if newest is None:
            return []
        return self._all(
            "SELECT * FROM weather_snapshots WHERE region_id = ? AND kind = 'FORECAST' "
            "AND fetched_at = ? ORDER BY lead_days",
            (region_id, newest["fetched_at"]),
        )

    def best_snapshot(self, region_id: str, day: str) -> dict | None:
        """The best reading for one region-day: an observation over a forecast, then
        the most recently fetched."""
        return self._one(
            "SELECT * FROM weather_snapshots WHERE region_id = ? AND date = ? "
            "ORDER BY (kind = 'ACTUAL') DESC, fetched_at DESC, id DESC LIMIT 1",
            (region_id, day),
        )

    def snapshots_between(self, start: str, end: str, region_id: str | None) -> list[dict]:
        sql = "SELECT * FROM weather_snapshots WHERE date BETWEEN ? AND ?"
        params: list[Any] = [start, end]
        if region_id:
            sql += " AND region_id = ?"
            params.append(region_id)
        return self._all(sql + " ORDER BY date, region_id", params)

    # -- predictions --------------------------------------------------------------------

    def insert_prediction_run(self, run: dict, days: list[dict]) -> None:
        """A run, its days and every day's factors: all or nothing."""
        with self.transaction():
            _insert(self.conn, "prediction_runs", RUN_FIELDS, run)
            for day in days:
                prediction_id = _insert(self.conn, "predictions", PREDICTION_FIELDS, day)
                for factor in day["factors"]:
                    _insert(
                        self.conn,
                        "prediction_factors",
                        FACTOR_FIELDS,
                        factor | {"prediction_id": prediction_id},
                    )

    def run(self, run_id: str) -> dict | None:
        """A stored run with its days (in date order) and each day's factors (by rank)."""
        run = self._one("SELECT * FROM prediction_runs WHERE id = ?", (run_id,))
        if run is None:
            return None
        days = self._all(
            "SELECT * FROM predictions WHERE run_id = ? ORDER BY target_date", (run_id,)
        )
        factors = self._all(
            "SELECT f.* FROM prediction_factors f JOIN predictions p ON p.id = f.prediction_id "
            "WHERE p.run_id = ? ORDER BY f.prediction_id, f.rank",
            (run_id,),
        )
        by_day: dict[int, list[dict]] = {}
        for f in factors:
            by_day.setdefault(f["prediction_id"], []).append(f)
        for day in days:
            day["factors"] = by_day.get(day["id"], [])
        return run | {"days": days}

    def latest_run_ids(self, region_ids: list[str] | None = None) -> dict[str, str]:
        """region_id -> id of its most recent run ("latest prediction per region")."""
        sql = (
            "SELECT r.region_id, r.id FROM prediction_runs r JOIN ("
            " SELECT MAX(seq) AS seq FROM prediction_runs GROUP BY region_id) last"
            " ON last.seq = r.seq"
        )
        latest = {row["region_id"]: row["id"] for row in self._all(sql)}
        if region_ids is not None:
            latest = {k: v for k, v in latest.items() if k in region_ids}
        return latest

    def run_summaries(self, run_ids: list[str]) -> dict[str, dict]:
        if not run_ids:
            return {}
        marks = ", ".join("?" for _ in run_ids)
        rows = self._all(f"SELECT * FROM prediction_runs WHERE id IN ({marks})", run_ids)
        return {r["id"]: r for r in rows}

    def daily_classes(self, start: str, end: str, region_id: str | None) -> list[dict]:
        """One row per region-day in [start, end]: the class of the most recent
        prediction made for that day (Part 14's counting unit)."""
        sql = (
            "SELECT p.region_id, p.target_date, p.risk_class FROM predictions p JOIN ("
            " SELECT MAX(id) AS id FROM predictions WHERE target_date BETWEEN ? AND ?"
        )
        params: list[Any] = [start, end]
        if region_id:
            sql += " AND region_id = ?"
            params.append(region_id)
        sql += " GROUP BY region_id, target_date) last ON last.id = p.id ORDER BY p.target_date"
        return self._all(sql, params)

    # -- users and tokens ---------------------------------------------------------------

    def create_user(self, username: str, password_hash: str, display_name: str) -> int:
        with self.transaction():
            return _insert(
                self.conn,
                "users",
                ("username", "password_hash", "display_name", "created_at"),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "display_name": display_name,
                    "created_at": utcnow(),
                },
            )

    def set_password(self, username: str, password_hash: str) -> bool:
        with self.transaction():
            cursor = self.conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username)
            )
        return cursor.rowcount == 1

    def user_by_username(self, username: str) -> dict | None:
        return self._one("SELECT * FROM users WHERE username = ?", (username,))

    def user_by_id(self, user_id: int) -> dict | None:
        return self._one("SELECT * FROM users WHERE id = ?", (user_id,))

    def revoke_token(self, jti: str, expires_at: str) -> None:
        with self.transaction():
            self.conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (utcnow(),))
            self.conn.execute(
                "INSERT OR IGNORE INTO revoked_tokens (jti, expires_at) VALUES (?, ?)",
                (jti, expires_at),
            )

    def is_revoked(self, jti: str) -> bool:
        return self._one("SELECT 1 AS x FROM revoked_tokens WHERE jti = ?", (jti,)) is not None

    # -- alerts -------------------------------------------------------------------------

    def next_alert_seq(self, year: int) -> int:
        """Call inside a transaction (BEGIN IMMEDIATE serialises writers)."""
        row = self._one("SELECT COALESCE(MAX(seq), 0) AS seq FROM alerts WHERE year = ?", (year,))
        return row["seq"] + 1

    def insert_alert(self, alert: dict) -> int:
        fields = (
            "code",
            "year",
            "seq",
            "region_id",
            "severity",
            "status",
            "message",
            "prediction_id",
            "client_request_id",
            "request_fingerprint",
            "created_by",
            "created_at",
            "updated_at",
            "issued_at",
            "issued_by",
        )
        return _insert(self.conn, "alerts", fields, alert)

    def update_alert(self, alert_id: int, changes: dict) -> None:
        if not changes:
            return
        assignments = ", ".join(f"{k} = ?" for k in changes)
        self.conn.execute(
            f"UPDATE alerts SET {assignments} WHERE id = ?", [*changes.values(), alert_id]
        )

    def replace_channels(self, alert_id: int, channels: list[str], status: str, at: str) -> None:
        self.conn.execute("DELETE FROM alert_channel_deliveries WHERE alert_id = ?", (alert_id,))
        for channel in channels:
            self.conn.execute(
                "INSERT INTO alert_channel_deliveries (alert_id, channel, status, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (alert_id, channel, status, at),
            )

    def set_channels_status(self, alert_id: int, status: str, at: str) -> None:
        self.conn.execute(
            "UPDATE alert_channel_deliveries SET status = ?, updated_at = ? WHERE alert_id = ?",
            (status, at, alert_id),
        )

    def record_delivery(self, alert_id: int, channel: str, status: str, error: str | None) -> None:
        """One delivery attempt's outcome, committed on its own so it is never lost."""
        with self.transaction():
            self.conn.execute(
                "UPDATE alert_channel_deliveries SET status = ?, last_error = ?, "
                "attempts = attempts + 1, updated_at = ? WHERE alert_id = ? AND channel = ?",
                (status, error, utcnow(), alert_id, channel),
            )

    def alert(self, *, code: str | None = None, client_request_id: str | None = None):
        if code is not None:
            row = self._one("SELECT * FROM alerts WHERE code = ?", (code,))
        else:
            row = self._one(
                "SELECT * FROM alerts WHERE client_request_id = ?", (client_request_id,)
            )
        return self._with_details([row])[0] if row else None

    def list_alerts(
        self, *, status: str | None, region_id: str | None, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if region_id:
            where.append("region_id = ?")
            params.append(region_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = self._one(f"SELECT COUNT(*) AS n FROM alerts{clause}", params)["n"]
        rows = self._all(
            f"SELECT * FROM alerts{clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return self._with_details(rows), total

    def _with_details(self, alerts: list[dict]) -> list[dict]:
        """Attach channels and the creator/issuer to each alert, in two queries."""
        if not alerts:
            return alerts
        ids = [a["id"] for a in alerts]
        marks = ", ".join("?" for _ in ids)
        channels = self._all(
            f"SELECT * FROM alert_channel_deliveries WHERE alert_id IN ({marks}) ORDER BY id",
            ids,
        )
        user_ids = {a["created_by"] for a in alerts} | {
            a["issued_by"] for a in alerts if a["issued_by"]
        }
        user_marks = ", ".join("?" for _ in user_ids)
        users = {
            u["id"]: u
            for u in self._all(
                f"SELECT id, username, display_name FROM users WHERE id IN ({user_marks})",
                list(user_ids),
            )
        }
        for a in alerts:
            a["channels"] = [c for c in channels if c["alert_id"] == a["id"]]
            a["creator"] = users.get(a["created_by"])
            a["issuer"] = users.get(a["issued_by"]) if a["issued_by"] else None
        return alerts

    # -- model metadata -----------------------------------------------------------------

    def activate_model(self, meta: dict) -> None:
        """Record the model this process serves as the active one (Part 08 §2.7)."""
        fields = (
            "model_version",
            "model_family",
            "model_sha256",
            "explainer_id",
            "evaluation_id",
            "policy_version",
            "report",
            "test_rows",
            "accuracy",
            "precision_macro",
            "recall_macro",
            "f1_macro",
            "mean_confidence",
            "top_label_ece",
            "per_class_json",
            "is_active",
            "deployed_at",
        )
        row = meta | {"is_active": 1, "per_class_json": json.dumps(meta["per_class"])}
        with self.transaction():
            current = self._one(
                "SELECT model_version, model_sha256, explainer_id, deployed_at "
                "FROM model_metadata WHERE is_active = 1"
            )
            unchanged = current is not None and all(
                current[k] == row[k] for k in ("model_version", "model_sha256", "explainer_id")
            )
            if unchanged:
                row["deployed_at"] = current["deployed_at"]  # a restart is not a deployment
            self.conn.execute("UPDATE model_metadata SET is_active = 0")
            self.conn.execute(
                "DELETE FROM model_metadata WHERE model_version = ?", (row["model_version"],)
            )
            _insert(self.conn, "model_metadata", fields, row)

    def active_model(self) -> dict | None:
        row = self._one("SELECT * FROM model_metadata WHERE is_active = 1")
        if row:
            row["per_class"] = json.loads(row.pop("per_class_json"))
        return row
