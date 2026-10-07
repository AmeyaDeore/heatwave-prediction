"""Opening the database the same way everywhere, with the pragmas the schema relies on.

SQLite does not enforce foreign keys unless asked, per connection. `connect()` turns
them on and then *checks* they are on, so a schema whose FKs are only documentation
cannot happen silently (Part 08 §7).
"""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from heatwave_api.config import REPO_ROOT

MEMORY = ":memory:"


class DatabaseError(RuntimeError):
    pass


def resolve_sqlite_path(database_url: str) -> Path | str:
    """`sqlite:///relative/path.db` (from the repo root), `sqlite:////abs/path.db`,
    `sqlite:///C:/abs/path.db`, or `sqlite:///:memory:`."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise DatabaseError(
            f"Only SQLite is supported for now (DATABASE_URL={database_url.split(':', 1)[0]}:...)."
            " See docs/database/README.md §8 for the PostgreSQL migration path."
        )
    rest = database_url[len(prefix) :]
    if rest in ("", MEMORY):
        return MEMORY
    path = Path(rest)
    return path if path.is_absolute() else REPO_ROOT / path


def connect(database_url: str) -> sqlite3.Connection:
    target = resolve_sqlite_path(database_url)
    if isinstance(target, Path):
        target.parent.mkdir(parents=True, exist_ok=True)
    # One connection shared behind a lock (see SqliteRepository), hence check_same_thread.
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if target != MEMORY:
        # WAL: readers (e.g. a backup or `heatwave-db status`) never block the writer.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        conn.close()
        raise DatabaseError("This SQLite build refused to enable foreign key enforcement.")
    return conn


def ts(value: datetime) -> str:
    """One fixed UTC text format, so stored timestamps sort and compare correctly as text."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def now_ts() -> str:
    return ts(datetime.now(UTC))


def ds(value: date) -> str:
    return value.isoformat()
