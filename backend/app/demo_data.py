import json
from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Lock

from .schemas import AlertOut, CommandCreate, CommandOut, DeviceOut, DeviceStatus, TelemetryOut

DEMO_DEVICE_ID = -1

_command_lock = Lock()
_demo_commands: deque[CommandOut] = deque(maxlen=20)
_next_command_id = -1000


def demo_device(device_uid: str, now: datetime | None = None) -> DeviceOut:
    current = now or datetime.now(UTC)
    return DeviceOut(
        id=DEMO_DEVICE_ID,
        device_uid=device_uid,
        name="Public Demo Feeder",
        owner_user_id=None,
        active=True,
        credential_version=1,
        claim_expires_at=None,
        claim_consumed_at=None,
        transfer_expires_at=None,
        last_sequence_number=12,
        last_seen_at=current,
        created_at=current - timedelta(days=30),
    )


def demo_status(device_uid: str, now: datetime | None = None) -> DeviceStatus:
    current = now or datetime.now(UTC)
    return DeviceStatus(
        device_uid=device_uid,
        online=True,
        temperature_c=4.6,
        cooling_on=False,
        pump_state="IDLE",
        sensor_status="OK",
        alert_level="normal",
        alert_message="Public demo online — all controls are simulated.",
        last_event_type="heartbeat",
        last_sequence_number=12,
        last_seen=current,
    )


def demo_telemetry(now: datetime | None = None) -> list[TelemetryOut]:
    current = now or datetime.now(UTC)
    temperatures = (4.2, 4.3, 4.5, 4.7, 4.9, 5.2, 5.6, 5.3, 4.9, 4.7, 4.6, 4.6)
    records: list[TelemetryOut] = []
    for index, temperature in enumerate(temperatures, start=1):
        recorded_at = current - timedelta(minutes=len(temperatures) - index)
        records.append(
            TelemetryOut(
                id=-index,
                sequence_number=index,
                recorded_at=recorded_at,
                temperature_c=temperature,
                cooling_on=temperature >= 5.0,
                pump_state="FEEDING" if index == 4 else "IDLE",
                sensor_status="OK",
                event_type="scheduled_feeding" if index == 4 else "heartbeat",
                alert_level="warning" if temperature >= 5.5 else "normal",
                alert_message="Demo temperature crossed 5.5 °C." if temperature >= 5.5 else None,
                created_at=recorded_at,
            )
        )
    return records


def demo_alerts(now: datetime | None = None) -> list[AlertOut]:
    current = now or datetime.now(UTC)
    return [
        AlertOut(
            id=-1,
            device_id=DEMO_DEVICE_ID,
            category="TEMPERATURE",
            level="warning",
            message="Sample alert: reservoir temperature briefly reached 5.6 °C.",
            acknowledged_at=None,
            resolved_at=current - timedelta(minutes=3),
            created_at=current - timedelta(minutes=5),
        )
    ]


def _sample_commands(now: datetime) -> list[CommandOut]:
    samples = (
        (-10, "SET_COOLING", '{"mode":"AUTO"}', "demo_automatic_cooling_enabled", 3),
        (-11, "CLEAN_PUMP", '{"duration_ms":1000}', "demo_reverse_clean_completed", 7),
        (-12, "FEED_NOW", '{"duration_ms":1000}', "demo_feeding_and_cleaning_completed", 12),
    )
    commands: list[CommandOut] = []
    for command_id, command_type, payload_json, result, minutes_ago in samples:
        created_at = now - timedelta(minutes=minutes_ago)
        commands.append(
            CommandOut(
                id=command_id,
                device_id=DEMO_DEVICE_ID,
                idempotency_key=f"demo-sample-{abs(command_id)}",
                command_type=command_type,
                payload_json=payload_json,
                status="COMPLETED",
                claimed_at=created_at + timedelta(milliseconds=100),
                lease_expires_at=None,
                expires_at=created_at + timedelta(seconds=45),
                completed_at=created_at + timedelta(seconds=2),
                result=result,
                created_at=created_at,
            )
        )
    return commands


def create_demo_command(payload: CommandCreate, ttl_seconds: int) -> CommandOut:
    global _next_command_id

    now = datetime.now(UTC)
    results = {
        "FEED_NOW": "demo_feeding_and_cleaning_completed",
        "CLEAN_PUMP": "demo_reverse_clean_completed",
        "SET_COOLING": "demo_cooling_mode_updated",
        "SYNC_SCHEDULES": "demo_schedules_synchronized",
    }
    with _command_lock:
        command_id = _next_command_id
        _next_command_id -= 1
        command = CommandOut(
            id=command_id,
            device_id=DEMO_DEVICE_ID,
            idempotency_key=payload.idempotency_key,
            command_type=payload.command_type,
            payload_json=json.dumps(payload.payload, separators=(",", ":"), sort_keys=True),
            status="COMPLETED",
            claimed_at=now,
            lease_expires_at=None,
            expires_at=now + timedelta(seconds=ttl_seconds),
            completed_at=now + timedelta(milliseconds=250),
            result=results.get(payload.command_type, "demo_command_completed"),
            created_at=now,
        )
        _demo_commands.appendleft(command)
    return command


def list_demo_commands(limit: int, now: datetime | None = None) -> list[CommandOut]:
    current = now or datetime.now(UTC)
    with _command_lock:
        dynamic = list(_demo_commands)
    return (dynamic + _sample_commands(current))[:limit]


def reset_demo_state() -> None:
    global _next_command_id

    with _command_lock:
        _demo_commands.clear()
        _next_command_id = -1000
