import re
import smtplib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


def _token_from_email(body: str, parameter: str) -> str:
    link = re.search(r"https?://\S+", body)
    assert link is not None
    token = parse_qs(urlparse(link.group(0)).query)[parameter][0]
    assert len(token) > 20
    return token


def _register_verified_customer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    email: str,
    password: str = "SecureFeeder42",
) -> dict[str, str]:
    import app.main as main_module

    delivered: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        main_module,
        "deliver_account_email",
        lambda recipient, subject, body: delivered.append((recipient, subject, body)),
    )
    registered = client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 202
    assert delivered[-1][0] == email
    token = _token_from_email(delivered[-1][2], "verify_token")
    verified = client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    login = client.post("/auth/token", data={"username": email.upper(), "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_customer_registration_verification_and_password_reset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    delivered: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        main_module,
        "deliver_account_email",
        lambda recipient, subject, body: delivered.append((recipient, subject, body)),
    )
    email = "customer@example.com"
    password = "SecureFeeder42"
    registered = client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 202
    assert "verification" in registered.json()["message"]
    assert client.post("/auth/token", data={"username": email, "password": password}).status_code == 403

    resent = client.post("/auth/verification/resend", json={"email": email})
    assert resent.status_code == 202
    assert len(delivered) == 2
    verification_token = _token_from_email(delivered[-1][2], "verify_token")
    assert client.post("/auth/verify-email", json={"token": verification_token}).status_code == 200
    assert client.post("/auth/verify-email", json={"token": "not-a-real-account-token"}).status_code == 400

    login = client.post("/auth/token", data={"username": email, "password": password})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    identity = client.get("/users/me", headers=headers).json()
    assert identity == {
        "id": identity["id"],
        "username": email,
        "email": email,
        "email_verified": True,
        "role": "customer",
        "active": True,
    }
    assert client.get("/devices", headers=headers).json() == []

    requested = client.post("/auth/password-reset/request", json={"email": email})
    assert requested.status_code == 202
    reset_token = _token_from_email(delivered[-1][2], "reset_token")
    new_password = "EvenSaferFeeder84"
    changed = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "password": new_password},
    )
    assert changed.status_code == 200
    assert client.get("/users/me", headers=headers).status_code == 401
    assert client.post("/auth/token", data={"username": email, "password": password}).status_code == 401
    assert client.post("/auth/token", data={"username": email, "password": new_password}).status_code == 200
    reused = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "password": "AnotherSafeFeeder96"},
    )
    assert reused.status_code == 400

    # Unknown addresses receive the same response and never trigger mail delivery.
    delivered_count = len(delivered)
    unknown = client.post("/auth/password-reset/request", json={"email": "unknown@example.com"})
    assert unknown.status_code == 202
    assert len(delivered) == delivered_count


def test_customer_device_pairing_and_tenant_isolation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    first = client.post(
        "/devices",
        json={"device_uid": "customer-feeder-a", "name": "Alice's feeder"},
        headers=operator_headers,
    ).json()
    second = client.post(
        "/devices",
        json={"device_uid": "customer-feeder-b", "name": "Bob's feeder"},
        headers=operator_headers,
    ).json()
    assert first["pairing_code"] and second["pairing_code"]
    assert "device_uid=customer-feeder-a" in first["pairing_url"]
    assert "pairing_code=" in first["pairing_url"]

    alice_headers = _register_verified_customer(client, monkeypatch, "alice@example.com")
    bob_headers = _register_verified_customer(client, monkeypatch, "bob@example.com")
    wrong = client.post(
        "/devices/pair",
        json={"device_uid": "customer-feeder-a", "pairing_code": "INVALID-CODE"},
        headers=alice_headers,
    )
    assert wrong.status_code == 404
    paired_a = client.post(
        "/devices/pair",
        json={"device_uid": "customer-feeder-a", "pairing_code": first["pairing_code"]},
        headers=alice_headers,
    )
    assert paired_a.status_code == 200
    assert (
        client.post(
            "/devices/pair",
            json={"device_uid": "customer-feeder-b", "pairing_code": second["pairing_code"]},
            headers=bob_headers,
        ).status_code
        == 200
    )

    now = datetime.now(UTC).isoformat()
    for uid, api_key, temperature in (
        ("customer-feeder-a", first["api_key"], 4.1),
        ("customer-feeder-b", second["api_key"], 5.6),
    ):
        ingested = client.post(
            "/telemetry",
            json={
                "device_uid": uid,
                "idempotency_key": f"{uid}-reading-1",
                "sequence_number": 1,
                "recorded_at": now,
                "temperature_c": temperature,
                "cooling_on": temperature > 5,
                "pump_state": "IDLE",
                "sensor_status": "OK",
                "event_type": "heartbeat",
            },
            headers={"X-Device-ID": uid, "X-Device-Key": api_key},
        )
        assert ingested.status_code == 200

    assert [device["device_uid"] for device in client.get("/devices", headers=alice_headers).json()] == [
        "customer-feeder-a"
    ]
    alice_telemetry = client.get("/telemetry", headers=alice_headers).json()
    assert [record["temperature_c"] for record in alice_telemetry] == [4.1]
    assert client.get("/device-status?device_uid=customer-feeder-b", headers=alice_headers).status_code == 404
    assert client.get("/devices/customer-feeder-b/commands", headers=alice_headers).status_code == 404
    assert (
        client.post(
            "/devices/customer-feeder-b/schedules",
            json={"name": "Blocked", "hour": 9, "minute": 0},
            headers=alice_headers,
        ).status_code
        == 404
    )

    own_schedule = client.post(
        "/devices/customer-feeder-a/schedules",
        json={"name": "Breakfast", "hour": 8, "minute": 30},
        headers=alice_headers,
    )
    assert own_schedule.status_code == 201
    own_command = client.post(
        "/devices/customer-feeder-a/commands",
        json={"idempotency_key": "alice-feed", "command_type": "FEED_NOW", "payload": {"duration_ms": 1000}},
        headers=alice_headers,
    )
    assert own_command.status_code == 201
    bob_alerts = client.get("/alerts", headers=bob_headers).json()
    assert len(bob_alerts) == 1
    assert client.post(f"/alerts/{bob_alerts[0]['id']}/acknowledge", headers=alice_headers).status_code == 404
    assert client.post(f"/alerts/{bob_alerts[0]['id']}/acknowledge", headers=bob_headers).status_code == 200

    unpaired = client.delete("/devices/customer-feeder-a/pairing", headers=alice_headers)
    assert unpaired.status_code == 200
    replacement_code = unpaired.json()["pairing_code"]
    assert replacement_code
    assert client.get("/devices", headers=alice_headers).json() == []
    assert (
        client.post(
            "/devices/pair",
            json={"device_uid": "customer-feeder-a", "pairing_code": replacement_code},
            headers=alice_headers,
        ).status_code
        == 200
    )


def test_expiring_claim_transfer_and_device_credential_lifecycle(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    from app.database import SessionLocal
    from app.models import Device
    from sqlalchemy import select

    manufactured = client.post(
        "/devices",
        json={"device_uid": "claimable-feeder", "name": "Claimable feeder"},
        headers=operator_headers,
    ).json()
    assert manufactured["proof_of_possession"] == manufactured["pairing_code"]
    assert "claim_code=" in manufactured["claim_url"]
    assert manufactured["claim_expires_at"] is not None
    assert manufactured["credential_version"] == 1

    alice = _register_verified_customer(client, monkeypatch, "claim-alice@example.com")
    bob = _register_verified_customer(client, monkeypatch, "claim-bob@example.com")
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "claimable-feeder"))
        assert device is not None
        device.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert (
        client.post(
            "/devices/claim",
            json={
                "device_uid": manufactured["device_uid"],
                "proof_of_possession": manufactured["proof_of_possession"],
            },
            headers=alice,
        ).status_code
        == 404
    )
    refreshed_claim = client.post(
        "/devices/claimable-feeder/pairing-code",
        headers=operator_headers,
    ).json()
    claimed = client.post(
        "/devices/claim",
        json={
            "device_uid": manufactured["device_uid"],
            "proof_of_possession": refreshed_claim["proof_of_possession"],
        },
        headers=alice,
    )
    assert claimed.status_code == 200
    assert claimed.json()["claim_consumed_at"] is not None
    assert (
        client.post(
            "/devices/claim",
            json={
                "device_uid": manufactured["device_uid"],
                "proof_of_possession": refreshed_claim["proof_of_possession"],
            },
            headers=bob,
        ).status_code
        == 404
    )

    expired_offer = client.post("/devices/claimable-feeder/transfer", headers=alice)
    assert expired_offer.status_code == 200
    with SessionLocal() as db:
        device = db.scalar(select(Device).where(Device.device_uid == "claimable-feeder"))
        assert device is not None
        device.transfer_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert (
        client.post(
            "/devices/claim",
            json={
                "device_uid": "claimable-feeder",
                "proof_of_possession": expired_offer.json()["proof_of_possession"],
            },
            headers=bob,
        ).status_code
        == 404
    )

    transfer = client.post("/devices/claimable-feeder/transfer", headers=alice)
    assert transfer.status_code == 200
    assert "claim_code=" in transfer.json()["claim_url"]
    transferred = client.post(
        "/devices/claim",
        json={
            "device_uid": "claimable-feeder",
            "proof_of_possession": transfer.json()["proof_of_possession"],
        },
        headers=bob,
    )
    assert transferred.status_code == 200
    assert client.get("/devices", headers=alice).json() == []
    assert [item["device_uid"] for item in client.get("/devices", headers=bob).json()] == ["claimable-feeder"]
    assert client.delete("/devices/claimable-feeder/transfer", headers=alice).status_code == 404

    rotated = client.post("/devices/claimable-feeder/rotate-key", headers=operator_headers)
    assert rotated.status_code == 200
    assert rotated.json()["credential_version"] == 2
    old_headers = {"X-Device-ID": "claimable-feeder", "X-Device-Key": manufactured["api_key"]}
    telemetry = {
        "device_uid": "claimable-feeder",
        "idempotency_key": "credential-check",
        "sequence_number": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "temperature_c": 4.3,
        "cooling_on": False,
        "pump_state": "IDLE",
        "sensor_status": "OK",
        "event_type": "heartbeat",
    }
    assert client.post("/telemetry", json=telemetry, headers=old_headers).status_code == 401
    rotated_headers = {"X-Device-ID": "claimable-feeder", "X-Device-Key": rotated.json()["api_key"]}
    assert client.post("/telemetry", json=telemetry, headers=rotated_headers).status_code == 200

    revoked = client.post("/devices/claimable-feeder/revoke", headers=operator_headers)
    assert revoked.status_code == 200
    assert revoked.json()["active"] is False
    assert revoked.json()["credential_version"] == 3
    assert (
        client.post("/telemetry", json={**telemetry, "idempotency_key": "revoked"}, headers=rotated_headers).status_code
        == 401
    )
    activated = client.post("/devices/claimable-feeder/activate", headers=operator_headers)
    assert activated.status_code == 200
    assert activated.json()["active"] is True
    assert activated.json()["credential_version"] == 4


def test_console_and_smtp_email_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.email_delivery as email_delivery

    monkeypatch.setattr(email_delivery.settings, "email_delivery_mode", "console")
    email_delivery.deliver_account_email("person@example.com", "Subject", "Body")

    sent: list[object] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            sent.append((host, port, timeout))

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args) -> None:  # type: ignore[no-untyped-def]
            return None

        def starttls(self) -> None:
            sent.append("tls")

        def login(self, username: str, password: str) -> None:
            sent.append((username, password))

        def send_message(self, message) -> None:  # type: ignore[no-untyped-def]
            sent.append(message)

    monkeypatch.setattr(email_delivery.settings, "email_delivery_mode", "smtp")
    monkeypatch.setattr(email_delivery.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_delivery.settings, "smtp_from_email", "feeder@example.com")
    monkeypatch.setattr(email_delivery.settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(email_delivery.settings, "smtp_password", "smtp-pass")
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    email_delivery.deliver_account_email("person@example.com", "Verify", "Follow the link")
    assert "tls" in sent
    assert ("smtp-user", "smtp-pass") in sent


def test_failed_registration_email_rolls_back_customer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    def reject_delivery(*_args: object) -> None:
        raise OSError("SMTP unavailable")

    monkeypatch.setattr(main_module, "deliver_account_email", reject_delivery)
    response = client.post(
        "/auth/register",
        json={"email": "delivery-failed@example.com", "password": "SecureFeeder42"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Verification email could not be sent"

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "delivery-failed@example.com")) is None


def test_customer_onboarding_reaches_first_completed_feed_through_smtp(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
) -> None:
    import app.email_delivery as email_delivery

    smtp_events: list[object] = []
    delivered_messages: list[object] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            smtp_events.append((host, port, timeout))

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def starttls(self) -> None:
            smtp_events.append("tls")

        def login(self, username: str, password: str) -> None:
            smtp_events.append((username, password))

        def send_message(self, message: object) -> None:
            delivered_messages.append(message)

    monkeypatch.setattr(email_delivery.settings, "email_delivery_mode", "smtp")
    monkeypatch.setattr(email_delivery.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(email_delivery.settings, "smtp_port", 587)
    monkeypatch.setattr(email_delivery.settings, "smtp_from_email", "accounts@smartfishfeeder.org")
    monkeypatch.setattr(email_delivery.settings, "smtp_username", "smtp-user")
    monkeypatch.setattr(email_delivery.settings, "smtp_password", "smtp-app-password")
    monkeypatch.setattr(email_delivery.settings, "smtp_starttls", True)
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    provisioned = client.post(
        "/devices",
        json={"device_uid": "onboarding-feeder", "name": "Onboarding feeder"},
        headers=operator_headers,
    )
    assert provisioned.status_code == 201
    device = provisioned.json()

    email = "new-owner@example.com"
    password = "SecureFeeder42"
    registered = client.post("/auth/register", json={"email": email, "password": password})
    assert registered.status_code == 202
    assert len(delivered_messages) == 1
    verification_message = delivered_messages[-1]
    assert verification_message["From"] == "accounts@smartfishfeeder.org"  # type: ignore[index]
    assert verification_message["To"] == email  # type: ignore[index]
    verification_token = _token_from_email(verification_message.get_content(), "verify_token")  # type: ignore[attr-defined]

    assert client.post("/auth/verify-email", json={"token": verification_token}).status_code == 200
    login = client.post("/auth/token", data={"username": email, "password": password})
    assert login.status_code == 200
    customer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    paired = client.post(
        "/devices/pair",
        json={"device_uid": device["device_uid"], "pairing_code": device["pairing_code"]},
        headers=customer_headers,
    )
    assert paired.status_code == 200
    assert [item["device_uid"] for item in client.get("/devices", headers=customer_headers).json()] == [
        "onboarding-feeder"
    ]

    device_headers = {"X-Device-ID": device["device_uid"], "X-Device-Key": device["api_key"]}
    heartbeat = client.post(
        "/telemetry",
        json={
            "device_uid": device["device_uid"],
            "idempotency_key": "onboarding-heartbeat-1",
            "sequence_number": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "temperature_c": 4.3,
            "cooling_on": False,
            "pump_state": "IDLE",
            "sensor_status": "OK",
            "event_type": "heartbeat",
        },
        headers=device_headers,
    )
    assert heartbeat.status_code == 200
    assert client.get("/device-status?device_uid=onboarding-feeder", headers=customer_headers).json()["online"] is True

    submitted = client.post(
        "/devices/onboarding-feeder/commands",
        json={
            "idempotency_key": "first-customer-feed",
            "command_type": "FEED_NOW",
            "payload": {"duration_ms": 1_000},
        },
        headers=customer_headers,
    )
    assert submitted.status_code == 201
    claimed = client.post("/device-commands/claim", headers=device_headers)
    assert claimed.status_code == 200
    assert [command["id"] for command in claimed.json()] == [submitted.json()["id"]]
    completed = client.post(
        f"/device-commands/{submitted.json()['id']}/complete",
        json={"status": "COMPLETED", "result": "feeding_and_cleaning_completed"},
        headers=device_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["result"] == "feeding_and_cleaning_completed"
    command_history = client.get("/devices/onboarding-feeder/commands", headers=customer_headers).json()
    assert command_history[0]["status"] == "COMPLETED"

    reset_requested = client.post("/auth/password-reset/request", json={"email": email})
    assert reset_requested.status_code == 202
    assert len(delivered_messages) == 2
    reset_token = _token_from_email(delivered_messages[-1].get_content(), "reset_token")  # type: ignore[attr-defined]
    new_password = "ReplacementFeeder84"
    assert (
        client.post(
            "/auth/password-reset/confirm",
            json={"token": reset_token, "password": new_password},
        ).status_code
        == 200
    )
    assert client.post("/auth/token", data={"username": email, "password": new_password}).status_code == 200
    assert smtp_events.count("tls") == 2
    assert smtp_events.count(("smtp-user", "smtp-app-password")) == 2
