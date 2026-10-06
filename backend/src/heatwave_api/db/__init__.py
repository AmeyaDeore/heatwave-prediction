"""SQLite connections and numbered SQL migrations.

    db = Database(path)
    db.migrate()                 # applies migrations/NNNN_*.sql not yet recorded
    with db.connect() as conn:   # foreign keys ON, rows as sqlite3.Row
        ...

Migrations are plain SQL files, applied in number order, each in its own
transaction, and recorded in ``schema_migrations``. A recorded migration whose file
has since changed is refused: edit the schema with a new migration, never by
rewriting an applied one (Part 08 §6).
"""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class MigrationError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path, migrations_dir: Path = MIGRATIONS_DIR):
        self.path = Path(path)
        self.migrations_dir = migrations_dir

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: transactions are explicit (BEGIN ... COMMIT), so a
        # multi-statement write is all-or-nothing and nothing commits implicitly.
        # check_same_thread=False: FastAPI may open the connection (a dependency) and use
        # it (the endpoint) on different worker threads. One request uses it at a time.
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    def migrations(self) -> list[tuple[str, Path]]:
        files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        return [(f.stem, f) for f in files]

    def migrate(self) -> list[str]:
        """Apply pending migrations. Returns the versions applied now."""
        applied_now = []
        with self.connect() as conn:
            # WAL lets the dashboard read while an alert is being written.
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            done = {
                row["version"]: row["sha256"]
                for row in conn.execute("SELECT version, sha256 FROM schema_migrations")
            }
            for version, path in self.migrations():
                sql = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                if version in done:
                    if done[version] != digest:
                        raise MigrationError(
                            f"Migration {version} was applied, but {path.name} has changed "
                            "since. Add a new migration instead of editing an applied one."
                        )
                    continue
                try:
                    conn.executescript(
                        "BEGIN;\n"
                        + sql
                        + "\nINSERT INTO schema_migrations (version, sha256, applied_at) "
                        + f"VALUES ('{version}', '{digest}', '{utcnow()}');\nCOMMIT;"
                    )
                except sqlite3.Error as exc:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise MigrationError(f"Migration {version} failed: {exc}") from exc
                applied_now.append(version)
            if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise MigrationError("SQLite foreign key enforcement could not be enabled")
        return applied_now

    def applied(self) -> list[str]:
        with self.connect() as conn:
            return [
                r["version"]
                for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]

    def ping(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT 1").fetchone()
