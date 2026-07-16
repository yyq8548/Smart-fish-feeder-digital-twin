import logging
import sqlite3
import time
from collections.abc import Callable, Generator
from typing import TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": settings.sqlite_busy_timeout_ms / 1_000} if is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
logger = logging.getLogger("fish_feeder")
ResultT = TypeVar("ResultT")


class SqliteBusyError(RuntimeError):
    """Raised after bounded retries cannot acquire SQLite's write lock."""


if is_sqlite:

    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection: sqlite3.Connection, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def is_sqlite_busy_error(exc: BaseException) -> bool:
    if not is_sqlite or not isinstance(exc, OperationalError):
        return False
    original = exc.orig
    message = str(original).lower()
    return isinstance(original, sqlite3.OperationalError) and (
        "database is locked" in message or "database table is locked" in message
    )


def run_with_sqlite_lock_retry(
    session: Session,
    operation: Callable[[], ResultT],
    *,
    operation_name: str,
) -> ResultT:
    attempts = settings.sqlite_lock_retry_attempts if is_sqlite else 1
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except OperationalError as exc:
            session.rollback()
            if not is_sqlite_busy_error(exc):
                raise
            if attempt == attempts:
                raise SqliteBusyError(f"{operation_name} remained busy after {attempts} attempts") from exc
            delay_seconds = settings.sqlite_lock_retry_base_delay_ms * (2 ** (attempt - 1)) / 1_000
            logger.warning(
                "sqlite_lock_retry",
                extra={"operation": operation_name, "attempt": attempt, "delay_seconds": delay_seconds},
            )
            time.sleep(delay_seconds)
    raise AssertionError("unreachable")


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
