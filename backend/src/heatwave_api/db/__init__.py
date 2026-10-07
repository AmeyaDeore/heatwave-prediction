"""SQLite persistence (Part 08): connection, numbered migrations, repository, CLI.

Schema and decisions: docs/database/README.md, docs/decisions/0007-database.md.
"""

from heatwave_api.db.connection import DatabaseError, connect, resolve_sqlite_path
from heatwave_api.db.migrate import MigrationError, apply_migrations, migration_status

__all__ = [
    "DatabaseError",
    "MigrationError",
    "apply_migrations",
    "connect",
    "migration_status",
    "resolve_sqlite_path",
]
