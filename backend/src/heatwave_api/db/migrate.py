"""Numbered SQL migrations: `db/migrations/NNNN_<name>.sql`, applied in order, once.

Each file runs in one transaction together with its `schema_migrations` row, so a
failed migration leaves the database exactly as it was. Applied files are checksummed:
editing one after it ran anywhere is an error, because that database and a fresh one
would silently differ. Change the schema with a new file instead.
"""

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from heatwave_api.db.connection import now_ts

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.replace("\r\n", "\n").encode()).hexdigest()


@dataclass(frozen=True)
class Status:
    applied: list[int]
    pending: list[Migration]
    current: int  # 0 = empty database


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"Migration file name not NNNN_name.sql: {path.name}")
        found.append(Migration(int(match.group(1)), match.group(2), path))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(
            f"Migrations must be numbered 0001, 0002, ... without gaps: {versions}"
        )
    return found


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version     INTEGER PRIMARY KEY,
               name        TEXT NOT NULL,
               checksum    TEXT NOT NULL,
               applied_at  TEXT NOT NULL
           )"""
    )
    conn.commit()


def migration_status(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> Status:
    _ensure_table(conn)
    known = {m.version: m for m in discover(directory)}
    applied = {
        row["version"]: row["checksum"]
        for row in conn.execute("SELECT version, checksum FROM schema_migrations")
    }
    for version, checksum in sorted(applied.items()):
        if version not in known:
            raise MigrationError(
                f"The database is at migration {version}, which this code does not have. "
                "Deploy the newer code (never roll the database back by hand)."
            )
        if known[version].checksum != checksum:
            raise MigrationError(
                f"Migration {known[version].path.name} was edited after it was applied. "
                "Restore the file and put the change in a new migration."
            )
    pending = [m for v, m in sorted(known.items()) if v not in applied]
    return Status(sorted(applied), pending, max(applied, default=0))


def apply_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply every pending migration; return the versions applied (may be empty)."""
    done = []
    for migration in migration_status(conn, directory).pending:
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n;\n"
            "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES "
            f"({migration.version}, '{migration.name}', '{migration.checksum}', '{now_ts()}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(f"Migration {migration.path.name} failed: {exc}") from exc
        done.append(migration.version)
    return done
