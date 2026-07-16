import sqlite3
from unittest.mock import MagicMock

import pytest
from app.database import SessionLocal, SqliteBusyError, engine, run_with_sqlite_lock_retry, settings
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def test_sqlite_connections_enable_wal_busy_timeout_and_foreign_keys() -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == settings.sqlite_busy_timeout_ms
        assert connection.scalar(text("PRAGMA synchronous")) == 1
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_sqlite_lock_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock(spec=Session)
    attempts = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database is locked"))
        return "completed"

    monkeypatch.setattr("app.database.time.sleep", delays.append)
    assert run_with_sqlite_lock_retry(session, operation, operation_name="test_write") == "completed"
    assert attempts == 3
    assert session.rollback.call_count == 2
    assert delays == [
        settings.sqlite_lock_retry_base_delay_ms / 1_000,
        settings.sqlite_lock_retry_base_delay_ms * 2 / 1_000,
    ]


def test_sqlite_lock_retry_reports_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock(spec=Session)

    def operation() -> None:
        raise OperationalError("UPDATE", {}, sqlite3.OperationalError("database table is locked"))

    monkeypatch.setattr("app.database.time.sleep", lambda _: None)
    with pytest.raises(SqliteBusyError, match="remained busy"):
        run_with_sqlite_lock_retry(session, operation, operation_name="test_exhaustion")
    assert session.rollback.call_count == settings.sqlite_lock_retry_attempts


def test_regular_operational_errors_are_not_retried() -> None:
    with SessionLocal() as session:
        with pytest.raises(OperationalError, match="disk I/O error"):
            run_with_sqlite_lock_retry(
                session,
                lambda: (_ for _ in ()).throw(
                    OperationalError("UPDATE", {}, sqlite3.OperationalError("disk I/O error"))
                ),
                operation_name="non_lock_error",
            )
