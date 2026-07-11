import hashlib
import hmac

import pytest

from mock_device.mqtt_bridge import (
    MQTT_SHARED_SECRET,
    on_message,
    telemetry_canonical,
    verify_result_signature,
    verify_signature,
)


def signed_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "device_uid": "feeder-001",
        "sequence_number": 42,
        "idempotency_key": "mqtt-test-42",
        "recorded_at": "2026-07-11T12:00:00Z",
        "temperature_c": 4.125,
        "cooling_on": False,
        "pump_state": "IDLE",
        "sensor_status": "OK",
        "event_type": "heartbeat",
        "schedule_id": None,
    }
    payload["signature"] = hmac.new(
        MQTT_SHARED_SECRET.encode("utf-8"), telemetry_canonical(payload), hashlib.sha256
    ).hexdigest()
    return payload


def test_valid_signature_is_removed_before_http_forwarding() -> None:
    payload = signed_payload()
    verify_signature(payload)
    assert "signature" not in payload


def test_telemetry_canonical_known_vector() -> None:
    payload: dict[str, object] = {
        "device_uid": "feeder-001",
        "sequence_number": 1783773296000123,
        "idempotency_key": "mqtt-a1b2c3d4-1783773296000123",
        "recorded_at": "2026-07-11T12:34:56Z",
        "temperature_c": 4.0,
        "cooling_on": False,
        "pump_state": "IDLE",
        "sensor_status": "OK",
        "event_type": "heartbeat",
        "schedule_id": None,
    }
    signature = hmac.new(b"local-development-mqtt-secret", telemetry_canonical(payload), hashlib.sha256).hexdigest()
    assert signature == "b58ac41df15885ef3bc69f89b0e34782c67d5edd5f289d96917e4acb8ced8d02"


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("temperature_c", 6.0),
        ("cooling_on", True),
        ("pump_state", "FEEDING"),
        ("sensor_status", "DISCONNECTED"),
        ("event_type", "feeding_cycle_completed"),
        ("schedule_id", 7),
    ],
)
def test_signature_rejects_tampered_telemetry(field: str, tampered_value: object) -> None:
    payload = signed_payload()
    payload[field] = tampered_value
    with pytest.raises(ValueError, match="invalid"):
        verify_signature(payload)


def test_invalid_or_missing_signature_is_rejected() -> None:
    payload = signed_payload()
    payload["signature"] = "invalid"
    with pytest.raises(ValueError, match="invalid"):
        verify_signature(payload)
    with pytest.raises(ValueError, match="requires"):
        verify_signature({"device_uid": "feeder-001"})


def test_command_result_signature() -> None:
    payload: dict[str, object] = {"command_id": 9, "status": "COMPLETED", "result": "dispensed"}
    payload["signature"] = hmac.new(MQTT_SHARED_SECRET.encode(), b"9|COMPLETED|dispensed", hashlib.sha256).hexdigest()
    verify_result_signature(payload, MQTT_SHARED_SECRET)
    assert "signature" not in payload


def test_malformed_broker_message_does_not_escape_callback() -> None:
    class BadMessage:
        topic = "fish-feeder/feeder-001/telemetry"
        payload = b"not-json"

    on_message(None, None, BadMessage())  # type: ignore[arg-type]
