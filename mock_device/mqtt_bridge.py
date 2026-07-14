"""Bidirectional signed MQTT bridge for telemetry and device commands."""

import hashlib
import hmac
import json
import os
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

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
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fish-feeder-http-bridge")


@dataclass(frozen=True)
class MqttTransportConfig:
    """Broker authentication and TLS settings loaded at bridge startup."""

    use_tls: bool
    tls_insecure: bool
    ca_file: str | None
    client_cert_file: str | None
    client_key_file: str | None
    username: str | None
    password: str | None


class MqttClientConfigurator(Protocol):
    def username_pw_set(self, username: str, password: str | None = None) -> None: ...

    def tls_set_context(self, context: ssl.SSLContext | None = None) -> None: ...


def _load_bool(variable: str, default: bool = False) -> bool:
    raw = os.getenv(variable)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{variable} must be one of true/false, 1/0, yes/no, or on/off")


def load_mqtt_transport_config() -> MqttTransportConfig:
    use_tls = _load_bool("MQTT_TLS_ENABLED")
    tls_insecure = _load_bool("MQTT_TLS_INSECURE")
    ca_file = os.getenv("MQTT_TLS_CA_FILE") or None
    client_cert_file = os.getenv("MQTT_TLS_CERT_FILE") or None
    client_key_file = os.getenv("MQTT_TLS_KEY_FILE") or None
    username = os.getenv("MQTT_USERNAME") or None
    password = os.getenv("MQTT_PASSWORD") or None

    if password is not None and username is None:
        raise ValueError("MQTT_PASSWORD requires MQTT_USERNAME")
    if (client_cert_file is None) != (client_key_file is None):
        raise ValueError("MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE must be configured together")
    if not use_tls and (tls_insecure or ca_file or client_cert_file or client_key_file):
        raise ValueError("MQTT TLS options require MQTT_TLS_ENABLED=true")

    return MqttTransportConfig(
        use_tls=use_tls,
        tls_insecure=tls_insecure,
        ca_file=ca_file,
        client_cert_file=client_cert_file,
        client_key_file=client_key_file,
        username=username,
        password=password,
    )


def build_mqtt_ssl_context(config: MqttTransportConfig) -> ssl.SSLContext:
    if not config.use_tls:
        raise ValueError("Cannot build an MQTT TLS context when TLS is disabled")

    if config.tls_insecure:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        # With no explicit CA file, Python's trusted system CA store is used.
        context = ssl.create_default_context(cafile=config.ca_file)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if config.client_cert_file is not None and config.client_key_file is not None:
        context.load_cert_chain(config.client_cert_file, config.client_key_file)
    return context


def configure_mqtt_transport(client: MqttClientConfigurator, config: MqttTransportConfig) -> None:
    if config.username is not None:
        client.username_pw_set(config.username, config.password)
    if config.use_tls:
        client.tls_set_context(build_mqtt_ssl_context(config))


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


def command_canonical(
    command_id: int,
    command_type: str,
    payload_json: str,
    expires_at: str | None = None,
) -> str:
    canonical = f"{command_id}|{command_type}|{payload_json}"
    if expires_at is not None:
        canonical = f"{canonical}|{expires_at}"
    return canonical


def normalize_command_expiry(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Claimed command expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        # SQLite can return a naive value for a timezone-aware UTC column.
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    if parsed.year < 1970:
        raise ValueError("Claimed command expires_at must not predate the Unix epoch")
    # The ESP32 parser enforces whole-second deadlines. Floor here so the
    # signed value and the device-side deadline are exactly the same instant.
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_command_message(command: dict[str, object], secret: str) -> dict[str, object]:
    command_id = command.get("id")
    command_type = command.get("command_type")
    payload_json = command.get("payload_json")
    expires_at = command.get("expires_at")
    if not isinstance(command_id, int) or isinstance(command_id, bool) or command_id <= 0:
        raise ValueError("Claimed command requires a positive integer id")
    if not isinstance(command_type, str) or not command_type:
        raise ValueError("Claimed command requires a non-empty command_type")
    if not isinstance(payload_json, str):
        raise ValueError("Claimed command requires string payload_json")
    if expires_at is not None and (not isinstance(expires_at, str) or not expires_at):
        raise ValueError("Claimed command expires_at must be a non-empty string when present")
    normalized_expiry = normalize_command_expiry(expires_at) if expires_at is not None else None

    message: dict[str, object] = {
        "command_id": command_id,
        "command_type": command_type,
        "payload_json": payload_json,
        "signature": _digest(
            secret,
            command_canonical(command_id, command_type, payload_json, normalized_expiry),
        ),
    }
    if normalized_expiry is not None:
        message["expires_at"] = normalized_expiry
    return message


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
    print(
        f"Accepted signed command result for {device_uid} command {command_id}: {body['status']}",
        flush=True,
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
                message = build_command_message(command, MQTT_SHARED_SECRETS[device_uid])
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
    transport_config = load_mqtt_transport_config()
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    configure_mqtt_transport(client, transport_config)
    client.on_connect = on_connect
    client.on_message = on_message
    if transport_config.use_tls and transport_config.tls_insecure:
        print(
            "WARNING: MQTT_TLS_INSECURE disables certificate and hostname verification; "
            "use only for local development",
            flush=True,
        )
    elif not transport_config.use_tls and transport_config.username is not None:
        print("WARNING: MQTT credentials are being sent over plaintext MQTT", flush=True)
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
