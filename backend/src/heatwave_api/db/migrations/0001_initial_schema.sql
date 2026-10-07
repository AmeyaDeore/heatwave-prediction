-- 0001: the initial schema (Part 08). Documented in docs/database/README.md.
--
-- Never edit this file once applied anywhere: the runner checksums it. Change the
-- schema with a new numbered file (0002_...sql).
--
-- Portability rules, so a later move to PostgreSQL is a port, not a redesign:
--   * timestamps are UTC ISO-8601 TEXT ("2026-10-07T09:30:00.000000+00:00") -> TIMESTAMPTZ
--   * dates are ISO TEXT ("2026-10-07") -> DATE; booleans are 0/1 INTEGER -> BOOLEAN
--   * enums are TEXT + CHECK (same spelling as the API: NORMAL / HEATWAVE / SEVERE_HEATWAVE)
--   * INTEGER PRIMARY KEY surrogates -> BIGINT GENERATED ALWAYS AS IDENTITY
--   * no SQLite-only types; triggers are the only dialect-specific part (-> plpgsql)

-- -- regions --------------------------------------------------------------------------
-- Seeded (upserted) from config/regions.yaml at startup and by `heatwave-db seed`;
-- the file stays the source of truth, the table exists so everything can reference it.
CREATE TABLE regions (
    region_id   TEXT PRIMARY KEY CHECK (region_id GLOB '[a-z][a-z0-9_]*'),
    name        TEXT NOT NULL,
    district    TEXT NOT NULL,
    state       TEXT NOT NULL,
    zone        TEXT NOT NULL,
    lat         REAL NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon         REAL NOT NULL CHECK (lon BETWEEN -180 AND 180),
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- -- weather_snapshots ----------------------------------------------------------------
-- One region's readings for one valid date, as issued by one source at one time.
-- kind: HISTORICAL = observed actuals (training/analytics imports),
--       FORECAST   = current/forecast conditions used for live prediction (lead 0-3).
CREATE TABLE weather_snapshots (
    snapshot_id    INTEGER PRIMARY KEY,
    region_id      TEXT NOT NULL REFERENCES regions (region_id),
    valid_date     TEXT NOT NULL,
    lead_days      INTEGER NOT NULL DEFAULT 0 CHECK (lead_days BETWEEN 0 AND 3),
    kind           TEXT NOT NULL CHECK (kind IN ('HISTORICAL', 'FORECAST')),
    source         TEXT NOT NULL,          -- imd / nasa_power / open_meteo / synthetic / ...
    issued_at      TEXT NOT NULL,
    tmax_c         REAL,
    normal_tmax_c  REAL,                   -- seasonal normal for the date (Part 03)
    rh_pct         REAL CHECK (rh_pct IS NULL OR rh_pct BETWEEN 0 AND 100),
    wind_ms        REAL CHECK (wind_ms IS NULL OR wind_ms >= 0),
    solar_mj_m2    REAL CHECK (solar_mj_m2 IS NULL OR solar_mj_m2 >= 0),
    precip_mm      REAL CHECK (precip_mm IS NULL OR precip_mm >= 0),
    recorded_at    TEXT NOT NULL,
    UNIQUE (region_id, valid_date, lead_days, source, issued_at)
);
CREATE INDEX ix_weather_snapshots_region_date ON weather_snapshots (region_id, valid_date);

-- -- model_metadata -------------------------------------------------------------------
-- Every model version that has served predictions, plus its held-out metrics (Part 05).
-- Exactly one row is active: the version the running service loaded.
CREATE TABLE model_metadata (
    model_version          TEXT PRIMARY KEY,
    model_family           TEXT NOT NULL,
    explainer_id           TEXT NOT NULL,
    labeling_rule_version  TEXT NOT NULL,
    test_rows              INTEGER NOT NULL CHECK (test_rows >= 0),
    accuracy               REAL NOT NULL CHECK (accuracy BETWEEN 0 AND 1),
    precision_macro        REAL NOT NULL CHECK (precision_macro BETWEEN 0 AND 1),
    recall_macro           REAL NOT NULL CHECK (recall_macro BETWEEN 0 AND 1),
    f1_macro               REAL NOT NULL CHECK (f1_macro BETWEEN 0 AND 1),
    performance_json       TEXT NOT NULL,  -- the full ModelPerformance block (per-class, calibration)
    is_active              INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    first_seen_at          TEXT NOT NULL,
    activated_at           TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_model_metadata_one_active ON model_metadata (is_active) WHERE is_active = 1;

-- -- users ----------------------------------------------------------------------------
-- Authority accounts. Part 15 owns the auth logic; the table lives here.
CREATE TABLE users (
    user_id        TEXT PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL CHECK (password_hash LIKE 'scrypt$%$%'),  -- never plain text
    display_name   TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('viewer', 'official', 'admin')),
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

-- Regions an account is responsible for. No rows = not scoped (Part 15 decides the rule).
CREATE TABLE user_regions (
    user_id    TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    region_id  TEXT NOT NULL REFERENCES regions (region_id),
    PRIMARY KEY (user_id, region_id)
);

-- -- predictions (append-only) --------------------------------------------------------
-- One row per POST /api/v1/predict. The inputs are copied in (inputs_json and the
-- snapshot), so the record stays true even if a snapshot is later corrected.
CREATE TABLE predictions (
    prediction_id             TEXT PRIMARY KEY,
    created_at                TEXT NOT NULL,
    region_id                 TEXT NOT NULL REFERENCES regions (region_id),
    weather_snapshot_id       INTEGER REFERENCES weather_snapshots (snapshot_id),
    model_version             TEXT NOT NULL REFERENCES model_metadata (model_version),
    explainer_id              TEXT NOT NULL,
    valid_date                TEXT NOT NULL,
    lead_days                 INTEGER NOT NULL CHECK (lead_days BETWEEN 0 AND 3),
    horizon_days              INTEGER NOT NULL DEFAULT 3,
    forecast_issued_at        TEXT NOT NULL,
    risk_class                TEXT NOT NULL CHECK (risk_class IN ('NORMAL', 'HEATWAVE', 'SEVERE_HEATWAVE')),
    confidence                REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    prob_normal               REAL NOT NULL CHECK (prob_normal BETWEEN 0 AND 1),
    prob_heatwave             REAL NOT NULL CHECK (prob_heatwave BETWEEN 0 AND 1),
    prob_severe_heatwave      REAL NOT NULL CHECK (prob_severe_heatwave BETWEEN 0 AND 1),
    inputs_json               TEXT NOT NULL,  -- raw model inputs, before imputation
    explanation_json          TEXT NOT NULL,  -- explanation header; factors are rows below
    recommended_actions_json  TEXT NOT NULL,
    actions_version           TEXT NOT NULL,
    weather_source            TEXT NOT NULL,
    weather_issued_at         TEXT NOT NULL,
    weather_age_hours         REAL NOT NULL,
    weather_stale             INTEGER NOT NULL CHECK (weather_stale IN (0, 1))
);
CREATE INDEX ix_predictions_region_created ON predictions (region_id, created_at);
CREATE INDEX ix_predictions_region_lead_created ON predictions (region_id, lead_days, created_at);
CREATE INDEX ix_predictions_created ON predictions (created_at);

-- The ranked SHAP breakdown: one row per factor, rank 1 = largest |contribution|.
CREATE TABLE prediction_factors (
    prediction_id  TEXT NOT NULL REFERENCES predictions (prediction_id),
    rank           INTEGER NOT NULL CHECK (rank >= 1),
    feature        TEXT NOT NULL,
    label          TEXT NOT NULL,
    unit           TEXT NOT NULL,
    value          REAL NOT NULL,
    display_value  TEXT NOT NULL,
    imputed        INTEGER NOT NULL CHECK (imputed IN (0, 1)),
    contribution   REAL NOT NULL,       -- signed
    share_pct      REAL NOT NULL,
    direction      TEXT NOT NULL CHECK (direction IN ('increases_risk', 'decreases_risk', 'neutral')),
    PRIMARY KEY (prediction_id, rank)
);
CREATE INDEX ix_prediction_factors_feature ON prediction_factors (feature);

-- Retention (Part 08 §5): predictions are the historical record. Never updated, never deleted.
CREATE TRIGGER trg_predictions_no_update BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TRIGGER trg_predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are append-only'); END;
CREATE TRIGGER trg_prediction_factors_no_update BEFORE UPDATE ON prediction_factors
BEGIN SELECT RAISE(ABORT, 'prediction factors are append-only'); END;
CREATE TRIGGER trg_prediction_factors_no_delete BEFORE DELETE ON prediction_factors
BEGIN SELECT RAISE(ABORT, 'prediction factors are append-only'); END;

-- -- alerts ---------------------------------------------------------------------------
-- alert_id is the human-readable "HW-<year>-<seq:04d>" shown in the Alert Management UI.
CREATE TABLE alert_sequences (
    year      INTEGER PRIMARY KEY,
    last_seq  INTEGER NOT NULL CHECK (last_seq >= 0)
);

CREATE TABLE alerts (
    alert_id           TEXT PRIMARY KEY CHECK (alert_id GLOB 'HW-[0-9][0-9][0-9][0-9]-[0-9]*'),
    region_id          TEXT NOT NULL REFERENCES regions (region_id),
    prediction_id      TEXT REFERENCES predictions (prediction_id),
    severity           TEXT NOT NULL CHECK (severity IN ('HEATWAVE', 'SEVERE_HEATWAVE')),
    status             TEXT NOT NULL CHECK (status IN ('DRAFT', 'READY', 'ISSUED')),
    message            TEXT NOT NULL CHECK (length(message) BETWEEN 10 AND 1000),
    created_by         TEXT NOT NULL REFERENCES users (user_id),
    client_request_id  TEXT,             -- idempotency key, unique per creator
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    issued_at          TEXT,
    CHECK ((status = 'ISSUED') = (issued_at IS NOT NULL)),
    UNIQUE (created_by, client_request_id)
);
CREATE INDEX ix_alerts_status ON alerts (status);
CREATE INDEX ix_alerts_region ON alerts (region_id);
CREATE INDEX ix_alerts_created ON alerts (created_at);

-- An issued warning is a public record: its content and status are frozen (only
-- updated_at moves, while channel deliveries are written back). Deleting it is refused.
CREATE TRIGGER trg_alerts_issued_frozen BEFORE UPDATE ON alerts
WHEN OLD.status = 'ISSUED' AND (
    NEW.status IS NOT OLD.status OR NEW.severity IS NOT OLD.severity
    OR NEW.message IS NOT OLD.message OR NEW.region_id IS NOT OLD.region_id
    OR NEW.prediction_id IS NOT OLD.prediction_id OR NEW.issued_at IS NOT OLD.issued_at
)
BEGIN SELECT RAISE(ABORT, 'an issued alert cannot be changed'); END;
CREATE TRIGGER trg_alerts_issued_no_delete BEFORE DELETE ON alerts
WHEN OLD.status = 'ISSUED'
BEGIN SELECT RAISE(ABORT, 'an issued alert cannot be deleted'); END;

-- Per-channel distribution status; Part 09's notifier writes back here after each attempt.
CREATE TABLE alert_channel_deliveries (
    alert_id    TEXT NOT NULL REFERENCES alerts (alert_id) ON DELETE CASCADE,
    channel     TEXT NOT NULL CHECK (channel GLOB '[a-z][a-z0-9_]*'),  -- config/alert_channels.yaml id
    label       TEXT NOT NULL,          -- the label at the time, for a faithful history
    position    INTEGER NOT NULL,       -- order the official listed the channels in
    status      TEXT NOT NULL CHECK (status IN ('READY', 'NOTIFIED', 'PENDING', 'FAILED')),
    detail      TEXT,                   -- why a delivery FAILED
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (alert_id, channel)     -- also the per-alert lookup index (Part 08 §4)
);
CREATE INDEX ix_alert_channel_deliveries_status ON alert_channel_deliveries (status);
