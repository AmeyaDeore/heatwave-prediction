# Part 08 — Database Design (SQLite)

**Depends on:** 01 (environment/repo); can proceed in parallel with 07
**Feeds into:** 07 (backend API), 09 (notifications), 14 (analytics), 16 (integration)
**Owner persona:** Backend engineer

## 1. Objective

Design a relational schema in SQLite (per the architecture diagram) that supports predictions, alerts, weather snapshots, regions, users, and notification delivery tracking — structured so it could migrate to a server-based relational database later without a redesign.

## 2. Entities and their responsibilities

### 2.1 `regions`
- Represents each monitored location (Mumbai, Kurla, Andheri, Dharavi, Colaba, etc., per the dashboard mockup).
- Fields to include: a unique identifier, display name, coarser area/district grouping, and geographic coordinates (needed for weather-source lookups in Part 02/07).

### 2.2 `weather_snapshots`
- Represents a point-in-time set of meteorological readings for a region — both historical (for training/analytics) and current/forecast (for live prediction).
- Fields: region reference, timestamp/date, maximum temperature, seasonal normal temperature, relative humidity, wind speed, solar radiation, precipitation, source (IMD/NASA POWER/forecast/synthetic — for traceability back to Part 02), and a flag distinguishing historical-actual vs. forecast readings.

### 2.3 `predictions`
- Represents one output of `POST /api/predict` — this is the persisted record behind the dashboard's "Heatwave Risk" and the Prediction page.
- Fields: region reference, the weather snapshot it was computed from (or a copy of the input feature values, for a stable historical record even if the snapshot table is later modified), model version identifier (linking to Part 05's versioning), risk class, probability/confidence, forecast window (next 1–3 days), and a timestamp of when the prediction was made.
- A separate related table or a structured column for the ranked SHAP top-factors (feature name + signed contribution, ordered) — model this as its own child table (`prediction_factors`) with a foreign key back to `predictions`, one row per contributing factor, rather than cramming a list into a single column — this makes the analytics/reporting queries in Part 14 far simpler.

### 2.4 `alerts`
- Represents an alert record as shown in the Alert Management screen.
- Fields: unique alert identifier (the UI shows a human-readable format like a code + year + sequence number), region reference, severity, status (`DRAFT` / `READY` / `ISSUED`), the public advisory message text, created timestamp, created-by user reference (Part 15), and issued timestamp (nullable until issued).
- Link to the `predictions` record that triggered/justified the alert, where applicable, so an alert's "why" can be traced back to the prediction and its SHAP explanation.

### 2.5 `alert_channel_deliveries`
- Represents the per-channel distribution status shown in the UI (Public Mobile Alert, Government Portal, Public Display Boards, Emergency Services, Hospitals & Health Centres).
- Fields: alert reference, channel name, status (`READY` / `NOTIFIED` / `PENDING` / `FAILED`), and last-updated timestamp.
- This is the table Part 09's notification service writes back to after each delivery attempt.

### 2.6 `users`
- Represents authority/disaster-management-official accounts (Part 15 owns authentication logic, but the table itself belongs here).
- Fields: unique identifier, credentials (hashed, never plain text), display name, role, and associated region(s) of responsibility if access is scoped by region.

### 2.7 `model_metadata` (or similar)
- A small reference table holding the currently-active production model's version identifier and its evaluation metrics (Accuracy/Precision/Recall/F1 per Part 05), so `GET /api/analytics`'s "Model Performance" panel can read from the database rather than needing a separate config file. Updated whenever Part 05's production model pointer changes.

## 3. Relationships summary

- One `region` has many `weather_snapshots`, many `predictions`, many `alerts`.
- One `prediction` has many `prediction_factors` (the SHAP breakdown) and optionally many `alerts` that reference it.
- One `alert` has many `alert_channel_deliveries` (one per distribution channel selected).
- One `user` creates many `alerts`.

## 4. Indexing strategy

- Index `predictions` and `weather_snapshots` on (region, timestamp) — this is the dominant query pattern for both the live dashboard ("latest prediction per region") and analytics ("trend over time per region").
- Index `alerts` on (status) and (region) separately, to support both "show me all issued alerts" and "show me alerts for this region" efficiently.
- Index `alert_channel_deliveries` on (alert reference) for fast per-alert status lookups.

## 5. Data retention and historical integrity

- Decide whether `predictions` records are ever deleted (recommend: never delete, only ever append — this table is the historical record the Analytics page's trend charts depend on).
- Because SQLite is single-file and simple, plan a basic backup approach (periodic file copy) even for the mini-project scope, since this file is the sole source of truth for everything the dashboard shows.

## 6. Migration strategy (schema evolution)

- Adopt a migration-script approach from day one (even simple, numbered SQL migration files) rather than hand-editing the database ad hoc — this matters because the schema above will almost certainly need small additions as Parts 09–15 are implemented (e.g., new alert statuses, new channel types).
- Document the process for applying migrations in both local development and the deployed environment (Part 18).

## 7. SQLite-specific considerations

- Enable foreign key constraint enforcement explicitly (SQLite does not enforce these by default) — this schema relies on foreign keys being real constraints, not just documentation.
- Plan for SQLite's single-writer concurrency model — for this project's expected load (a small number of authority users), this is not a practical bottleneck, but it should be a documented, conscious decision (and named explicitly as the reason a future migration to a server-based database might eventually be warranted, per Part 00's cross-cutting decision).
- Store the SQLite file path via the environment configuration from Part 01, not hard-coded, so it can point to different locations in dev/test/production.

## 8. Non-functional requirements

- Schema must support the exact fields shown in every frontend mockup screen (Parts 11–14) — cross-check the schema against those UI specs explicitly before considering this part done.
- All monetary-equivalent "source of truth" data (predictions, alerts) must never be derivable-only from cache/frontend state — the database is authoritative.

## 9. Acceptance criteria / "done"

- [ ] Full schema documented (tables, fields, types, constraints, relationships) matching Sections 2–3.
- [ ] Indexes defined per Section 4.
- [ ] Migration tooling/process chosen and a first migration applied to create the schema.
- [ ] Foreign key enforcement confirmed enabled.
- [ ] Schema cross-checked field-by-field against the UI mockups in Parts 11–14.
- [ ] Backup approach documented.

## 10. Handoff note template

> Schema migrations at: <path>. Entity-relationship summary: <link>. Database file location (per environment): <config key>. Part 07 can now implement data-access logic against this confirmed schema.
