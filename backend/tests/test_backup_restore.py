import sqlite3
from pathlib import Path

import pytest

from scripts.verify_sqlite_restore import COUNT_TABLES, REQUIRED_TABLES, verify_restore


def create_restore_fixture(path: Path, *, omit: str | None = None) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in sorted(REQUIRED_TABLES):
            if table == omit:
                continue
            if table == "alembic_version":
                connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
                connection.execute("INSERT INTO alembic_version VALUES ('0005_secure_device_claims')")
            else:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.commit()
    finally:
        connection.close()


def test_restore_verifier_checks_schema_counts_integrity_and_rollback(tmp_path: Path) -> None:
    restored = tmp_path / "restored.db"
    create_restore_fixture(restored)
    report = verify_restore(restored)
    assert report["integrity"] == "ok"
    assert report["foreign_keys"] == "ok"
    assert report["alembic_version"] == "0005_secure_device_claims"
    assert report["counts"] == {table: 0 for table in COUNT_TABLES}
    assert report["write_probe"] == "rolled_back"


def test_restore_verifier_rejects_an_incomplete_schema(tmp_path: Path) -> None:
    restored = tmp_path / "incomplete.db"
    create_restore_fixture(restored, omit="device_commands")
    with pytest.raises(ValueError, match="device_commands"):
        verify_restore(restored)
