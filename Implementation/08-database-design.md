# Part 08 — Database Design (SQLite)

**Depends on:** 01 (environment/repo); can proceed in parallel with 07
**Feeds into:** 07 (backend API), 09 (notifications), 14 (analytics), 16 (integration)
**Owner persona:** Backend engineer

> **Revision 2 (2026-10-20, examiner feedback, M2):** **MongoDB** becomes the application database, used by the Node.js API (Part 07 §B). The entities, relationships, query patterns, retention and backup rules below carry over. The SQLite schema built in this part is kept as the reference model the MongoDB design is ported from, and is no longer the application store. See [Revision 2](#revision-2--examiner-feedback-2026-10-20).

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

- [x] Full schema documented (tables, fields, types, constraints, relationships) matching Sections 2–3. *(`docs/database/README.md` §1–2: ER diagram and every column; the SQL is `backend/src/heatwave_api/db/migrations/0001_initial_schema.sql`. SHAP factors are the child table `prediction_factors`.)*
- [x] Indexes defined per Section 4. *((region, time) on predictions and weather_snapshots; status and region separately on alerts; per-alert lookup via the deliveries PK. `docs/database/README.md` §3; the latest-prediction query plan is asserted in a test.)*
- [x] Migration tooling/process chosen and a first migration applied to create the schema. *(Numbered SQL files + a checksummed runner, `uv run heatwave-db migrate`. Auto-applied in local/test; staging/production refuse to start while migrations are pending. `0001` applied to `data/local/heatwave.db`. §6.)*
- [x] Foreign key enforcement confirmed enabled. *(Enabled per connection and verified at connect time; a violation is tested to raise.)*
- [x] Schema cross-checked field-by-field against the UI mockups in Parts 11–14. *(`docs/database/README.md` §4. One open item belongs to Part 13: the Response Coordination panel.)*
- [x] Backup approach documented. *(`heatwave-db backup`: online-backup API, integrity check, `--keep` retention; restore steps and the backup-before-migrate rule in §5.)*

## 10. Handoff note template

> Schema migrations at: <path>. Entity-relationship summary: <link>. Database file location (per environment): <config key>. Part 07 can now implement data-access logic against this confirmed schema.

**Also produced:** `SqliteRepository` / `SqliteUserStore` wired into the API (persistence is no longer in memory), append-only and issued-alert triggers, `UNIQUE (created_by, client_request_id)`, `model_metadata` read by analytics, `heatwave-db` CLI (`migrate`, `status`, `seed`, `backup`, `import-weather`), ADR 0007 and log 08.

**Filled-in handoff:** Schema migrations at `backend/src/heatwave_api/db/migrations/`. Entity-relationship summary: [`docs/database/README.md`](../docs/database/README.md) §1. Database file location (per environment): `DATABASE_URL` (local `sqlite:///data/local/heatwave.db`, tests `sqlite:///:memory:`, deployed: a persistent volume, Part 18). Part 07's data access already runs against this schema.

## Revision 2 — examiner feedback (2026-10-20)

**R2 status (2026-10-20):** 🟡 **In progress.** ✅ Step 4 built (uncommitted): migrations runner, the `places`, `predictions`, `weather_snapshots` and `model_metadata` collections with validators and indexes, on the developer's MongoDB 7.0.31 in its own `heatwave_local` database. **Also built in step 4 (SQLite, the role-`app` reference):** migration `0003` adds the region hierarchy columns, so predictions keep round-tripping exactly. ⏳ The users, alerts and history collections (steps 5, 8, 9) and backup/restore (step 11) are pending.

**Why:** MongoDB integration is mandatory (M2) and the application stack is MERN. The entity model in §2–§3 was designed engine-neutral, so it maps onto collections without changing what the UI or API can show.

### R2.1 Collections (ported from §2)

| SQLite table(s) | MongoDB collection | Shape decision and why |
|---|---|---|
| `regions` | `places` | Seeded/upserted from `config/regions.yaml` at startup, as today. Adds `division`, `kind`, `parent` (Part 02 R2). Coordinates stay plain `lat`/`lon`: nothing queries by location, so no geo index is needed |
| `weather_snapshots` | `weather_snapshots` | One document per place × valid date × lead × source (`forecast` or `observed`), written when the API fetches conditions and by the observed-history import (Part 14 R2.1). Observed rows carry the class computed in Python, the rule version and the IMD cell |
| *(new)* | `history_summaries` | Per place × year (and × month) aggregates of the observed history: heatwave and severe days, longest spell, maximum Tmax and departure. Precomputed at import so the place comparison does not scan about 225,000 daily rows per request (Part 14 R2.6) |
| `predictions` + `prediction_factors` | `predictions` | The SHAP `factors` are an **embedded ordered array**. §2.3 chose a child table so analytics could query factors. In MongoDB an embedded array plus an aggregation `$unwind` gives the same query without a join, and a prediction is always read with its factors. The input values, model version, explainer id, forecast window and weather provenance are stored as returned by the ML service |
| `alerts` + `alert_channel_deliveries` | `alerts` | Per-channel deliveries are an **embedded `channels` array**. Saving an alert as ISSUED with every channel PENDING is then **one atomic document write**, which SQLite needed a transaction for. Adds `origin` (`manual` / `auto_draft`, Part 09 R2) |
| `notification_attempts` | `notification_attempts` | A separate collection, append-only. It grows per retry and is read per alert, so it is not embedded |
| `public_advisories` | `public_advisories` | Unique per alert × channel, as before |
| `users` + `user_regions` | `users` | Salted password hash only, display name, role; regions of responsibility become an embedded `region_ids` array (Part 15 R2) |
| *(new)* | `revoked_tokens` | Token ids revoked at logout, with a TTL index on expiry, so the collection empties itself (Part 15 R2) |
| `alert_sequences` | `counters` | The `HW-<year>-<seq>` alert sequence, incremented atomically per year |
| `model_metadata` | `model_metadata` | One document per model version, recorded from the ML service's `GET /model` when the version changes; `active: true` on the current one |
| `schema_migrations` | `_migrations` | Applied migration ids and checksums (R2.4) |

### R2.2 Indexes (ported from §4, query by query)
- `predictions`: `{region_id, lead_days, created_at desc}` serves latest-per-place, the composite `latest-by-region` aggregation for the map, and the Prediction page. `{valid_date, region_id}` serves analytics ("one per place-day, newest wins").
- `weather_snapshots`: `{region_id, valid_date}` for the temperature trend.
- `alerts`: `{status}`, `{region.id}`, `{created_at desc}`, plus **unique** `{created_by, client_request_id}`, the idempotency guarantee SQLite enforced with a UNIQUE constraint.
- `notification_attempts`: `{alert_id, started_at}`. `public_advisories`: unique `{alert_id, channel}`, and `{published_at desc}` for the polling feed.
- `users`: unique `{username}`. `revoked_tokens`: TTL on `expires_at`. `places`: unique `{id}`. `history_summaries`: unique `{region_id, year, month}`.
- `weather_snapshots` also gets unique `{region_id, valid_date, lead_days, source}`, so re-running an import or a refresh never duplicates a day.
- Each index is created by a migration and asserted in a test that inspects the query plan for the dashboard and analytics queries (the SQLite part asserted its latest-prediction plan the same way).

### R2.3 Integrity rules that SQLite enforced and MongoDB must enforce another way
| SQLite mechanism | MongoDB replacement |
|---|---|
| Foreign keys | References validated by the API before writing (place exists, prediction exists, user exists), plus `$jsonSchema` collection validators for required fields and enum values |
| CHECK enums (risk class, alert status, delivery status) | `$jsonSchema` enums with the exact vocabulary `NORMAL` / `HEATWAVE` / `SEVERE_HEATWAVE`, `DRAFT` / `READY` / `ISSUED`, `READY` / `PENDING` / `NOTIFIED` / `FAILED` |
| Append-only triggers (attempts) and the issued-alert immutability trigger | No update/delete code paths for attempts. Alert updates are conditional writes that match `status ≠ ISSUED` (except delivery status), so an issued alert's content cannot change. Both are covered by tests |
| UNIQUE constraints | Unique indexes (R2.2) |

### R2.4 Migrations and seeding
- Numbered migration scripts in `server/` that create collections, validators and indexes. They are recorded in `_migrations` with a checksum and applied automatically in local/test. Staging/production refuse to start with pending migrations, the same rule as §6.
- Seeding: `places` from `config/regions.yaml` at startup, the first official user via a CLI (Part 15 R2), predictions via the scoring CLI (Part 11 R2), weather history via the import CLI (Part 14 R2).
- **Existing SQLite data:** local demo data only, so no migration is required. An optional one-off import from `data/local/heatwave.db` can be written if someone wants their local history preserved.

### R2.5 Deployment, backup and retention
- Local: MongoDB 7 in a container or a native install (Part 01 R2). Staging/production: a managed MongoDB (for example an Atlas free/shared tier) or a self-hosted instance with authentication and TLS. One database per environment, never shared (Part 18 R2).
- No multi-document transactions are needed (R2.1 keeps each write in one document), so a standalone server is enough. A replica set is optional.
- Retention unchanged: predictions are never deleted (§5). Backups with `mongodump` on a schedule, with a **tested** `mongorestore` (Part 18 §7).

### R2 acceptance criteria
- [ ] Collections, validators and indexes in R2.1–R2.3 created by migrations; `docs/database/README.md` updated with the MongoDB model (and the SQLite model kept as the reference section). *(**Partly, step 4:** migrations 1–4 create `places`, `predictions`, `weather_snapshots`, `model_metadata` with `$jsonSchema` validators and indexes, recorded in `_migrations` with checksums. `users`/`revoked_tokens` (step 5), `alerts`/`notification_attempts`/`public_advisories`/`counters` (step 8) and `history_summaries` (step 9) come in their steps. `docs/database/README.md` has a MongoDB section for what exists.)*
- [ ] Every integrity rule in R2.3 enforced and tested (invalid enum rejected, unknown place rejected, attempts not updatable, issued alert content immutable, duplicate `client_request_id` rejected). *(**Partly:** the database rejects an invalid risk class (`HIGH`, lower-case), a lead over 3, a malformed date or region id, a non-prediction id and a missing payload; unknown places are rejected by the API before any write; snapshots are unique per place/day/lead/source. The alert rules come with step 8.)*
- [ ] Query plans asserted to use the R2.2 indexes for latest-by-region, alert listing and the analytics aggregations. *(**Partly:** latest-per-place (IXSCAN) and latest-by-region (DISTINCT_SCAN) on `latest_per_place` are asserted. Alert listing (step 8) and analytics (step 9) are pending.)*
- [x] Startup seeding of `places`, and the migration-pending refusal in staging/production. *(`server/src/bootstrap.ts`: local/test migrate automatically; staging/production stop with a `MigrationError` while any migration is pending (`npm run db:migrate` after a backup). Places are mirrored from `config/regions.yaml` at every start. Live: 18 places, migrations 1–4, model recorded in `model_metadata`.)*
- [ ] `mongodump`/`mongorestore` procedure documented and a restore tested once.
- [ ] Cross-check against the UI specs (§8) repeated for the R2 pages: map, place analysis, model-suggested drafts.
