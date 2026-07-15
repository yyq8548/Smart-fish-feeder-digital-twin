from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def test_root_health_and_request_id(client: TestClient) -> None:
    root = client.get("/", headers={"X-Request-ID": "request-123"})
    assert root.status_code == 200
    assert root.json()["version"] == "5.0.0"
    assert root.json()["docs"] == "/docs"
    assert root.headers["X-Request-ID"] == "request-123"
    assert client.get("/health").json() == {"status": "healthy", "database": "connected"}


def test_operator_login_and_protected_identity(client: TestClient, operator_headers: dict[str, str]) -> None:
    assert client.post("/auth/token", data={"username": "test-admin", "password": "wrong"}).status_code == 401
    me = client.get("/users/me", headers=operator_headers)
    assert me.status_code == 200
    assert me.json()["username"] == "test-admin"
    assert me.json()["role"] == "operator"
    assert client.get("/users/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_public_demo_is_synthetic_and_isolated(client: TestClient, demo_headers: dict[str, str]) -> None:
    from app.database import SessionLocal
    from app.models import DeviceCommand
    from sqlalchemy import func, select

    me = client.get("/users/me", headers=demo_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "demo"

    devices = client.get("/devices", headers=demo_headers).json()
    assert [device["device_uid"] for device in devices] == ["demo-feeder-001"]
    assert devices[0]["id"] == -1

    status = client.get("/device-status?device_uid=demo-feeder-001", headers=demo_headers).json()
    assert status["online"] is True
    assert status["pump_state"] == "IDLE"
    telemetry = client.get("/telemetry?device_uid=demo-feeder-001", headers=demo_headers).json()
    assert len(telemetry) >= 10
    assert max(item["temperature_c"] for item in telemetry) == 5.6
    alerts = client.get("/alerts?device_uid=demo-feeder-001", headers=demo_headers).json()
    assert alerts[0]["device_id"] == -1
    assert "Sample alert" in alerts[0]["message"]
    assert len(client.get("/devices/demo-feeder-001/commands", headers=demo_headers).json()) >= 3

    simulated = client.post(
        "/devices/demo-feeder-001/commands",
        json={
            "idempotency_key": "public-demo-feed",
            "command_type": "FEED_NOW",
            "payload": {"duration_ms": 1000},
        },
        headers=demo_headers,
    )
    assert simulated.status_code == 201
    assert simulated.json()["status"] == "COMPLETED"
    assert simulated.json()["device_id"] == -1
    assert "demo_feeding" in simulated.json()["result"]

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(DeviceCommand)) == 0

    for path in (
        "/device-status?device_uid=feeder-001",
        "/telemetry?device_uid=feeder-001",
        "/alerts?device_uid=feeder-001",
        "/devices/feeder-001/commands",
    ):
        assert client.get(path, headers=demo_headers).status_code == 404


def test_public_demo_cannot_modify_production_resources(client: TestClient, demo_headers: dict[str, str]) -> None:
    denied_requests = (
        client.post(
            "/devices",
            json={"device_uid": "attacker-device", "name": "Blocked"},
            headers=demo_headers,
        ),
        client.post("/devices/feeder-001/rotate-key", headers=demo_headers),
        client.post(
            "/devices/feeder-001/schedules",
            json={"name": "Blocked", "hour": 9, "minute": 0},
            headers=demo_headers,
        ),
        client.patch("/schedules/1", json={"enabled": False}, headers=demo_headers),
        client.delete("/schedules/1", headers=demo_headers),
        client.post("/alerts/1/acknowledge", headers=demo_headers),
        client.post("/reliability/scan", headers=demo_headers),
    )
    assert {response.status_code for response in denied_requests} == {403}
    blocked_command = client.post(
        "/devices/feeder-001/commands",
        json={"idempotency_key": "blocked-real-feed", "command_type": "FEED_NOW", "payload": {}},
        headers=demo_headers,
    )
    assert blocked_command.status_code == 404


def test_device_provisioning_returns_key_once(client: TestClient, operator_headers: dict[str, str]) -> None:
    response = client.post(
        "/devices",
        json={"device_uid": "feeder-002", "name": "Second feeder"},
        headers=operator_headers,
    )
    assert response.status_code == 201
    assert len(response.json()["api_key"]) >= 32
    devices = client.get("/devices", headers=operator_headers).json()
    assert {item["device_uid"] for item in devices} == {"feeder-001", "feeder-002"}
    assert "api_key" not in devices[0]
    rotated = client.post("/devices/feeder-002/rotate-key", headers=operator_headers)
    assert rotated.status_code == 200
    assert rotated.json()["api_key"] != response.json()["api_key"]
    assert (
        client.post(
            "/devices",
            json={"device_uid": "feeder-002", "name": "Duplicate"},
            headers=operator_headers,
        ).status_code
        == 409
    )


def test_empty_monitoring_endpoints(client: TestClient, operator_headers: dict[str, str]) -> None:
    assert client.get("/telemetry").status_code == 401
    assert client.get("/alerts").status_code == 401
    assert client.get("/device-status").status_code == 401
    assert client.get("/telemetry", headers=operator_headers).json() == []
    assert client.get("/alerts", headers=operator_headers).json() == []
    status = client.get("/device-status", headers=operator_headers).json()
    assert status["online"] is False
    assert status["temperature_c"] is None


def test_ingest_requires_matching_device_credentials(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    assert client.post("/telemetry", json=telemetry_payload).status_code == 422
    wrong = {"X-Device-ID": "feeder-001", "X-Device-Key": "wrong"}
    assert client.post("/telemetry", json=telemetry_payload, headers=wrong).status_code == 401
    mismatch = {"X-Device-ID": "feeder-002", "X-Device-Key": "test-device-key"}
    assert client.post("/telemetry", json=telemetry_payload, headers=mismatch).status_code == 400


def test_ingest_idempotency_and_sequence_ordering(
    client: TestClient,
    telemetry_payload: dict[str, object],
    device_headers: dict[str, str],
    operator_headers: dict[str, str],
) -> None:
    first = client.post("/telemetry", json=telemetry_payload, headers=device_headers)
    assert first.status_code == 200
    duplicate = client.post("/telemetry", json=telemetry_payload, headers=device_headers)
    assert duplicate.json()["id"] == first.json()["id"]
    telemetry_payload["temperature_c"] = 4.25
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 409
    telemetry_payload["temperature_c"] = 4.0

    telemetry_payload["idempotency_key"] = "reading-old"
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 409

    telemetry_payload["idempotency_key"] = "reading-2"
    telemetry_payload["sequence_number"] = 2
    second = client.post("/telemetry", json=telemetry_payload, headers=device_headers)
    assert second.status_code == 200
    assert len(client.get("/telemetry?device_uid=feeder-001", headers=operator_headers).json()) == 2
    status = client.get("/device-status", headers=operator_headers).json()
    assert status["online"] is True
    assert status["last_sequence_number"] == 2


def test_concurrent_telemetry_idempotency_race_is_never_a_server_error(
    client: TestClient,
    device_headers: dict[str, str],
) -> None:
    from app.database import SessionLocal, get_db
    from app.main import app, telemetry_payload_hash
    from app.models import Device, TelemetryRecord
    from app.schemas import TelemetryIn
    from sqlalchemy import select

    def post_with_concurrent_winner(sequence_number: int, winner_temperature: float) -> int:
        request_payload: dict[str, object] = {
            "device_uid": "feeder-001",
            "idempotency_key": f"concurrent-{sequence_number}",
            "sequence_number": sequence_number,
            "recorded_at": datetime.now(UTC).isoformat(),
            "temperature_c": 4.0,
            "cooling_on": False,
            "pump_state": "IDLE",
            "sensor_status": "OK",
            "event_type": "heartbeat",
        }
        winner_payload = TelemetryIn.model_validate({**request_payload, "temperature_c": winner_temperature})
        with SessionLocal() as endpoint_db:
            original_flush = endpoint_db.flush
            injected = False

            def flush_after_concurrent_insert() -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    with SessionLocal() as concurrent_db:
                        concurrent_device = concurrent_db.scalar(
                            select(Device).where(Device.device_uid == "feeder-001")
                        )
                        assert concurrent_device is not None
                        concurrent_db.add(
                            TelemetryRecord(
                                device_id=concurrent_device.id,
                                idempotency_key=winner_payload.idempotency_key,
                                payload_hash=telemetry_payload_hash(winner_payload),
                                sequence_number=winner_payload.sequence_number,
                                recorded_at=winner_payload.recorded_at.astimezone(UTC),
                                temperature_c=winner_payload.temperature_c,
                                cooling_on=winner_payload.cooling_on,
                                pump_state=winner_payload.pump_state,
                                sensor_status=winner_payload.sensor_status,
                                event_type=winner_payload.event_type,
                                alert_level="normal",
                            )
                        )
                        concurrent_device.last_sequence_number = winner_payload.sequence_number
                        concurrent_device.last_seen_at = datetime.now(UTC)
                        concurrent_db.commit()
                original_flush()

            endpoint_db.flush = flush_after_concurrent_insert  # type: ignore[method-assign,assignment]

            def override_db():  # type: ignore[no-untyped-def]
                yield endpoint_db

            app.dependency_overrides[get_db] = override_db
            try:
                return client.post("/telemetry", json=request_payload, headers=device_headers).status_code
            finally:
                app.dependency_overrides.pop(get_db, None)

    assert post_with_concurrent_winner(1, 4.0) == 200
    assert post_with_concurrent_winner(2, 5.0) == 409


def test_timestamp_and_sensor_validation(
    client: TestClient, telemetry_payload: dict[str, object], device_headers: dict[str, str]
) -> None:
    telemetry_payload["recorded_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 422
    telemetry_payload["recorded_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 422
    telemetry_payload["recorded_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 422
    telemetry_payload["recorded_at"] = datetime.now(UTC).isoformat()
    telemetry_payload["temperature_c"] = None
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 422
    telemetry_payload["temperature_c"] = 4.0
    telemetry_payload["unexpected"] = "rejected"
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 422


def test_sensor_failure_creates_acknowledgeable_alert(
    client: TestClient,
    telemetry_payload: dict[str, object],
    device_headers: dict[str, str],
    operator_headers: dict[str, str],
) -> None:
    telemetry_payload.update({"temperature_c": None, "sensor_status": "DISCONNECTED"})
    response = client.post("/telemetry", json=telemetry_payload, headers=device_headers)
    assert response.status_code == 200
    assert response.json()["alert_level"] == "critical"
    alerts = client.get("/alerts?unacknowledged_only=true", headers=operator_headers).json()
    assert alerts[0]["category"] == "SENSOR_FAILURE"
    telemetry_payload.update(
        {"idempotency_key": "reading-2", "sequence_number": 2, "recorded_at": datetime.now(UTC).isoformat()}
    )
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    assert len(client.get("/alerts", headers=operator_headers).json()) == 1
    acknowledged = client.post(f"/alerts/{alerts[0]['id']}/acknowledge", headers=operator_headers)
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None
    telemetry_payload.update(
        {
            "idempotency_key": "reading-recovery",
            "sequence_number": 3,
            "recorded_at": datetime.now(UTC).isoformat(),
            "temperature_c": 4.0,
            "sensor_status": "OK",
        }
    )
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    assert client.get("/alerts", headers=operator_headers).json()[0]["resolved_at"] is not None
    telemetry_payload.update(
        {
            "idempotency_key": "reading-new-failure",
            "sequence_number": 4,
            "recorded_at": datetime.now(UTC).isoformat(),
            "temperature_c": None,
            "sensor_status": "DISCONNECTED",
        }
    )
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    assert len(client.get("/alerts", headers=operator_headers).json()) == 2


def test_open_temperature_alert_escalates_without_duplicate(
    client: TestClient,
    telemetry_payload: dict[str, object],
    device_headers: dict[str, str],
    operator_headers: dict[str, str],
) -> None:
    telemetry_payload["temperature_c"] = 5.5
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    first_alert = client.get("/alerts", headers=operator_headers).json()[0]
    assert first_alert["level"] == "warning"

    telemetry_payload.update(
        {
            "idempotency_key": "temperature-critical",
            "sequence_number": 2,
            "recorded_at": datetime.now(UTC).isoformat(),
            "temperature_c": 6.0,
        }
    )
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    alerts = client.get("/alerts", headers=operator_headers).json()
    assert len(alerts) == 1
    assert alerts[0]["id"] == first_alert["id"]
    assert alerts[0]["level"] == "critical"
    assert alerts[0]["message"] == "Reservoir temperature is dangerously high."


def test_schedule_crud_and_feeding_execution(
    client: TestClient,
    telemetry_payload: dict[str, object],
    device_headers: dict[str, str],
    operator_headers: dict[str, str],
) -> None:
    now = datetime.now(UTC)
    created = client.post(
        "/devices/feeder-001/schedules",
        json={
            "name": "Current feeding",
            "hour": now.hour,
            "minute": now.minute,
            "days_of_week": [now.weekday()],
            "timezone": "UTC",
        },
        headers=operator_headers,
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    patched = client.patch(f"/schedules/{schedule_id}", json={"grace_minutes": 20}, headers=operator_headers)
    assert patched.json()["grace_minutes"] == 20
    assert len(client.get("/devices/feeder-001/schedules", headers=operator_headers).json()) == 1

    telemetry_payload.update({"event_type": "scheduled_feeding"})
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    executions = client.get("/feeding-executions", headers=operator_headers).json()
    assert executions[0]["status"] == "STARTED"
    assert executions[0]["schedule_id"] == schedule_id
    telemetry_payload.update(
        {
            "idempotency_key": "reading-complete",
            "sequence_number": 2,
            "recorded_at": datetime.now(UTC).isoformat(),
            "event_type": "feeding_cycle_completed",
        }
    )
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    executions = client.get("/feeding-executions", headers=operator_headers).json()
    assert executions[0]["status"] == "SUCCESS"

    assert (
        client.patch(f"/schedules/{schedule_id}", json={"timezone": None}, headers=operator_headers).status_code == 422
    )

    assert client.delete(f"/schedules/{schedule_id}", headers=operator_headers).status_code == 409
    disposable = client.post(
        "/devices/feeder-001/schedules",
        json={"name": "Disposable", "hour": 12, "minute": 0, "timezone": "UTC"},
        headers=operator_headers,
    ).json()
    assert client.delete(f"/schedules/{disposable['id']}", headers=operator_headers).status_code == 204


def test_command_lifecycle(
    client: TestClient,
    operator_headers: dict[str, str],
    device_headers: dict[str, str],
    telemetry_payload: dict[str, object],
) -> None:
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    created = client.post(
        "/devices/feeder-001/commands",
        json={
            "idempotency_key": "feed-now-1",
            "command_type": "FEED_NOW",
            "payload": {"duration_ms": 1000},
        },
        headers=operator_headers,
    )
    assert created.status_code == 201
    assert created.json()["expires_at"] is not None
    duplicate = client.post(
        "/devices/feeder-001/commands",
        json={
            "idempotency_key": "feed-now-1",
            "command_type": "FEED_NOW",
            "payload": {"duration_ms": 1000},
        },
        headers=operator_headers,
    )
    assert duplicate.json()["id"] == created.json()["id"]
    collision = client.post(
        "/devices/feeder-001/commands",
        json={"idempotency_key": "feed-now-1", "command_type": "FEED_NOW", "payload": {}},
        headers=operator_headers,
    )
    assert collision.status_code == 409
    claimed = client.post("/device-commands/claim", headers=device_headers).json()
    assert claimed[0]["status"] == "CLAIMED"
    assert len(client.get("/devices/feeder-001/commands", headers=operator_headers).json()) == 1
    completed = client.post(
        f"/device-commands/{claimed[0]['id']}/complete",
        json={"status": "COMPLETED", "result": "dispensed"},
        headers=device_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert client.get("/feeding-executions", headers=operator_headers).json() == []
    assert (
        client.post(
            f"/device-commands/{claimed[0]['id']}/complete", json={"status": "FAILED"}, headers=device_headers
        ).status_code
        == 409
    )


def test_scheduled_command_completion_recovers_lost_telemetry(
    client: TestClient,
    operator_headers: dict[str, str],
    device_headers: dict[str, str],
    telemetry_payload: dict[str, object],
) -> None:
    assert client.post("/telemetry", json=telemetry_payload, headers=device_headers).status_code == 200
    now = datetime.now(UTC)
    schedule = client.post(
        "/devices/feeder-001/schedules",
        json={
            "name": "Command-confirmed feeding",
            "hour": now.hour,
            "minute": now.minute,
            "days_of_week": [now.weekday()],
            "timezone": "UTC",
            "grace_minutes": 10,
        },
        headers=operator_headers,
    ).json()
    command = client.post(
        "/devices/feeder-001/commands",
        json={
            "idempotency_key": f"scheduled-feed:{schedule['id']}:{now.date().isoformat()}",
            "command_type": "FEED_NOW",
            "payload": {"schedule_id": schedule["id"]},
        },
        headers=operator_headers,
    )
    assert command.status_code == 201
    claimed = client.post("/device-commands/claim", headers=device_headers).json()
    assert len(claimed) == 1
    completed = client.post(
        f"/device-commands/{claimed[0]['id']}/complete",
        json={"status": "COMPLETED", "result": "feeding_and_cleaning_completed"},
        headers=device_headers,
    )
    assert completed.status_code == 200
    executions = client.get("/feeding-executions", headers=operator_headers).json()
    assert len(executions) == 1
    assert executions[0]["schedule_id"] == schedule["id"]
    assert executions[0]["status"] == "SUCCESS"


def test_command_payload_validation_and_schedule_sync(
    client: TestClient,
    operator_headers: dict[str, str],
) -> None:
    invalid_commands = [
        {"idempotency_key": "bad-feed", "command_type": "FEED_NOW", "payload": {"duration_ms": 499}},
        {
            "idempotency_key": "bad-clean",
            "command_type": "CLEAN_PUMP",
            "payload": {"duration_ms": 60_001},
        },
        {
            "idempotency_key": "ambiguous-cooling",
            "command_type": "SET_COOLING",
            "payload": {"mode": "AUTO", "enabled": True},
        },
        {"idempotency_key": "missing-cooling", "command_type": "SET_COOLING", "payload": {}},
        {
            "idempotency_key": "duplicate-schedules",
            "command_type": "SYNC_SCHEDULES",
            "payload": {
                "schedules": [
                    {"id": 1, "hour": 8, "minute": 0, "days_of_week": [0]},
                    {"id": 1, "hour": 18, "minute": 0, "days_of_week": [0]},
                ]
            },
        },
        {
            "idempotency_key": "oversized-extra",
            "command_type": "FEED_NOW",
            "payload": {"untrusted": "x" * 4_000},
        },
    ]
    for command in invalid_commands:
        response = client.post("/devices/feeder-001/commands", json=command, headers=operator_headers)
        assert response.status_code == 422, response.text

    synchronized = client.post(
        "/devices/feeder-001/commands",
        json={
            "idempotency_key": "sync-schedules-1",
            "command_type": "SYNC_SCHEDULES",
            "payload": {
                "schedules": [
                    {
                        "id": 7,
                        "hour": 8,
                        "minute": 30,
                        "days_of_week": [4, 0, 4],
                        "timezone": "UTC",
                        "enabled": True,
                    }
                ]
            },
        },
        headers=operator_headers,
    )
    assert synchronized.status_code == 201
    assert synchronized.json()["command_type"] == "SYNC_SCHEDULES"
    assert '"days_of_week":[0,4]' in synchronized.json()["payload_json"]


def test_concurrent_command_idempotency_conflicts_are_recovered(
    client: TestClient,
    operator_headers: dict[str, str],
) -> None:
    from app.database import SessionLocal, get_db
    from app.main import app
    from app.models import Device, DeviceCommand, User
    from sqlalchemy import select

    def post_with_concurrent_insert(idempotency_key: str, concurrent_payload: str) -> int:
        with SessionLocal() as endpoint_db:
            device = endpoint_db.scalar(select(Device).where(Device.device_uid == "feeder-001"))
            user = endpoint_db.scalar(select(User).where(User.username == "test-admin"))
            assert device is not None and user is not None
            device.last_seen_at = datetime.now(UTC)
            endpoint_db.commit()
            original_commit = endpoint_db.commit
            injected = False

            def commit_after_concurrent_insert() -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    with SessionLocal() as concurrent_db:
                        concurrent_db.add(
                            DeviceCommand(
                                device_id=device.id,
                                idempotency_key=idempotency_key,
                                command_type="FEED_NOW",
                                payload_json=concurrent_payload,
                                requested_by_user_id=user.id,
                            )
                        )
                        concurrent_db.commit()
                original_commit()

            endpoint_db.commit = commit_after_concurrent_insert  # type: ignore[method-assign]

            def override_db():  # type: ignore[no-untyped-def]
                yield endpoint_db

            app.dependency_overrides[get_db] = override_db
            try:
                response = client.post(
                    "/devices/feeder-001/commands",
                    json={
                        "idempotency_key": idempotency_key,
                        "command_type": "FEED_NOW",
                        "payload": {"duration_ms": 1000},
                    },
                    headers=operator_headers,
                )
                return response.status_code
            finally:
                app.dependency_overrides.pop(get_db, None)

    assert post_with_concurrent_insert("race-identical", '{"duration_ms":1000}') == 201
    assert post_with_concurrent_insert("race-conflicting", "{}") == 409


def test_offline_device_refuses_manual_actuation(
    client: TestClient,
    operator_headers: dict[str, str],
) -> None:
    response = client.post(
        "/devices/feeder-001/commands",
        json={"idempotency_key": "offline-feed", "command_type": "FEED_NOW", "payload": {}},
        headers=operator_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Device is offline; refusing an actuation command"


def test_pagination_validation(client: TestClient, operator_headers: dict[str, str]) -> None:
    assert client.get("/telemetry?limit=0", headers=operator_headers).status_code == 422
    assert client.get("/alerts?limit=101", headers=operator_headers).status_code == 422
