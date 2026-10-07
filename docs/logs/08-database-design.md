# Log 08 — Database design (SQLite)

| | |
|---|---|
| Plan | [Implementation/08-database-design.md](../../Implementation/08-database-design.md) |
| Status | Complete against the plan's checklist. One UI question is handed to Part 13 (Response Coordination panel) |
| Date | 2026-10-07 |
| Branch / commits | `part-07/backend-api` (on top of the uncommitted Part 07 work, which it depends on). Not committed yet |
| Tests | 16 new in `backend/tests/test_database.py`; the 81 existing backend tests now run against in-memory SQLite. 97 backend, 253 total passing |

## Summary

Part 08 added the SQLite schema (10 tables + migration bookkeeping), a checksummed numbered-SQL migration runner, `SqliteRepository` and `SqliteUserStore` implementing Part 07's protocols, and a `heatwave-db` CLI. The API now uses the database by default, so **predictions, SHAP factors, alerts, channel deliveries and users survive restarts**, which removes Part 07's "must not be deployed" blocker. Integrity rules the plan states as policy (append-only predictions, immutable issued alerts, real foreign keys, atomic idempotency) are enforced by the database itself. It was exercised end to end on the real production model against the real `data/local/heatwave.db`.

## What was built

| Path | Role |
|---|---|
| `backend/src/heatwave_api/db/migrations/0001_initial_schema.sql` | The schema: `regions`, `weather_snapshots`, `model_metadata`, `users`, `user_regions`, `predictions`, `prediction_factors`, `alert_sequences`, `alerts`, `alert_channel_deliveries`; CHECK constraints, indexes, 6 integrity triggers |
| `db/connection.py` | `DATABASE_URL` → path (repo-root relative, absolute, or `:memory:`); pragmas (FKs **verified** on, WAL, busy timeout); the one UTC timestamp format |
| `db/migrate.py` | Discovery (`NNNN_name.sql`, no gaps), per-file transaction with its `schema_migrations` row, SHA-256 checksums, refuses edited/unknown migrations |
| `db/repository.py` | `Database` (one connection + lock), `SqliteRepository` (every `Repository` method + `upsert_regions`, `record_active_model`, `active_model`), `SqliteUserStore` (`get_by_*`, `upsert`, `deactivate`) |
| `db/cli.py` | `heatwave-db migrate / status / seed / backup [--keep N] [--dest] / import-weather CSV --kind --source` |
| `app.py` | `open_database()`: migrate (local/test/in-memory) or refuse to start (staging/production with pending migrations); upsert regions; seed or deactivate the demo user; record the loaded model; close the DB on shutdown |
| `repositories.py` | Protocol gains `record_active_model` / `active_model`; `MemoryRepository` kept as a test double |
| `services.py` | Analytics reads Model Performance from `model_metadata` (falls back to the loaded model) |
| `config.py`, `backend/.env.example` | New `DATABASE_BACKUP_DIR` (default `data/local/backups`) |
| `backend/pyproject.toml` | `[project.scripts] heatwave-db` |
| `backend/tests/conftest.py`, `test_production_model.py` | Every test gets `sqlite:///:memory:` (autouse fixture + one module-level `Settings`) |
| `backend/tests/test_database.py` | 16 tests: migrations, FKs, indexes/query plan, triggers, round-trip, restart persistence, startup policy, CLI and backup |
| `docs/database/README.md`, `docs/decisions/0007-database.md` | Schema doc (ER diagram, every column, indexes, UI cross-check, retention, backups, migrations, SQLite decisions, Postgres path) and ADR |

**Dependency change:** none at runtime (standard-library `sqlite3`). New console script only; `uv sync` registers it.
**Docs updated:** `docs/api/README.md` (§2 analytics, §8 limits, intro), ADR 0006 consequences, `backend/README.md`, `config/README.md`, `docs/README.md`, `docs/configuration-and-secrets.md`, `docs/local-dev-runbook.md` §6, the Part 08 plan checklist.

## Key decisions and why

Full table in [ADR 0007](../decisions/0007-database.md). The ones that matter most:

- **No ORM, plain SQL migrations.** Ten tables do not justify SQLAlchemy + Alembic; plain SQL is reviewable and maps to PostgreSQL almost line for line (docs/database §8).
- **Integrity in the database, not in convention.** Triggers make predictions/factors append-only and freeze issued alerts (only `updated_at` moves while Part 09 writes delivery results); `CHECK` ties `issued_at` to `ISSUED`; a CHECK rejects non-scrypt password values.
- **Prediction inputs stored twice on purpose:** FK to the `FORECAST` snapshot used (traceability) plus a JSON copy (a stable record if a snapshot is corrected). A stored prediction reads back byte-identical to the API response.
- **Migrations run themselves only where it is safe.** Local/test/in-memory auto-migrate; staging/production refuse to start until `heatwave-db backup && heatwave-db migrate` has been run.
- **Single writer, documented.** One connection behind a lock + WAL. The named trigger for PostgreSQL is multiple API processes/hosts or sustained concurrent writes.
- **`model_metadata` is written from the model actually loaded** at startup, so the analytics panel can never disagree with what is serving.

## Verification

```text
$ uv run pytest -q
253 passed in 48.15s
$ uv run pytest backend/tests/test_database.py -q
16 passed in 1.13s
$ uv run ruff check . && uv run ruff format --check .
All checks passed! / 137 files already formatted

$ uv run heatwave-db migrate
applied: [1]
$ uv run heatwave-db seed
regions upserted: 5
$ uv run heatwave-db import-weather data/sample/forecast_features.csv --kind FORECAST --source pipeline_sample
weather snapshots inserted: 20, already present: 0
```

Then the real app (`create_app(Settings())`, real production model) through a test client: `POST /predict {dharavi, lead 1}` → `NORMAL 0.9996`, 7 factors; `/health/ready` → `ready: True`, model `xgboost-20260928T100821Z-0bde51`, `weather_data: stale` (the committed sample is from 2026-09-28); `/analytics` model performance read from `model_metadata` → same version.

```text
$ uv run heatwave-db status
version:  1     pending:  none
  regions 5 · weather_snapshots 21 · model_metadata 1 · users 1 · predictions 1
  prediction_factors 7 · alerts 0 · alert_channel_deliveries 0
$ uv run heatwave-db backup --keep 3
backup written: data/local/backups/heatwave-20261007T093830Z.db
```

What the tests pin down: FK pragma reads 1 and a violation raises; `0001` creates every table and re-running is a no-op; edited migration, numbering gap, newer-than-code database and a failing migration (rolled back completely) are all refused; the dashboard's latest-prediction query uses `ix_predictions_region_lead_created` (`EXPLAIN QUERY PLAN`); UPDATE/DELETE on predictions and factors abort; an issued alert cannot be edited or deleted while its deliveries read back in order; one active model row; a file database keeps predictions, idempotent replays and the alert sequence across an app restart; staging refuses pending migrations; a local database started as staging rejects the demo login; CLI migrate/seed/import (idempotent)/status/backup (retention, readable copy).

## Deviations from the plan and issues found

- **Test isolation bug found and fixed.** After wiring SQLite in, tests that build their own `Settings` used the default file `data/local/heatwave.db`, so a demo user seeded by one test made `test_no_demo_user_exists_outside_local_and_test` fail. Fixed with an autouse `DATABASE_URL=sqlite:///:memory:` fixture plus the one module-level `Settings` in `test_production_model.py`. The stray file the test run had created was deleted.
- **Behaviour change beyond the plan:** outside local/test, startup now *deactivates* `user_demo` if present. Without it, a database copied from a laptop would carry a known password into staging (the case the failing test exposed).
- **In-memory databases always auto-migrate,** even under `APP_ENV=staging`, since they can never be migrated beforehand (needed by existing staging-mode startup tests).
- `weather_snapshots` gets one `FORECAST` row per distinct reading a prediction used, under the reading's own `source`. Rows imported with `import-weather` under a different `--source` label are separate rows (the 21 above = 20 imported + 1 from the prediction). Harmless, but import with the same source name the API uses if you want them to merge.
- Part 13's Response Coordination panel is not modelled: the plan leaves the reuse-channels vs separate-tracker choice to Part 13. Both options are mapped in docs/database §4.

## Open items / follow-ups

- **Part 09:** delivery results already land in `alert_channel_deliveries` via `AlertService`; a retry job can use `ix_alert_channel_deliveries_status`.
- **Part 13:** decide Response Coordination (channel ids in YAML, or migration `0002`).
- **Part 14:** read `HISTORICAL` `weather_snapshots` for trends longer than stored predictions.
- **Part 15:** user management on `users` / `user_regions`; confirm the `viewer`/`official`/`admin` role set (widening it is a migration).
- **Part 18:** persistent volume for `DATABASE_URL`; `heatwave-db backup && heatwave-db migrate` in the deploy; daily off-host backups; a single API process.

## Handoff

Schema migrations at `backend/src/heatwave_api/db/migrations/`. Entity-relationship summary: [docs/database/README.md](../database/README.md) §1 (every column in §2, UI cross-check in §4). Database file location per environment: `DATABASE_URL` (local `sqlite:///data/local/heatwave.db`, tests `sqlite:///:memory:`, deployed a persistent volume). The API already reads and writes through `SqliteRepository`; later parts add tables with `0002_…sql` and a test, never by editing `0001`.
