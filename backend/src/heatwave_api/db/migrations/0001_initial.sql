-- 0001: the initial schema (Part 07 data access, Part 08 entities §2-4).
--
-- Portable on purpose (CLAUDE.md: SQLite now, PostgreSQL later without a redesign):
--   * timestamps are ISO-8601 UTC text ("2026-10-06T09:30:00+00:00"), dates "YYYY-MM-DD";
--   * enums are CHECK constraints over the shared vocabulary;
--   * the only SQLite-specific spelling is INTEGER PRIMARY KEY AUTOINCREMENT
--     (GENERATED ALWAYS AS IDENTITY in PostgreSQL).
-- Foreign keys are only enforced with PRAGMA foreign_keys = ON, which db.connect sets.

CREATE TABLE regions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    district    TEXT NOT NULL,
    state       TEXT NOT NULL,
    zone        TEXT NOT NULL,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- Readings in model-feature units: wind at 2 m, normal from config/seasonal_normals.csv.
CREATE TABLE weather_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id         TEXT NOT NULL REFERENCES regions (id),
    date              TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('ACTUAL', 'FORECAST')),
    lead_days         INTEGER,
    issued_at         TEXT,
    source            TEXT NOT NULL,
    tmax_c            REAL,
    normal_tmax_c     REAL,
    temp_deviation_c  REAL,
    rh_pct            REAL,
    wind_ms           REAL,
    solar_mj_m2       REAL,
    precip_mm         REAL,
    fetched_at        TEXT NOT NULL
);
CREATE INDEX ix_weather_snapshots_region_date ON weather_snapshots (region_id, date);
CREATE INDEX ix_weather_snapshots_region_fetched ON weather_snapshots (region_id, fetched_at);

-- One POST /predict call: the 1-3 day window for one region. ``id`` is the public,
-- unguessable prediction id; ``seq`` orders runs by insertion ("latest per region"
-- must not depend on two runs landing in different clock seconds).
CREATE TABLE prediction_runs (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    id              TEXT NOT NULL UNIQUE,
    region_id       TEXT NOT NULL REFERENCES regions (id),
    created_at      TEXT NOT NULL,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('open_meteo_forecast', 'client')),
    issued_at       TEXT,
    fetched_at      TEXT,
    peak_date       TEXT NOT NULL,
    risk_class      TEXT NOT NULL CHECK (risk_class IN ('NORMAL', 'HEATWAVE', 'SEVERE_HEATWAVE')),
    confidence      REAL NOT NULL,
    model_version   TEXT NOT NULL,
    explainer_id    TEXT NOT NULL
);
CREATE INDEX ix_prediction_runs_region_seq ON prediction_runs (region_id, seq);

-- One row per predicted day. Inputs are copied in, so the record stays stable even if
-- weather_snapshots is later corrected. Append-only: predictions are never deleted.
CREATE TABLE predictions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               TEXT NOT NULL REFERENCES prediction_runs (id),
    region_id            TEXT NOT NULL REFERENCES regions (id),
    weather_snapshot_id  INTEGER REFERENCES weather_snapshots (id),
    target_date          TEXT NOT NULL,
    lead_days            INTEGER NOT NULL,
    created_at           TEXT NOT NULL,
    tmax_c               REAL NOT NULL,
    normal_tmax_c        REAL NOT NULL,
    temp_deviation_c     REAL NOT NULL,
    rh_pct               REAL NOT NULL,
    wind_ms              REAL NOT NULL,
    solar_mj_m2          REAL NOT NULL,
    precip_mm            REAL NOT NULL,
    risk_class           TEXT NOT NULL CHECK (risk_class IN ('NORMAL', 'HEATWAVE', 'SEVERE_HEATWAVE')),
    confidence           REAL NOT NULL,
    p_normal             REAL NOT NULL,
    p_heatwave           REAL NOT NULL,
    p_severe_heatwave    REAL NOT NULL,
    target_class         TEXT NOT NULL,
    quantity             TEXT NOT NULL,
    explained            TEXT NOT NULL,
    baseline             REAL NOT NULL,
    output               REAL NOT NULL,
    summary              TEXT NOT NULL,
    model_version        TEXT NOT NULL,
    explainer_id         TEXT NOT NULL,
    UNIQUE (run_id, target_date)
);
CREATE INDEX ix_predictions_region_target ON predictions (region_id, target_date);
CREATE INDEX ix_predictions_region_created ON predictions (region_id, created_at);

-- The SHAP breakdown, one row per factor (Part 08 §2.3), in rank order.
CREATE TABLE prediction_factors (
    prediction_id  INTEGER NOT NULL REFERENCES predictions (id) ON DELETE CASCADE,
    rank           INTEGER NOT NULL,
    feature        TEXT NOT NULL,
    label          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    value          REAL NOT NULL,
    display_value  TEXT NOT NULL,
    imputed        INTEGER NOT NULL CHECK (imputed IN (0, 1)),
    contribution   REAL NOT NULL,
    share_pct      REAL NOT NULL,
    direction      TEXT NOT NULL CHECK (direction IN ('increases_risk', 'decreases_risk', 'neutral')),
    PRIMARY KEY (prediction_id, rank),
    UNIQUE (prediction_id, feature)
);

CREATE TABLE users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'AUTHORITY' CHECK (role IN ('AUTHORITY')),
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at     TEXT NOT NULL
);

-- Logged-out tokens until they would have expired anyway (Part 15 §4).
CREATE TABLE revoked_tokens (
    jti         TEXT PRIMARY KEY,
    expires_at  TEXT NOT NULL
);

CREATE TABLE alerts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    code                 TEXT NOT NULL UNIQUE,
    year                 INTEGER NOT NULL,
    seq                  INTEGER NOT NULL,
    region_id            TEXT NOT NULL REFERENCES regions (id),
    severity             TEXT NOT NULL CHECK (severity IN ('NORMAL', 'HEATWAVE', 'SEVERE_HEATWAVE')),
    status               TEXT NOT NULL CHECK (status IN ('DRAFT', 'READY', 'ISSUED')),
    message              TEXT NOT NULL,
    prediction_id        TEXT REFERENCES prediction_runs (id),
    client_request_id    TEXT NOT NULL UNIQUE,
    request_fingerprint  TEXT NOT NULL,
    created_by           INTEGER NOT NULL REFERENCES users (id),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    issued_at            TEXT,
    issued_by            INTEGER REFERENCES users (id),
    UNIQUE (year, seq),
    CHECK ((status = 'ISSUED') = (issued_at IS NOT NULL))
);
CREATE INDEX ix_alerts_status ON alerts (status);
CREATE INDEX ix_alerts_region ON alerts (region_id);

CREATE TABLE alert_channel_deliveries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    INTEGER NOT NULL REFERENCES alerts (id) ON DELETE CASCADE,
    channel     TEXT NOT NULL CHECK (channel IN (
                    'PUBLIC_MOBILE_ALERT', 'GOVERNMENT_PORTAL', 'PUBLIC_DISPLAY_BOARDS',
                    'EMERGENCY_SERVICES', 'HOSPITALS_HEALTH_CENTRES')),
    status      TEXT NOT NULL CHECK (status IN ('READY', 'PENDING', 'NOTIFIED', 'FAILED')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    updated_at  TEXT NOT NULL,
    UNIQUE (alert_id, channel)
);

-- The deployed model and its Part 05 test metrics (static per version), for analytics.
CREATE TABLE model_metadata (
    model_version     TEXT PRIMARY KEY,
    model_family      TEXT NOT NULL,
    model_sha256      TEXT NOT NULL,
    explainer_id      TEXT,
    evaluation_id     TEXT NOT NULL,
    policy_version    TEXT NOT NULL,
    report            TEXT NOT NULL,
    test_rows         INTEGER NOT NULL,
    accuracy          REAL NOT NULL,
    precision_macro   REAL NOT NULL,
    recall_macro      REAL NOT NULL,
    f1_macro          REAL NOT NULL,
    mean_confidence   REAL NOT NULL,
    top_label_ece     REAL NOT NULL,
    per_class_json    TEXT NOT NULL,
    is_active         INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    deployed_at       TEXT NOT NULL
);
