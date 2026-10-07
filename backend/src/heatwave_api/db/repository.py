"""`SqliteRepository`: the `Repository` (repositories.py) and `UserStore` (auth.py) on SQLite.

Concurrency (Part 08 §7, a conscious decision): SQLite allows one writer at a time. The
service holds one connection behind a lock, so its own writes are serialized in-process,
and WAL mode lets outside readers (backups, `heatwave-db status`) run alongside. For a
handful of officials this is nowhere near a bottleneck. Many concurrent writers, or more
than one API process writing, is the point to move to PostgreSQL (docs/database §8).
"""

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime

from heatwave_api.alerts import summarize
from heatwave_api.auth import User
from heatwave_api.db.connection import connect, ds, now_ts, ts
from heatwave_api.db.migrate import apply_migrations, migration_status
from heatwave_api.schemas import (
    AlertOut,
    ChannelDelivery,
    FactorOut,
    ModelPerformance,
    PredictionOut,
    RegionOut,
)

# Snapshot columns, filled from a prediction's inputs (same names as the feature table).
WEATHER_FIELDS = ("tmax_c", "normal_tmax_c", "rh_pct", "wind_ms", "solar_mj_m2", "precip_mm")
_PROB_COLUMNS = {
    "NORMAL": "prob_normal",
    "HEATWAVE": "prob_heatwave",
    "SEVERE_HEATWAVE": "prob_severe_heatwave",
}


@dataclass
class Database:
    conn: sqlite3.Connection
    lock: threading.RLock = field(default_factory=threading.RLock)

    @classmethod
    def open(cls, database_url: str) -> "Database":
        return cls(connect(database_url))

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One transaction: committed on success, rolled back on any error."""
        with self.lock, self.conn:
            yield self.conn

    def read(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def migrate(self) -> list[int]:
        with self.lock:
            return apply_migrations(self.conn)

    def pending_migrations(self) -> list[str]:
        with self.lock:
            return [m.path.name for m in migration_status(self.conn).pending]

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def _region(row: sqlite3.Row) -> RegionOut:
    return RegionOut(
        id=row["region_id"],
        name=row["region_name"],
        district=row["district"],
        state=row["state"],
        zone=row["zone"],
        lat=row["lat"],
        lon=row["lon"],
    )


_REGION_COLS = "r.region_id, r.name AS region_name, r.district, r.state, r.zone, r.lat, r.lon"


class SqliteRepository:
    def __init__(self, db: Database):
        self.db = db

    # -- reference data ---------------------------------------------------------------

    def upsert_regions(self, regions: Iterable[RegionOut]) -> None:
        now = now_ts()
        with self.db.tx() as c:
            c.executemany(
                """INSERT INTO regions (region_id, name, district, state, zone, lat, lon,
                                        created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (region_id) DO UPDATE SET
                     name = excluded.name, district = excluded.district,
                     state = excluded.state, zone = excluded.zone, lat = excluded.lat,
                     lon = excluded.lon, is_active = 1, updated_at = excluded.updated_at""",
                [
                    (r.id, r.name, r.district, r.state, r.zone, r.lat, r.lon, now, now)
                    for r in regions
                ],
            )

    def record_active_model(self, perf: ModelPerformance) -> None:
        """Called at startup with the model the service loaded: it becomes the active row."""
        now = now_ts()
        with self.db.tx() as c:
            c.execute("UPDATE model_metadata SET is_active = 0 WHERE is_active = 1")
            c.execute(
                """INSERT INTO model_metadata (model_version, model_family, explainer_id,
                       labeling_rule_version, test_rows, accuracy, precision_macro,
                       recall_macro, f1_macro, performance_json, is_active, first_seen_at,
                       activated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT (model_version) DO UPDATE SET
                     model_family = excluded.model_family, explainer_id = excluded.explainer_id,
                     labeling_rule_version = excluded.labeling_rule_version,
                     test_rows = excluded.test_rows, accuracy = excluded.accuracy,
                     precision_macro = excluded.precision_macro,
                     recall_macro = excluded.recall_macro, f1_macro = excluded.f1_macro,
                     performance_json = excluded.performance_json, is_active = 1,
                     activated_at = excluded.activated_at""",
                (
                    perf.model_version,
                    perf.model_family,
                    perf.explainer_id,
                    perf.labeling_rule_version,
                    perf.test_rows,
                    perf.accuracy,
                    perf.precision_macro,
                    perf.recall_macro,
                    perf.f1_macro,
                    perf.model_dump_json(),
                    now,
                    now,
                ),
            )

    def active_model(self) -> ModelPerformance | None:
        rows = self.db.read("SELECT performance_json FROM model_metadata WHERE is_active = 1")
        return ModelPerformance.model_validate_json(rows[0][0]) if rows else None

    # -- predictions (append-only) ----------------------------------------------------

    def add_prediction(self, prediction: PredictionOut) -> None:
        p, w = prediction, prediction.weather
        explanation = p.explanation.model_dump(mode="json", exclude={"factors"})
        with self.db.tx() as c:
            snapshot_id = self._snapshot(c, p)
            c.execute(
                """INSERT INTO predictions (prediction_id, created_at, region_id,
                       weather_snapshot_id, model_version, explainer_id, valid_date, lead_days,
                       horizon_days, forecast_issued_at, risk_class, confidence, prob_normal,
                       prob_heatwave, prob_severe_heatwave, inputs_json, explanation_json,
                       recommended_actions_json, actions_version, weather_source,
                       weather_issued_at, weather_age_hours, weather_stale)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.prediction_id,
                    ts(p.created_at),
                    p.region.id,
                    snapshot_id,
                    p.explanation.model_version,
                    p.explanation.explainer_id,
                    ds(p.forecast_window.valid_date),
                    p.forecast_window.lead_days,
                    p.forecast_window.horizon_days,
                    ts(p.forecast_window.issued_at),
                    p.risk_class,
                    p.confidence,
                    *(p.probabilities.get(k, 0.0) for k in _PROB_COLUMNS),
                    json.dumps(p.inputs),
                    json.dumps(explanation),
                    json.dumps(p.recommended_actions),
                    p.actions_version,
                    w.source,
                    ts(w.issued_at),
                    w.age_hours,
                    int(w.stale),
                ),
            )
            c.executemany(
                """INSERT INTO prediction_factors (prediction_id, rank, feature, label, unit,
                       value, display_value, imputed, contribution, share_pct, direction)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        p.prediction_id,
                        f.rank,
                        f.feature,
                        f.label,
                        f.unit,
                        f.value,
                        f.display_value,
                        int(f.imputed),
                        f.contribution,
                        f.share_pct,
                        f.direction,
                    )
                    for f in p.explanation.factors
                ],
            )

    @staticmethod
    def _snapshot(c: sqlite3.Connection, p: PredictionOut) -> int:
        """The conditions the prediction used, as a FORECAST snapshot (shared if identical)."""
        key = (
            p.region.id,
            ds(p.forecast_window.valid_date),
            p.forecast_window.lead_days,
            p.weather.source,
            ts(p.weather.issued_at),
        )
        c.execute(
            f"""INSERT INTO weather_snapshots (region_id, valid_date, lead_days, source,
                    issued_at, kind, {", ".join(WEATHER_FIELDS)}, recorded_at)
                VALUES (?, ?, ?, ?, ?, 'FORECAST', {", ".join("?" * len(WEATHER_FIELDS))}, ?)
                ON CONFLICT DO NOTHING""",
            (*key, *(p.inputs.get(f) for f in WEATHER_FIELDS), now_ts()),
        )
        return c.execute(
            """SELECT snapshot_id FROM weather_snapshots WHERE region_id = ? AND valid_date = ?
                 AND lead_days = ? AND source = ? AND issued_at = ?""",
            key,
        ).fetchone()[0]

    def _predictions(self, where: str, params: tuple, tail: str = "") -> list[PredictionOut]:
        rows = self.db.read(
            f"""SELECT p.*, {_REGION_COLS} FROM predictions p
                JOIN regions r ON r.region_id = p.region_id WHERE {where} {tail}""",
            params,
        )
        if not rows:
            return []
        ids = [row["prediction_id"] for row in rows]
        factors: dict[str, list[FactorOut]] = {i: [] for i in ids}
        for chunk in (ids[i : i + 500] for i in range(0, len(ids), 500)):
            for f in self.db.read(
                f"""SELECT * FROM prediction_factors WHERE prediction_id IN
                    ({",".join("?" * len(chunk))}) ORDER BY prediction_id, rank""",
                chunk,
            ):
                factors[f["prediction_id"]].append(
                    FactorOut(**{k: v for k, v in dict(f).items() if k != "prediction_id"})
                )
        return [self._prediction(row, factors[row["prediction_id"]]) for row in rows]

    @staticmethod
    def _prediction(row: sqlite3.Row, factors: list[FactorOut]) -> PredictionOut:
        return PredictionOut(
            prediction_id=row["prediction_id"],
            created_at=row["created_at"],
            region=_region(row),
            forecast_window={
                "valid_date": row["valid_date"],
                "lead_days": row["lead_days"],
                "issued_at": row["forecast_issued_at"],
                "horizon_days": row["horizon_days"],
            },
            risk_class=row["risk_class"],
            confidence=row["confidence"],
            probabilities={k: row[col] for k, col in _PROB_COLUMNS.items()},
            inputs=json.loads(row["inputs_json"]),
            explanation={**json.loads(row["explanation_json"]), "factors": factors},
            recommended_actions=json.loads(row["recommended_actions_json"]),
            actions_version=row["actions_version"],
            weather={
                "source": row["weather_source"],
                "issued_at": row["weather_issued_at"],
                "age_hours": row["weather_age_hours"],
                "stale": bool(row["weather_stale"]),
            },
        )

    def get_prediction(self, prediction_id: str) -> PredictionOut | None:
        found = self._predictions("p.prediction_id = ?", (prediction_id,))
        return found[0] if found else None

    def latest_prediction(self, region_id: str, lead_days: int) -> PredictionOut | None:
        found = self._predictions(
            "p.region_id = ? AND p.lead_days = ?",
            (region_id, lead_days),
            "ORDER BY p.created_at DESC, p.rowid DESC LIMIT 1",
        )
        return found[0] if found else None

    def predictions_since(
        self, since: datetime, region_id: str | None = None
    ) -> list[PredictionOut]:
        where, params = "p.created_at >= ?", [ts(since)]
        if region_id is not None:
            where += " AND p.region_id = ?"
            params.append(region_id)
        return self._predictions(where, tuple(params), "ORDER BY p.created_at, p.rowid")

    # -- alerts -----------------------------------------------------------------------

    def next_alert_sequence(self, year: int) -> int:
        with self.db.tx() as c:
            return c.execute(
                """INSERT INTO alert_sequences (year, last_seq) VALUES (?, 1)
                   ON CONFLICT (year) DO UPDATE SET last_seq = last_seq + 1
                   RETURNING last_seq""",
                (year,),
            ).fetchone()[0]

    def save_alert(self, alert: AlertOut, request_key: tuple[str, str] | None = None) -> None:
        a = alert
        with self.db.tx() as c:
            c.execute(
                """INSERT INTO alerts (alert_id, region_id, prediction_id, severity, status,
                       message, created_by, client_request_id, created_at, updated_at, issued_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (alert_id) DO UPDATE SET
                     severity = excluded.severity, status = excluded.status,
                     message = excluded.message, updated_at = excluded.updated_at,
                     issued_at = excluded.issued_at""",
                (
                    a.alert_id,
                    a.region.id,
                    a.prediction_id,
                    a.severity,
                    a.status,
                    a.message,
                    a.created_by,
                    request_key[1] if request_key else None,
                    ts(a.created_at),
                    ts(a.updated_at),
                    ts(a.issued_at) if a.issued_at else None,
                ),
            )
            channels = [d.channel for d in a.channels]
            c.execute(
                f"""DELETE FROM alert_channel_deliveries WHERE alert_id = ?
                    AND channel NOT IN ({",".join("?" * len(channels))})""",
                (a.alert_id, *channels),
            )
            c.executemany(
                """INSERT INTO alert_channel_deliveries (alert_id, channel, label, position,
                       status, detail, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (alert_id, channel) DO UPDATE SET
                     label = excluded.label, position = excluded.position,
                     status = excluded.status, detail = excluded.detail,
                     updated_at = excluded.updated_at""",
                [
                    (a.alert_id, d.channel, d.label, i, d.status, d.detail, ts(d.updated_at))
                    for i, d in enumerate(a.channels)
                ],
            )

    def _alerts(self, where: str, params: tuple, tail: str = "") -> list[AlertOut]:
        rows = self.db.read(
            f"""SELECT a.*, {_REGION_COLS} FROM alerts a
                JOIN regions r ON r.region_id = a.region_id WHERE {where} {tail}""",
            params,
        )
        if not rows:
            return []
        ids = [row["alert_id"] for row in rows]
        deliveries: dict[str, list[ChannelDelivery]] = {i: [] for i in ids}
        for d in self.db.read(
            f"""SELECT * FROM alert_channel_deliveries WHERE alert_id IN
                ({",".join("?" * len(ids))}) ORDER BY alert_id, position""",
            ids,
        ):
            deliveries[d["alert_id"]].append(
                ChannelDelivery(
                    channel=d["channel"],
                    label=d["label"],
                    status=d["status"],
                    detail=d["detail"],
                    updated_at=d["updated_at"],
                )
            )
        return [
            AlertOut(
                alert_id=row["alert_id"],
                status=row["status"],
                severity=row["severity"],
                region=_region(row),
                message=row["message"],
                prediction_id=row["prediction_id"],
                channels=deliveries[row["alert_id"]],
                delivery_summary=summarize(deliveries[row["alert_id"]]),
                created_at=row["created_at"],
                created_by=row["created_by"],
                issued_at=row["issued_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_alert(self, alert_id: str) -> AlertOut | None:
        found = self._alerts("a.alert_id = ?", (alert_id,))
        return found[0] if found else None

    def find_alert_by_request(self, user_id: str, client_request_id: str) -> AlertOut | None:
        found = self._alerts(
            "a.created_by = ? AND a.client_request_id = ?", (user_id, client_request_id)
        )
        return found[0] if found else None

    def list_alerts(
        self, *, status: str | None, region_id: str | None, limit: int, offset: int
    ) -> tuple[list[AlertOut], int]:
        clauses, params = ["1 = 1"], []
        if status is not None:
            clauses.append("a.status = ?")
            params.append(status)
        if region_id is not None:
            clauses.append("a.region_id = ?")
            params.append(region_id)
        where = " AND ".join(clauses)
        total = self.db.read(f"SELECT count(*) FROM alerts a WHERE {where}", params)[0][0]
        page = self._alerts(
            where,
            (*params, limit, offset),
            "ORDER BY a.created_at DESC, a.alert_id DESC LIMIT ? OFFSET ?",
        )
        return page, total

    def ping(self) -> bool:
        try:
            return self.db.read("SELECT 1")[0][0] == 1
        except sqlite3.Error:
            return False


class SqliteUserStore:
    """`UserStore` over the `users` table. Part 15 adds management on top of this."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _user(rows: list[sqlite3.Row]) -> User | None:
        if not rows:
            return None
        r = rows[0]
        return User(
            id=r["user_id"],
            username=r["username"],
            display_name=r["display_name"],
            role=r["role"],
            password_hash=r["password_hash"],
        )

    def get_by_username(self, username: str) -> User | None:
        return self._user(
            self.db.read("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
        )

    def get_by_id(self, user_id: str) -> User | None:
        return self._user(
            self.db.read("SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,))
        )

    def upsert(self, user: User, region_ids: Iterable[str] = ()) -> None:
        now = now_ts()
        with self.db.tx() as c:
            c.execute(
                """INSERT INTO users (user_id, username, password_hash, display_name, role,
                                      created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (user_id) DO UPDATE SET
                     username = excluded.username, password_hash = excluded.password_hash,
                     display_name = excluded.display_name, role = excluded.role,
                     is_active = 1, updated_at = excluded.updated_at""",
                (
                    user.id,
                    user.username,
                    user.password_hash,
                    user.display_name,
                    user.role,
                    now,
                    now,
                ),
            )
            c.executemany(
                "INSERT OR IGNORE INTO user_regions (user_id, region_id) VALUES (?, ?)",
                [(user.id, r) for r in region_ids],
            )

    def deactivate(self, user_id: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET is_active = 0, updated_at = ? WHERE user_id = ?",
                (now_ts(), user_id),
            )
