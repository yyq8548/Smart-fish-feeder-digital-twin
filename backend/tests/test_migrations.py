from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _config_for(database: Path) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    return config


def test_alembic_upgrade_creates_platform_schema(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    command.upgrade(_config_for(database), "head")
    inspector = inspect(create_engine(f"sqlite:///{database.as_posix()}"))
    tables = set(inspector.get_table_names())
    assert {
        "users",
        "devices",
        "telemetry",
        "feeding_schedules",
        "feeding_executions",
        "alerts",
        "device_commands",
    } <= tables
    assert "expires_at" in {column["name"] for column in inspector.get_columns("device_commands")}


def test_alembic_upgrades_unversioned_v3_database(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE devices ("
                "id INTEGER PRIMARY KEY, device_uid VARCHAR(80), "
                "name VARCHAR(120), created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE telemetry ("
                "id INTEGER PRIMARY KEY, device_id INTEGER, idempotency_key VARCHAR(100), "
                "temperature_c FLOAT NOT NULL, cooling_on BOOLEAN, pump_state VARCHAR(20), "
                "event_type VARCHAR(80), alert_level VARCHAR(20), "
                "alert_message VARCHAR(200), created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE feeding_schedules ("
                "id INTEGER PRIMARY KEY, device_id INTEGER, hour INTEGER, "
                "minute INTEGER, enabled BOOLEAN)"
            )
        )
        connection.execute(text("INSERT INTO devices VALUES (1, 'feeder-001', 'Legacy feeder', CURRENT_TIMESTAMP)"))
        connection.execute(
            text(
                "INSERT INTO telemetry VALUES "
                "(1, 1, 'legacy-1', 4.0, 0, 'IDLE', NULL, 'normal', NULL, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(_config_for(database), "head")
    inspector = inspect(engine)
    assert {"api_key_hash", "last_sequence_number", "last_seen_at"} <= {
        column["name"] for column in inspector.get_columns("devices")
    }
    telemetry_columns = {column["name"]: column for column in inspector.get_columns("telemetry")}
    assert {"payload_hash", "sequence_number", "recorded_at", "sensor_status"} <= telemetry_columns.keys()
    assert telemetry_columns["temperature_c"]["nullable"] is True
    assert "expires_at" in {column["name"] for column in inspector.get_columns("device_commands")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT sequence_number FROM telemetry WHERE id = 1")).scalar_one() == 1
        state = connection.execute(text("SELECT last_sequence_number, last_seen_at FROM devices WHERE id = 1")).one()
        assert state.last_sequence_number == 1
        assert state.last_seen_at is not None


def test_expiry_migration_invalidates_predeadline_nonterminal_commands(tmp_path: Path) -> None:
    database = tmp_path / "legacy-commands.db"
    config = _config_for(database)
    command.upgrade(config, "0001_platform_schema")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ix_device_commands_expires_at"))
        connection.execute(text("ALTER TABLE device_commands DROP COLUMN expires_at"))
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, active, created_at) "
                "VALUES (1, 'legacy-admin', 'hash', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO devices (id, device_uid, name, api_key_hash, active, created_at) "
                "VALUES (1, 'feeder-001', 'Legacy feeder', 'hash', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO device_commands "
                "(id, device_id, idempotency_key, command_type, payload_json, status, "
                "requested_by_user_id, created_at) "
                "VALUES (1, 1, 'old-pending', 'FEED_NOW', '{}', 'PENDING', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO device_commands "
                "(id, device_id, idempotency_key, command_type, payload_json, status, claimed_at, "
                "lease_expires_at, requested_by_user_id, created_at) "
                "VALUES (2, 1, 'old-claimed', 'CLEAN_PUMP', '{}', 'CLAIMED', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)"
            )
        )

    command.upgrade(config, "head")
    assert "expires_at" in {column["name"] for column in inspect(engine).get_columns("device_commands")}
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT status, result, completed_at FROM device_commands ORDER BY id")).all()
    assert [row.status for row in rows] == ["EXPIRED", "EXPIRED"]
    assert [row.result for row in rows] == [
        "expired_during_expiry_migration",
        "expired_during_expiry_migration",
    ]
    assert all(row.completed_at is not None for row in rows)
