"""`heatwave-db`: apply migrations, inspect, seed, back up, and import weather history.

    uv run heatwave-db migrate                 # apply pending migrations (the deploy step)
    uv run heatwave-db status                  # current version, pending files, row counts
    uv run heatwave-db seed                    # regions from config/regions.yaml
    uv run heatwave-db backup [--keep 14]      # consistent online copy into DATABASE_BACKUP_DIR
    uv run heatwave-db import-weather FILE.csv --kind HISTORICAL --source nasa_power

Every command reads DATABASE_URL from the same settings as the API (backend/.env).
"""

import argparse
import csv
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from heatwave_api.catalog import Catalog
from heatwave_api.config import Settings, get_settings
from heatwave_api.db.connection import MEMORY, connect, now_ts, resolve_sqlite_path
from heatwave_api.db.migrate import MigrationError, apply_migrations, migration_status
from heatwave_api.db.repository import WEATHER_FIELDS, Database, SqliteRepository
from heatwave_api.schemas import RegionOut

TABLES = (
    "regions",
    "weather_snapshots",
    "model_metadata",
    "users",
    "predictions",
    "prediction_factors",
    "alerts",
    "alert_channel_deliveries",
)


def seed_regions(db: Database, settings: Settings) -> int:
    regions = Catalog.load(settings).regions.values()
    SqliteRepository(db).upsert_regions(RegionOut(**r.__dict__) for r in regions)
    return len(regions)


def backup(settings: Settings, keep: int, dest_dir: Path | None = None) -> Path:
    """sqlite3's online backup API: a consistent copy even while the API is writing
    (a plain file copy of a WAL database can miss committed pages)."""
    source = resolve_sqlite_path(settings.database_url)
    if source == MEMORY:
        raise SystemExit("DATABASE_URL is in-memory: there is nothing to back up.")
    if not Path(source).exists():
        raise SystemExit(f"No database at {source}.")
    dest_dir = dest_dir or settings.database_backup_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = dest_dir / f"{Path(source).stem}-{stamp}.db"
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit(f"Backup {target} failed its integrity check.")
    finally:
        dst.close()
        src.close()
    if keep > 0:
        for old in sorted(dest_dir.glob(f"{Path(source).stem}-*.db"))[:-keep]:
            old.unlink()
    return target


def import_weather(db: Database, path: Path, kind: str, source: str) -> tuple[int, int]:
    """Load a pipeline feature CSV (region_id, date, lead_days, issued_at, tmax_c, ...)."""
    inserted = skipped = 0
    with path.open(newline="", encoding="utf-8") as fh, db.tx() as c:
        for row in csv.DictReader(fh):
            values = [
                float(row[f]) if row.get(f) not in (None, "") else None for f in WEATHER_FIELDS
            ]
            issued = row.get("issued_at") or f"{row['date']}T00:00:00+00:00"
            cur = c.execute(
                f"""INSERT INTO weather_snapshots (region_id, valid_date, lead_days, source,
                        issued_at, kind, {", ".join(WEATHER_FIELDS)}, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, {", ".join("?" * len(WEATHER_FIELDS))}, ?)
                    ON CONFLICT DO NOTHING""",
                (
                    row["region_id"],
                    row["date"],
                    int(row.get("lead_days") or 0),
                    source,
                    issued,
                    kind,
                    *values,
                    now_ts(),
                ),
            )
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
    return inserted, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-db", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply pending migrations")
    sub.add_parser("status", help="show migration state and row counts")
    sub.add_parser("seed", help="upsert regions from config/regions.yaml")
    b = sub.add_parser("backup", help="online backup into DATABASE_BACKUP_DIR")
    b.add_argument("--keep", type=int, default=14, help="backups to retain (0 = all)")
    b.add_argument("--dest", type=Path, help="override DATABASE_BACKUP_DIR")
    w = sub.add_parser("import-weather", help="load a feature CSV into weather_snapshots")
    w.add_argument("csv", type=Path)
    w.add_argument("--kind", choices=["HISTORICAL", "FORECAST"], default="HISTORICAL")
    w.add_argument("--source", required=True, help="e.g. imd, nasa_power, synthetic")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "backup":
        print(f"backup written: {backup(settings, args.keep, args.dest)}")
        return 0

    db = Database(connect(settings.database_url))
    try:
        if args.command == "migrate":
            applied = apply_migrations(db.conn)
            print(f"applied: {applied}" if applied else "already up to date")
        elif args.command == "status":
            status = migration_status(db.conn)
            print(f"database: {resolve_sqlite_path(settings.database_url)}")
            print(f"version:  {status.current}")
            print(f"pending:  {[m.path.name for m in status.pending] or 'none'}")
            if not status.pending:
                for table in TABLES:
                    count = db.read(f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608
                    print(f"  {table:<26}{count}")
        elif args.command == "seed":
            _require_current(db)
            print(f"regions upserted: {seed_regions(db, settings)}")
        elif args.command == "import-weather":
            _require_current(db)
            seed_regions(db, settings)  # snapshots reference regions
            inserted, skipped = import_weather(db, args.csv, args.kind, args.source)
            print(f"weather snapshots inserted: {inserted}, already present: {skipped}")
    except MigrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


def _require_current(db: Database) -> None:
    if pending := db.pending_migrations():
        raise MigrationError(f"Pending migrations {pending}: run `heatwave-db migrate` first.")


if __name__ == "__main__":
    sys.exit(main())
