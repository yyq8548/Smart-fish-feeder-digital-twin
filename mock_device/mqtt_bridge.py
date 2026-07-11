"""Bidirectional signed MQTT bridge for telemetry and device commands."""

import hashlib
import hmac
import json
import os
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.enums import CallbackAPIVersion

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "fish-feeder")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/telemetry")
API_BASE = API_URL.removesuffix("/telemetry")
DEVICE_UID = os.getenv("DEVICE_UID", "feeder-001")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "local-development-key")
MQTT_SHARED_SECRET = os.getenv("MQTT_SHARED_SECRET", "local-development-mqtt-secret")
COMMAND_POLL_SECONDS = float(os.getenv("COMMAND_POLL_SECONDS", "2"))


def _load_string_map(variable: str, fallback_key: str, fallback_value: str) -> dict[str, str]:
    raw = os.getenv(variable)
    if not raw:
        return {fallback_key: fallback_value}
    parsed = json.loads(raw)
    if (
        not isinstance(parsed, dict)
        or not parsed
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items())
    ):
        raise ValueError(f"{variable} must be a non-empty JSON object of string values")
    return parsed


DEVICE_CREDENTIALS = _load_string_map("DEVICE_CREDENTIALS_JSON", DEVICE_UID, DEVICE_API_KEY)
MQTT_SHARED_SECRETS = _load_string_map("MQTT_SHARED_SECRETS_JSON", DEVICE_UID, MQTT_SHARED_SECRET)
if DEVICE_CREDENTIALS.keys() != MQTT_SHARED_SECRETS.keys():
    raise ValueError("Device credential and MQTT signing-secret maps must contain the same device UIDs")


def _digest(secret: str, canonical: str | bytes) -> str:
    message = canonical.encode("utf-8") if isinstance(canonical, str) else canonical
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _canonical_field(label: str, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return label.encode("ascii") + b":" + str(len(encoded)).encode("ascii") + b":" + encoded


def telemetry_canonical(payload: dict[str, object]) -> bytes:
    required_types: dict[str, type[object]] = {
        "device_uid": str,
        "sequence_number": int,
        "idempotency_key": str,
        "recorded_at": str,
        "cooling_on": bool,
        "pump_state": str,
        "sensor_status": str,
    }
    for field, expected_type in required_types.items():
        value = payload.get(field)
        if not isinstance(value, expected_type) or (expected_type is int and isinstance(value, bool)):
            raise ValueError(f"MQTT telemetry field {field} has an invalid type")

    temperature = payload.get("temperature_c")
    if temperature is None:
        temperature_mdeg = "null"
    else:
        if isinstance(temperature, bool) or not isinstance(temperature, int | float):
            raise ValueError("MQTT telemetry field temperature_c has an invalid type")
        try:
            decimal_temperature = Decimal(str(temperature))
            if not decimal_temperature.is_finite():
                raise ValueError("MQTT telemetry temperature_c must be finite")
            temperature_mdeg = str(
                int((decimal_temperature * Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("MQTT telemetry temperature_c is invalid") from exc

    event_type = payload.get("event_type")
    if event_type is not None and not isinstance(event_type, str):
        raise ValueError("MQTT telemetry field event_type has an invalid type")
    schedule_id = payload.get("schedule_id")
    if schedule_id is not None and (not isinstance(schedule_id, int) or isinstance(schedule_id, bool)):
        raise ValueError("MQTT telemetry field schedule_id has an invalid type")

    values = (
        ("device_uid", str(payload["device_uid"])),
        ("sequence_number", str(payload["sequence_number"])),
        ("idempotency_key", str(payload["idempotency_key"])),
        ("recorded_at", str(payload["recorded_at"])),
        ("temperature_mdeg", temperature_mdeg),
        ("cooling_on", "1" if payload["cooling_on"] else "0"),
        ("pump_state", str(payload["pump_state"])),
        ("sensor_status", str(payload["sensor_status"])),
        ("event_type", "null" if event_type is None else event_type),
        ("schedule_id", "null" if schedule_id is None else str(schedule_id)),
    )
    return b"\n".join([b"fish-feeder-telemetry-v1", *(_canonical_field(label, value) for label, value in values)])


def verify_signature(payload: dict[str, object], secret: str = MQTT_SHARED_SECRET) -> None:
    signature = payload.pop("signature", None)
    if not isinstance(signature, str):
        raise ValueError("MQTT telemetry requires a signature")
    expected = _digest(secret, telemetry_canonical(payload))
    if not hmac.compare_digest(signature, expected):
        raise ValueError("MQTT telemetry signature is invalid")


def verify_result_signature(payload: dict[str, object], secret: str) -> None:
    signature = payload.pop("signature", None)
    fields = (payload.get("command_id"), payload.get("status"), payload.get("result", ""))
    if not isinstance(signature, str) or any(value is None for value in fields):
        raise ValueError("Command result requires a signature and canonical result fields")
    expected = _digest(secret, "|".join(str(value) for value in fields))
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Command result signature is invalid")


def _request_with_retry(
    method: str,
    url: str,
    *,
    json_body: object | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    for attempt in range(4):
        try:
            response = requests.request(method, url, timeout=5, json=json_body, headers=headers)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if exc.response is not None and 400 <= exc.response.status_code < 500:
                raise
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def _headers(device_uid: str) -> dict[str, str]:
    return {"X-Device-ID": device_uid, "X-Device-Key": DEVICE_CREDENTIALS[device_uid]}


def forward(payload: dict[str, object], device_uid: str) -> None:
    _request_with_retry("POST", API_URL, json_body=payload, headers=_headers(device_uid))


def complete_command(payload: dict[str, object], device_uid: str) -> None:
    command_id = payload.get("command_id")
    if not isinstance(command_id, int):
        raise ValueError("Command result requires an integer command_id")
    body = {"status": payload.get("status"), "result": payload.get("result") or None}
    _request_with_retry(
        "POST",
        f"{API_BASE}/device-commands/{command_id}/complete",
        json_body=body,
        headers=_headers(device_uid),
    )


def on_connect(
    client: mqtt.Client,
    _userdata: object,
    _flags: dict[str, object],
    reason_code: Any,
    _properties: object,
) -> None:
    if reason_code.is_failure:
        return
    for device_uid in DEVICE_CREDENTIALS:
        client.subscribe(f"{MQTT_TOPIC_PREFIX}/{device_uid}/telemetry", qos=1)
        client.subscribe(f"{MQTT_TOPIC_PREFIX}/{device_uid}/command-results", qos=1)


def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
    try:
        parts = message.topic.split("/")
        if len(parts) != 3 or parts[0] != MQTT_TOPIC_PREFIX:
            raise ValueError("Unexpected MQTT topic")
        device_uid, message_type = parts[1], parts[2]
        if device_uid not in DEVICE_CREDENTIALS:
            raise ValueError("MQTT topic uses an unconfigured device UID")
        payload = json.loads(message.payload.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("MQTT payload must be a JSON object")
        if message_type == "telemetry":
            if payload.get("device_uid") != device_uid:
                raise ValueError("MQTT topic and payload device UIDs do not match")
            verify_signature(payload, MQTT_SHARED_SECRETS[device_uid])
            forward(payload, device_uid)
        elif message_type == "command-results":
            verify_result_signature(payload, MQTT_SHARED_SECRETS[device_uid])
            complete_command(payload, device_uid)
        else:
            raise ValueError("Unsupported MQTT message type")
    except Exception as exc:
        print(f"Rejected MQTT message on {message.topic}: {exc}", flush=True)


def publish_pending_commands(client: mqtt.Client) -> None:
    for device_uid, api_key in DEVICE_CREDENTIALS.items():
        try:
            response = _request_with_retry(
                "POST",
                f"{API_BASE}/device-commands/claim",
                headers={"X-Device-ID": device_uid, "X-Device-Key": api_key},
            )
            commands = response.json()
            if not isinstance(commands, list):
                raise ValueError("Command claim response must be a list")
            for command in commands:
                if not isinstance(command, dict):
                    continue
                command_id = command["id"]
                command_type = command["command_type"]
                payload_json = command["payload_json"]
                canonical = f"{command_id}|{command_type}|{payload_json}"
                message = {
                    "command_id": command_id,
                    "command_type": command_type,
                    "payload_json": payload_json,
                    "signature": _digest(MQTT_SHARED_SECRETS[device_uid], canonical),
                }
                result = client.publish(
                    f"{MQTT_TOPIC_PREFIX}/{device_uid}/commands",
                    json.dumps(message, separators=(",", ":")),
                    qos=1,
                    retain=False,
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(f"MQTT command publish failed with rc={result.rc}")
        except Exception as exc:
            print(f"Command polling failed for {device_uid}: {exc}", flush=True)


def main() -> None:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="fish-feeder-http-bridge")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    try:
        while True:
            if client.is_connected():
                publish_pending_commands(client)
            time.sleep(COMMAND_POLL_SECONDS)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
