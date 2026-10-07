# ADR 0007 — Database: SQLite schema, migrations, integrity

**Status:** Accepted, 2026-10-07 (Part 08)

## Decisions

| Need | Choice | Why |
|------|--------|-----|
| Engine (Part 00) | SQLite, one file, via the standard-library `sqlite3` driver | The fixed project decision. No ORM: the schema is small, the SQL is plain and portable, and there is no dependency to add. |
| Data access | `SqliteRepository` implements Part 07's `Repository` protocol; `SqliteUserStore` implements `UserStore` | Routers and services did not change. `build_context` now uses SQLite by default; `MemoryRepository` stays only as a test double. |
| SHAP factors (§2.3) | Child table `prediction_factors`, one row per ranked factor | As the plan asks: Part 14's "top driver" queries are plain SQL. A stored prediction reads back identical to the API response (tested). |
| Prediction inputs (§2.3) | Both: an FK to the `FORECAST` weather snapshot used **and** a JSON copy of the inputs | The FK gives traceability; the copy keeps the historical record stable if a snapshot is corrected. |
| Probabilities | One column per class (`prob_normal`, …) | The class vocabulary is fixed project-wide, and columns aggregate in SQL. |
| Retention (§5) | Predictions and factors append-only; issued alerts frozen and undeletable — **enforced by triggers**, not convention | The analytics history and the "why" of every warning must be trustworthy. A purge, if ever needed, is a migration with a decision. |
| Idempotency | `UNIQUE (created_by, client_request_id)` on `alerts` | Closes the race Part 07 flagged in its in-memory check. |
| Alert ids | `HW-<year>-<seq:04d>` from an `alert_sequences` counter (`UPSERT … RETURNING`) | Human-readable as in the UI, atomic, survives restarts (tested). |
| Model metadata (§2.7) | `model_metadata`, written at startup from the model actually loaded; one active row (partial unique index) | Always matches what is serving; analytics reads it from the database. Old versions stay because predictions reference them. |
| Regions | Upserted from `config/regions.yaml` at startup | The file stays the source of truth (Part 02); the table exists for foreign keys. |
| Migrations (§6) | Numbered SQL files, own ~130-line runner, checksums, one transaction per file | Plain SQL is reviewable and portable. Refuses edited applied files, gaps, and a database newer than the code. |
| When migrations run | Automatically at startup for `local`/`test`/in-memory; **staging/production refuse to start** while any are pending | Zero friction locally; in deployment, migration is an explicit step taken right after a backup. |
| Foreign keys (§7) | Enabled per connection **and verified** (fails loudly otherwise) | SQLite ignores them by default; the schema relies on them. |
| Concurrency (§7) | One connection behind a lock, WAL mode, `busy_timeout` | A few officials cannot saturate one writer. Named trigger to move to PostgreSQL: multiple API processes/hosts writing, or sustained concurrent writes. |
| Timestamps | UTC ISO-8601 text in one fixed format | Sorts and compares correctly as text in SQLite; maps directly to `TIMESTAMPTZ`. |
| Backups (§5) | `heatwave-db backup`: SQLite online-backup API + `integrity_check`, retention `--keep` | A consistent copy while the API runs (a raw copy of a WAL database can miss pages). |
| Demo user | Seeded only in `local`/`test`; deactivated at startup elsewhere | A database copied from a laptop must not carry a known password into staging. |

## Rejected alternatives

- **SQLAlchemy + Alembic:** two dependencies and an abstraction layer for ten tables. Revisit when the Postgres port happens, if a second dialect needs to be kept in sync.
- **Factors as a JSON column only:** the plan explicitly asks for rows, and Part 14 needs per-feature queries.
- **Auto-migrate in production:** a bad migration would run unattended, without a fresh backup.
- **A connection per request:** pointless for SQLite's single writer, and incompatible with the in-memory test database.

## Consequences

- Part 09's notifier results land in `alert_channel_deliveries` through `AlertService`. *(Update, Part 09: a per-channel `update_delivery` write was added for background dispatch, plus migration `0002` for the audit trail and advisories; see [ADR 0008](0008-notification-service.md).)*
- Part 13 must decide the Response Coordination panel: channel ids in `config/alert_channels.yaml` (no schema change) or a new table (migration `0002`).
- Part 14 can read `weather_snapshots` (`heatwave-db import-weather … --kind HISTORICAL`) for history beyond stored predictions.
- Part 15 adds user management on `users` / `user_regions` and decides role semantics (`viewer`/`official`/`admin` is the current CHECK; widening it is a migration).
- Part 18 must: mount `DATABASE_URL` on a persistent volume, run `heatwave-db backup && heatwave-db migrate` on deploy, schedule daily backups off-host, and run a single API process (or move to PostgreSQL).
