import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from .models import Alert, Device, DeviceCommand, FeedingExecution, FeedingSchedule, User

AlertLevel = Literal["normal", "warning", "critical"]


def create_alert(
    temperature_c: float | None, pump_state: str, sensor_status: str = "OK"
) -> tuple[AlertLevel, str | None, str | None]:
    if sensor_status != "OK":
        return "critical", "Temperature sensor is unavailable.", "SENSOR_FAILURE"
    if pump_state.upper() == "ERROR":
        return "critical", "Pump reported an error state.", "PUMP_FAILURE"
    if temperature_c is not None and temperature_c >= 6.0:
        return "critical", "Reservoir temperature is dangerously high.", "TEMPERATURE"
    if temperature_c is not None and temperature_c > 5.0:
        return "warning", "Reservoir temperature is above target range.", "TEMPERATURE"
    if temperature_c is not None and temperature_c < 2.5:
        return "warning", "Reservoir temperature is below target range.", "TEMPERATURE"
    return "normal", None, None


def ensure_alert(
    db: Session,
    *,
    device_id: int,
    category: str,
    level: str,
    message: str,
    fingerprint: str,
    telemetry_id: int | None = None,
    schedule_id: int | None = None,
) -> bool:
    if db.scalar(select(Alert.id).where(Alert.fingerprint == fingerprint)) is not None:
        return False
    db.add(
        Alert(
            device_id=device_id,
            telemetry_id=telemetry_id,
            schedule_id=schedule_id,
            category=category,
            level=level,
            message=message,
            fingerprint=fingerprint,
        )
    )
    return True


def resolve_alert_categories(db: Session, device_id: int, categories: set[str], now: datetime) -> None:
    if not categories:
        return
    db.execute(
        update(Alert)
        .where(
            Alert.device_id == device_id,
            Alert.category.in_(categories),
            Alert.resolved_at.is_(None),
        )
        .values(resolved_at=now)
    )


def ensure_incident_alert(
    db: Session,
    *,
    device_id: int,
    telemetry_id: int,
    category: str,
    level: str,
    message: str,
) -> bool:
    open_alert = db.scalar(
        select(Alert).where(
            Alert.device_id == device_id,
            Alert.category == category,
            Alert.resolved_at.is_(None),
        )
    )
    if open_alert is not None:
        severity = {"warning": 1, "critical": 2}
        if severity.get(level, 0) > severity.get(open_alert.level, 0):
            open_alert.level = level
            open_alert.message = message
        return False
    return ensure_alert(
        db,
        device_id=device_id,
        telemetry_id=telemetry_id,
        category=category,
        level=level,
        message=message,
        fingerprint=f"incident:{device_id}:{category}:{telemetry_id}",
    )


def _local_day_bounds(day: date, timezone_name: str) -> tuple[datetime, datetime, ZoneInfo]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    start = datetime.combine(day, time.min, tzinfo=zone)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC), zone


def match_schedule_for_event(db: Session, device_id: int, recorded_at: datetime) -> FeedingSchedule | None:
    for schedule in db.scalars(
        select(FeedingSchedule).where(FeedingSchedule.device_id == device_id, FeedingSchedule.enabled.is_(True))
    ):
        try:
            zone = ZoneInfo(schedule.timezone)
        except ZoneInfoNotFoundError:
            continue
        local_event = recorded_at.astimezone(zone)
        if local_event.weekday() not in {int(day) for day in schedule.days_of_week.split(",") if day}:
            continue
        expected = datetime.combine(local_event.date(), time(schedule.hour, schedule.minute), tzinfo=zone)
        if abs((local_event - expected).total_seconds()) <= schedule.grace_minutes * 60:
            return schedule
    return None


def reconcile_scheduled_feed_completion(db: Session, command: DeviceCommand, completed_at: datetime) -> bool:
    if command.command_type != "FEED_NOW" or command.claimed_at is None:
        return False
    try:
        command_payload = json.loads(command.payload_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(command_payload, dict):
        return False
    schedule_id = command_payload.get("schedule_id")
    if not isinstance(schedule_id, int) or isinstance(schedule_id, bool):
        return False

    key_parts = command.idempotency_key.split(":")
    if len(key_parts) != 3 or key_parts[0] != "scheduled-feed":
        return False
    try:
        key_schedule_id = int(key_parts[1])
        scheduled_day = date.fromisoformat(key_parts[2])
    except ValueError:
        return False
    if key_schedule_id != schedule_id:
        return False

    schedule = db.scalar(
        select(FeedingSchedule).where(
            FeedingSchedule.id == schedule_id,
            FeedingSchedule.device_id == command.device_id,
        )
    )
    if schedule is None:
        return False
    try:
        day_start, day_end, zone = _local_day_bounds(scheduled_day, schedule.timezone)
    except ValueError:
        return False
    scheduled_days = {int(day) for day in schedule.days_of_week.split(",") if day}
    if scheduled_day.weekday() not in scheduled_days:
        return False

    claimed_at = command.claimed_at
    if claimed_at.tzinfo is None:
        claimed_at = claimed_at.replace(tzinfo=UTC)
    expected_local = datetime.combine(scheduled_day, time(schedule.hour, schedule.minute), tzinfo=zone)
    claimed_local = claimed_at.astimezone(zone)
    if claimed_local < expected_local or claimed_local > expected_local + timedelta(minutes=schedule.grace_minutes):
        return False

    successful = db.scalar(
        select(FeedingExecution.id).where(
            FeedingExecution.schedule_id == schedule.id,
            FeedingExecution.started_at >= day_start,
            FeedingExecution.started_at < day_end,
            FeedingExecution.status == "SUCCESS",
        )
    )
    if successful is not None:
        return False

    started = db.scalar(
        select(FeedingExecution)
        .where(
            FeedingExecution.device_id == command.device_id,
            FeedingExecution.schedule_id == schedule.id,
            FeedingExecution.started_at >= day_start,
            FeedingExecution.started_at < day_end,
            FeedingExecution.status == "STARTED",
        )
        .order_by(FeedingExecution.started_at.desc())
    )
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    else:
        completed_at = completed_at.astimezone(UTC)
    if started is not None:
        started.status = "SUCCESS"
        started.completed_at = completed_at
        started.details = "Confirmed by the completed scheduled-feed device command."
    else:
        db.add(
            FeedingExecution(
                device_id=command.device_id,
                schedule_id=schedule.id,
                execution_type="SCHEDULED",
                status="SUCCESS",
                started_at=expected_local.astimezone(UTC),
                completed_at=completed_at,
                details="Recovered from the completed scheduled-feed device command after telemetry loss.",
            )
        )
    return True


def scan_reliability(db: Session, now: datetime, offline_after_seconds: int) -> tuple[int, int, int]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    missed_created = 0
    offline_created = 0
    commands_created = 0
    operator = db.scalar(select(User).where(User.active.is_(True)).order_by(User.id))

    for device in db.scalars(select(Device).where(Device.active.is_(True))):
        last_seen = device.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if last_seen is None or (now - last_seen).total_seconds() > offline_after_seconds:
            incident = last_seen.isoformat() if last_seen is not None else "never-seen"
            offline_created += int(
                ensure_alert(
                    db,
                    device_id=device.id,
                    category="DEVICE_OFFLINE",
                    level="warning",
                    message="Device heartbeat is stale.",
                    fingerprint=f"offline:{device.id}:{incident}",
                )
            )

    schedules = db.scalars(select(FeedingSchedule).where(FeedingSchedule.enabled.is_(True))).all()
    for schedule in schedules:
        try:
            zone = ZoneInfo(schedule.timezone)
        except ZoneInfoNotFoundError:
            continue
        local_now = now.astimezone(zone)
        if local_now.weekday() not in {int(day) for day in schedule.days_of_week.split(",") if day}:
            continue
        expected_local = datetime.combine(local_now.date(), time(schedule.hour, schedule.minute), tzinfo=zone)
        if local_now < expected_local:
            continue
        day_start, day_end, _ = _local_day_bounds(local_now.date(), schedule.timezone)
        execution = db.scalar(
            select(FeedingExecution.id).where(
                and_(
                    FeedingExecution.schedule_id == schedule.id,
                    FeedingExecution.started_at >= day_start,
                    FeedingExecution.started_at < day_end,
                    FeedingExecution.status == "SUCCESS",
                )
            )
        )
        if execution is not None:
            continue
        operation_key = f"scheduled-feed:{schedule.id}:{local_now.date().isoformat()}"
        if local_now <= expected_local + timedelta(minutes=schedule.grace_minutes):
            if (
                operator is not None
                and db.scalar(
                    select(DeviceCommand.id).where(
                        DeviceCommand.device_id == schedule.device_id,
                        DeviceCommand.idempotency_key == operation_key,
                    )
                )
                is None
            ):
                db.add(
                    DeviceCommand(
                        device_id=schedule.device_id,
                        idempotency_key=operation_key,
                        command_type="FEED_NOW",
                        payload_json=json.dumps({"schedule_id": schedule.id}, separators=(",", ":"), sort_keys=True),
                        requested_by_user_id=operator.id,
                        expires_at=(expected_local + timedelta(minutes=schedule.grace_minutes)).astimezone(UTC),
                    )
                )
                commands_created += 1
            continue

        fingerprint = f"missed:{schedule.id}:{local_now.date().isoformat()}"
        if db.scalar(select(Alert.id).where(Alert.fingerprint == fingerprint)) is None:
            expected_utc = expected_local.astimezone(UTC)
            db.add(
                FeedingExecution(
                    device_id=schedule.device_id,
                    schedule_id=schedule.id,
                    execution_type="SCHEDULED",
                    status="MISSED",
                    started_at=expected_utc,
                    completed_at=expected_utc,
                    details="No successful feeding event was received before the grace period ended.",
                )
            )
            ensure_alert(
                db,
                device_id=schedule.device_id,
                schedule_id=schedule.id,
                category="MISSED_FEEDING",
                level="critical",
                message=f"Scheduled feeding '{schedule.name}' was missed.",
                fingerprint=fingerprint,
            )
            missed_created += 1

    db.commit()
    return missed_created, offline_created, commands_created
