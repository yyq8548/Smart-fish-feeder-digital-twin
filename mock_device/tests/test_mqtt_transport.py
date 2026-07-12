import hashlib
import hmac
import ssl

import pytest

from mock_device.mqtt_bridge import (
    MqttTransportConfig,
    build_command_message,
    build_mqtt_ssl_context,
    configure_mqtt_transport,
    load_mqtt_transport_config,
    normalize_command_expiry,
)

TRANSPORT_ENV_VARS = (
    "MQTT_TLS_ENABLED",
    "MQTT_TLS_INSECURE",
    "MQTT_TLS_CA_FILE",
    "MQTT_TLS_CERT_FILE",
    "MQTT_TLS_KEY_FILE",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
)


class RecordingClient:
    def __init__(self) -> None:
        self.username_calls: list[tuple[str, str | None]] = []
        self.tls_contexts: list[ssl.SSLContext | None] = []

    def username_pw_set(self, username: str, password: str | None = None) -> None:
        self.username_calls.append((username, password))

    def tls_set_context(self, context: ssl.SSLContext | None = None) -> None:
        self.tls_contexts.append(context)


def clear_transport_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in TRANSPORT_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)


def test_transport_defaults_preserve_local_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_transport_environment(monkeypatch)
    config = load_mqtt_transport_config()
    assert config == MqttTransportConfig(False, False, None, None, None, None, None)


def test_verified_tls_and_credentials_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_transport_environment(monkeypatch)
    monkeypatch.setenv("MQTT_TLS_ENABLED", "true")
    monkeypatch.setenv("MQTT_USERNAME", "bridge-user")
    monkeypatch.setenv("MQTT_PASSWORD", "bridge-password")

    config = load_mqtt_transport_config()
    client = RecordingClient()
    configure_mqtt_transport(client, config)

    assert client.username_calls == [("bridge-user", "bridge-password")]
    assert len(client.tls_contexts) == 1
    context = client.tls_contexts[0]
    assert context is not None
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_insecure_tls_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_transport_environment(monkeypatch)
    monkeypatch.setenv("MQTT_TLS_ENABLED", "true")
    monkeypatch.setenv("MQTT_TLS_INSECURE", "true")

    context = build_mqtt_ssl_context(load_mqtt_transport_config())
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"MQTT_PASSWORD": "orphaned"}, "MQTT_PASSWORD requires MQTT_USERNAME"),
        ({"MQTT_TLS_INSECURE": "true"}, "MQTT TLS options require"),
        ({"MQTT_TLS_CA_FILE": "ca.pem"}, "MQTT TLS options require"),
        ({"MQTT_TLS_ENABLED": "maybe"}, "MQTT_TLS_ENABLED must be one of"),
        (
            {"MQTT_TLS_ENABLED": "true", "MQTT_TLS_CERT_FILE": "device.pem"},
            "must be configured together",
        ),
    ],
)
def test_invalid_transport_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    message: str,
) -> None:
    clear_transport_environment(monkeypatch)
    for variable, value in environment.items():
        monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=message):
        load_mqtt_transport_config()


def test_command_expiry_is_included_in_message_and_signature() -> None:
    expires_at = "2026-07-11T12:34:56.123456Z"
    normalized_expiry = "2026-07-11T12:34:56Z"
    message = build_command_message(
        {
            "id": 42,
            "command_type": "FEED_NOW",
            "payload_json": '{"duration_ms":1000}',
            "expires_at": expires_at,
        },
        "test-secret",
    )
    canonical = f'42|FEED_NOW|{{"duration_ms":1000}}|{normalized_expiry}'
    expected = hmac.new(b"test-secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert message["expires_at"] == normalized_expiry
    assert message["signature"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-11T12:34:56.123456", "2026-07-11T12:34:56Z"),
        ("2026-07-11T08:34:56-04:00", "2026-07-11T12:34:56Z"),
        ("2026-07-11T12:34:56+00:00", "2026-07-11T12:34:56Z"),
    ],
)
def test_command_expiry_is_normalized_to_explicit_utc(value: str, expected: str) -> None:
    assert normalize_command_expiry(value) == expected


def test_legacy_command_without_expiry_keeps_original_canonical_value() -> None:
    message = build_command_message(
        {"id": 9, "command_type": "CLEAN_PUMP", "payload_json": "{}"},
        "test-secret",
    )
    expected = hmac.new(b"test-secret", b"9|CLEAN_PUMP|{}", hashlib.sha256).hexdigest()
    assert "expires_at" not in message
    assert message["signature"] == expected
