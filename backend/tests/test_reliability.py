from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.models import Device, DeviceCommand, FeedingExecution, FeedingSchedule, User
from app.rate_limit import FixedWindowRateLimiter
from app.services import reconcile_scheduled_feed_completion, scan_reliability
from sqlalchemy import select


def test_rate_limiter_expires_old_events() -> None:
    limiter = FixedWindowRateLimiter()
    assert limiter.allow("device", 2, now=0)
    assert limiter.allow("device", 2, now=1)
    assert not limiter.allow("device", 2, now=2)
    assert limiter.allow("device", 2, now=61)


def test_reliability_scan_endpoint_requires_operator_and_is_idempotent(  # type: ignore[no-untyped-def]
    client, operator_headers
) -> None:
    assert client.post("/reliability/scan").status_code == 401
    first = client.post("/reliability/scan", headers=operator_headers)
    assert first.status_code == 200
    assert first.json() == {
        "missed_feedings_created": 0,
        "offline_alerts_created": 1,
        "scheduled_commands_created": 0,
    }
    second = client.post("/reliability/scan", headers=operator_headers)
    assert second.status_code == 200
    assert second.json()["offline_alerts_created"] == 0


def test_reliability_scan_creates_missed_feeding_and_offline_alerts(client) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        assert device is not None
        device.last_seen_at = now - timedelta(minutes=5)
        scheduled = now - timedelta(hours=1)
        db.add(
            FeedingSchedule(
                device_id=device.id,
                name="Overdue feeding",
                hour=scheduled.hour,
                minute=scheduled.minute,
                days_of_week=str(scheduled.weekday()),
                timezone="UTC",
                grace_minutes=1,
            )
        )
        db.commit()
        missed, offline, commands = scan_reliability(db, now, offline_after_seconds=60)
        assert missed == 1
        assert offline == 1
        assert commands == 0
        assert scan_reliability(db, now, offline_after_seconds=60) == (0, 0, 0)


def test_due_schedule_dispatches_one_idempotent_feed_command(client) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        assert device is not None
        schedule = FeedingSchedule(
            device_id=device.id,
            name="Due now",
            hour=now.hour,
            minute=now.minute,
            days_of_week=str(now.weekday()),
            timezone="UTC",
            grace_minutes=10,
        )
        db.add(schedule)
        db.commit()
        result = scan_reliability(db, now, offline_after_seconds=60)
        assert result[2] == 1
        assert scan_reliability(db, now, offline_after_seconds=60)[2] == 0
        command = db.scalar(select(DeviceCommand).where(DeviceCommand.idempotency_key.like("scheduled-feed:%")))
        assert command is not None
        assert command.command_type == "FEED_NOW"
        assert command.expires_at is not None
        assert command.expires_at.replace(tzinfo=UTC) == now + timedelta(minutes=schedule.grace_minutes)
        assert f'"schedule_id":{schedule.id}' in command.payload_json


def test_expired_command_lease_can_be_reclaimed(client, device_headers) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        user = db.scalar(select(User).where(User.username == "test-admin"))
        assert device is not None and user is not None
        db.add(
            DeviceCommand(
                device_id=device.id,
                idempotency_key="lease-test",
                command_type="FEED_NOW",
                payload_json="{}",
                requested_by_user_id=user.id,
                status="CLAIMED",
                claimed_at=now - timedelta(minutes=2),
                lease_expires_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(minutes=5),
            )
        )
        db.commit()
    reclaimed = client.post("/device-commands/claim", headers=device_headers)
    assert reclaimed.status_code == 200
    assert reclaimed.json()[0]["idempotency_key"] == "lease-test"
    assert reclaimed.json()[0]["lease_expires_at"] is not None


def test_expired_pending_command_is_not_delivered(client, device_headers) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        user = db.scalar(select(User).where(User.username == "test-admin"))
        assert device is not None and user is not None
        command = DeviceCommand(
            device_id=device.id,
            idempotency_key="expired-before-delivery",
            command_type="FEED_NOW",
            payload_json="{}",
            requested_by_user_id=user.id,
            expires_at=now - timedelta(seconds=1),
        )
        db.add(command)
        db.commit()
        command_id = command.id

    claimed = client.post("/device-commands/claim", headers=device_headers)
    assert claimed.status_code == 200
    assert claimed.json() == []
    with SessionLocal() as db:
        expired = db.get(DeviceCommand, command_id)
        assert expired is not None
        assert expired.status == "EXPIRED"
        assert expired.result == "expired_before_delivery"


def test_command_without_delivery_deadline_fails_closed(client, device_headers) -> None:  # type: ignore[no-untyped-def]
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        user = db.scalar(select(User).where(User.username == "test-admin"))
        assert device is not None and user is not None
        command = DeviceCommand(
            device_id=device.id,
            idempotency_key="missing-delivery-deadline",
            command_type="FEED_NOW",
            payload_json="{}",
            requested_by_user_id=user.id,
        )
        db.add(command)
        db.commit()
        command_id = command.id

    claimed = client.post("/device-commands/claim", headers=device_headers)
    assert claimed.status_code == 200
    assert claimed.json() == []
    with SessionLocal() as db:
        expired = db.get(DeviceCommand, command_id)
        assert expired is not None
        assert expired.status == "EXPIRED"
        assert expired.result == "missing_delivery_deadline"


def test_claimed_command_gets_result_grace_before_timeout(client, device_headers) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        user = db.scalar(select(User).where(User.username == "test-admin"))
        assert device is not None and user is not None
        command = DeviceCommand(
            device_id=device.id,
            idempotency_key="long-running-command",
            command_type="FEED_NOW",
            payload_json='{"duration_ms":60000}',
            requested_by_user_id=user.id,
            status="CLAIMED",
            claimed_at=now - timedelta(seconds=30),
            lease_expires_at=now - timedelta(seconds=20),
            expires_at=now - timedelta(seconds=1),
        )
        db.add(command)
        db.commit()
        command_id = command.id

    assert client.post("/device-commands/claim", headers=device_headers).json() == []
    with SessionLocal() as db:
        awaiting_result = db.get(DeviceCommand, command_id)
        assert awaiting_result is not None
        assert awaiting_result.status == "CLAIMED"
        awaiting_result.expires_at = now - timedelta(seconds=91)
        db.commit()

    assert client.post("/device-commands/claim", headers=device_headers).json() == []
    with SessionLocal() as db:
        timed_out = db.get(DeviceCommand, command_id)
        assert timed_out is not None
        assert timed_out.status == "EXPIRED"
        assert timed_out.result == "terminal_result_timeout_after_claim"


def test_command_completion_reconciles_started_execution_and_prevents_false_missed_alert(client) -> None:  # type: ignore[no-untyped-def]
    scheduled_at = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
        user = db.scalar(select(User).where(User.username == "test-admin"))
        assert device is not None and user is not None
        schedule = FeedingSchedule(
            device_id=device.id,
            name="Command reconciliation",
            hour=scheduled_at.hour,
            minute=scheduled_at.minute,
            days_of_week=str(scheduled_at.weekday()),
            timezone="UTC",
            grace_minutes=10,
        )
        db.add(schedule)
        db.flush()
        execution = FeedingExecution(
            device_id=device.id,
            schedule_id=schedule.id,
            execution_type="SCHEDULED",
            status="STARTED",
            started_at=scheduled_at + timedelta(seconds=5),
        )
        command = DeviceCommand(
            device_id=device.id,
            idempotency_key=f"scheduled-feed:{schedule.id}:{scheduled_at.date().isoformat()}",
            command_type="FEED_NOW",
            payload_json=f'{{"schedule_id":{schedule.id}}}',
            requested_by_user_id=user.id,
            status="CLAIMED",
            claimed_at=scheduled_at + timedelta(seconds=2),
            lease_expires_at=scheduled_at + timedelta(minutes=1),
        )
        db.add_all([execution, command])
        db.commit()

        completed_at = scheduled_at + timedelta(seconds=30)
        assert reconcile_scheduled_feed_completion(db, command, completed_at)
        db.commit()
        executions = list(db.scalars(select(FeedingExecution).where(FeedingExecution.schedule_id == schedule.id)))
        assert len(executions) == 1
        assert executions[0].status == "SUCCESS"
        assert executions[0].completed_at is not None
        assert not reconcile_scheduled_feed_completion(db, command, completed_at)

        missed, _, _ = scan_reliability(db, scheduled_at + timedelta(minutes=20), offline_after_seconds=60)
        assert missed == 0
