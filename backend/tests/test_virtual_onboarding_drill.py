from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from scripts.manufacture_device import write_bundle


def register_verified_customer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
) -> dict[str, str]:
    import app.main as main_module

    messages: list[str] = []
    monkeypatch.setattr(
        main_module,
        "deliver_account_email",
        lambda _recipient, _subject, body: messages.append(body),
    )
    password = "SecureFeeder42"
    assert client.post("/auth/register", json={"email": email, "password": password}).status_code == 202
    verification_url = next(line for line in messages[-1].splitlines() if "verify_token=" in line)
    token = parse_qs(urlparse(verification_url).query)["verify_token"][0]
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    login = client.post("/auth/token", data={"username": email, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_complete_no_hardware_device_lifecycle_drill(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operator_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    provisioned_response = client.post(
        "/devices",
        json={"device_uid": "virtual-drill-feeder", "name": "Virtual drill feeder"},
        headers=operator_headers,
    )
    assert provisioned_response.status_code == 201
    provisioned = provisioned_response.json()
    root_ca = Path("simulation/esp32-mqtt/amazon-root-ca-1.pem").read_text(encoding="utf-8")
    bundle = write_bundle(
        tmp_path / "virtual-drill-feeder",
        provisioned,
        mqtt_host="mqtt.smartfishfeeder.org",
        mqtt_port=8883,
        mqtt_root_ca=root_ca,
    )
    assert Path(bundle["qr"]).stat().st_size > 0
    assert Path(bundle["label"]).stat().st_size > 0
    assert Path(bundle["firmware_header"]).stat().st_size > 0

    claim_query = parse_qs(urlparse(provisioned["claim_url"]).query)
    assert claim_query == {
        "device_uid": ["virtual-drill-feeder"],
        "claim_code": [provisioned["proof_of_possession"]],
    }
    owner_a = register_verified_customer(client, monkeypatch, email="virtual-owner-a@example.com")
    owner_b = register_verified_customer(client, monkeypatch, email="virtual-owner-b@example.com")

    claim_payload = {
        "device_uid": "virtual-drill-feeder",
        "proof_of_possession": provisioned["proof_of_possession"],
    }
    assert client.post("/devices/claim", json=claim_payload, headers=owner_a).status_code == 200
    assert client.post("/devices/claim", json=claim_payload, headers=owner_a).status_code == 404

    device_headers = {
        "X-Device-ID": "virtual-drill-feeder",
        "X-Device-Key": provisioned["api_key"],
    }
    heartbeat = {
        "device_uid": "virtual-drill-feeder",
        "idempotency_key": "virtual-heartbeat-1",
        "sequence_number": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "temperature_c": 4.2,
        "cooling_on": False,
        "pump_state": "IDLE",
        "sensor_status": "OK",
        "event_type": "heartbeat",
    }
    assert client.post("/telemetry", json=heartbeat, headers=device_headers).status_code == 200
    submitted = client.post(
        "/devices/virtual-drill-feeder/commands",
        json={
            "idempotency_key": "virtual-first-feed",
            "command_type": "FEED_NOW",
            "payload": {"duration_ms": 1_000},
        },
        headers=owner_a,
    )
    assert submitted.status_code == 201
    claimed = client.post("/device-commands/claim", headers=device_headers)
    assert claimed.status_code == 200
    assert [item["id"] for item in claimed.json()] == [submitted.json()["id"]]
    completed = client.post(
        f"/device-commands/{submitted.json()['id']}/complete",
        json={"status": "COMPLETED", "result": "virtual_gpio_cycle_completed"},
        headers=device_headers,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"

    unpaired = client.delete("/devices/virtual-drill-feeder/pairing", headers=owner_a)
    assert unpaired.status_code == 200
    assert client.get("/devices", headers=owner_a).json() == []
    replacement_proof = unpaired.json()["proof_of_possession"]
    assert (
        client.post(
            "/devices/claim",
            json={
                "device_uid": "virtual-drill-feeder",
                "proof_of_possession": replacement_proof,
            },
            headers=owner_a,
        ).status_code
        == 200
    )
    transfer = client.post("/devices/virtual-drill-feeder/transfer", headers=owner_a)
    assert transfer.status_code == 200
    assert (
        client.post(
            "/devices/claim",
            json={
                "device_uid": "virtual-drill-feeder",
                "proof_of_possession": transfer.json()["proof_of_possession"],
            },
            headers=owner_b,
        ).status_code
        == 200
    )
    assert client.get("/devices", headers=owner_a).json() == []
    assert [item["device_uid"] for item in client.get("/devices", headers=owner_b).json()] == ["virtual-drill-feeder"]

    revoked = client.post("/devices/virtual-drill-feeder/revoke", headers=operator_headers)
    assert revoked.status_code == 200
    assert (
        client.post("/telemetry", json={**heartbeat, "idempotency_key": "revoked"}, headers=device_headers).status_code
        == 401
    )
    activated = client.post("/devices/virtual-drill-feeder/activate", headers=operator_headers)
    assert activated.status_code == 200
    assert activated.json()["credential_version"] == revoked.json()["credential_version"] + 1
    replacement_headers = {
        "X-Device-ID": "virtual-drill-feeder",
        "X-Device-Key": activated.json()["api_key"],
    }
    assert (
        client.post(
            "/telemetry",
            json={
                **heartbeat,
                "idempotency_key": "virtual-heartbeat-2",
                "sequence_number": 2,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
            headers=replacement_headers,
        ).status_code
        == 200
    )
