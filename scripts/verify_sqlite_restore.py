"""Validate an isolated Smart Fish Feeder SQLite restore."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REQUIRED_TABLES = {
    "alembic_version",
    "users",
    "devices",
    "telemetry",
    "feeding_schedules",
    "feeding_executions",
    "alerts",
    "device_commands",
}
COUNT_TABLES = (
    "users",
    "devices",
    "feeding_schedules",
    "device_commands",
    "telemetry",
    "alerts",
    "feeding_executions",
)


def verify_restore(database_path: Path) -> dict[str, object]:
    if not database_path.is_file() or database_path.stat().st_size == 0:
        raise ValueError("restored database is missing or empty")
    connection = sqlite3.connect(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"integrity_check failed: {integrity}")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise ValueError(f"foreign_key_check failed: {foreign_key_errors[:5]}")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise ValueError(f"required tables are missing: {', '.join(missing)}")
        version_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if version_row is None or not version_row[0]:
            raise ValueError("alembic version is missing")
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in COUNT_TABLES
        }
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE restore_write_probe (id INTEGER PRIMARY KEY, checked INTEGER NOT NULL)")
        connection.execute("INSERT INTO restore_write_probe (checked) VALUES (1)")
        assert connection.execute("SELECT checked FROM restore_write_probe").fetchone() == (1,)
        connection.rollback()
        probe_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='restore_write_probe'"
        ).fetchone()
        if probe_exists is not None:
            raise ValueError("restore write probe did not roll back")
        return {
            "database": str(database_path),
            "integrity": "ok",
            "foreign_keys": "ok",
            "alembic_version": str(version_row[0]),
            "counts": counts,
            "write_probe": "rolled_back",
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify_restore(args.database.resolve())
    except (AssertionError, OSError, sqlite3.DatabaseError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1
    payload = {"status": "passed", **report}
    rendered = json.dumps(payload, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
