-- 0002: notification audit trail and public advisories (Part 09).
-- Documented in docs/notifications/README.md and docs/database/README.md.
-- Same portability rules as 0001.

-- Every dispatch attempt, one row per (channel, recipient, try). Append-only: this is
-- the answer to "did the warning actually go out, to whom, and when" after the fact.
CREATE TABLE notification_attempts (
    attempt_id    INTEGER PRIMARY KEY,
    alert_id      TEXT NOT NULL REFERENCES alerts (alert_id),
    channel       TEXT NOT NULL,
    mechanism     TEXT NOT NULL CHECK (mechanism IN ('sms', 'email', 'in_app')),
    provider      TEXT NOT NULL,          -- mock-sms, twilio, sendgrid, in_app, ...
    recipient     TEXT,                   -- NULL for in_app
    attempt       INTEGER NOT NULL CHECK (attempt >= 1),
    outcome       TEXT NOT NULL CHECK (outcome IN ('SUCCESS', 'TRANSIENT_FAILURE', 'PERMANENT_FAILURE')),
    detail        TEXT,                   -- provider error, sanitised
    provider_ref  TEXT,                   -- provider message id, for delivery receipts
    started_at    TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL CHECK (duration_ms >= 0),
    FOREIGN KEY (alert_id, channel) REFERENCES alert_channel_deliveries (alert_id, channel)
);
CREATE INDEX ix_notification_attempts_alert ON notification_attempts (alert_id, channel, attempt_id);

CREATE TRIGGER trg_notification_attempts_no_update BEFORE UPDATE ON notification_attempts
BEGIN SELECT RAISE(ABORT, 'notification attempts are append-only'); END;
CREATE TRIGGER trg_notification_attempts_no_delete BEFORE DELETE ON notification_attempts
BEGIN SELECT RAISE(ABORT, 'notification attempts are append-only'); END;

-- The in_app mechanism's "delivery": a published advisory the government portal and
-- public display boards poll. One per (alert, channel), so a retry cannot duplicate it.
CREATE TABLE public_advisories (
    advisory_id   INTEGER PRIMARY KEY,
    alert_id      TEXT NOT NULL REFERENCES alerts (alert_id),
    channel       TEXT NOT NULL,
    region_id     TEXT NOT NULL REFERENCES regions (region_id),
    severity      TEXT NOT NULL CHECK (severity IN ('HEATWAVE', 'SEVERE_HEATWAVE')),
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    UNIQUE (alert_id, channel)
);
CREATE INDEX ix_public_advisories_region_time ON public_advisories (region_id, published_at);
