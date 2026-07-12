# Device simulators and MQTT bridge

- `mock_esp32_client.py` posts telemetry directly to FastAPI every two seconds.
- `mqtt_bridge.py` subscribes only to explicitly configured device topics, forwards signed telemetry to HTTP, polls leased backend commands, publishes signed command messages, and forwards signed device results.

From the repository root, with the backend running:

```powershell
.\.venv\Scripts\python.exe -m pip install -r mock_device\requirements.txt
$env:DEVICE_API_KEY = "local-development-key"
.\.venv\Scripts\python.exe mock_device\mock_esp32_client.py
```

Both paths send the complete device contract: UID, idempotency key, monotonic sequence, UTC event time, temperature, cooling state, pump state, sensor status, and event type.

The bridge verifies the message's HMAC-SHA256 `signature` using `MQTT_SHARED_SECRET` before it supplies the API credential. The versioned canonical record covers every accepted telemetry value, including temperature, actuator state, sensor status, event type, and schedule ID; the exact byte contract and known vector are documented in [`../firmware/README.md`](../firmware/README.md). It also validates that the topic UID, payload UID, API credential map, and signing-secret map agree. A `4xx` response is treated as a permanent credential or contract failure; connection and server failures use bounded exponential retry. Malformed broker messages are rejected per-message without terminating the bridge.

For multiple devices, set `DEVICE_CREDENTIALS_JSON` and `MQTT_SHARED_SECRETS_JSON` to JSON objects with identical UID keys. The bridge never accepts an arbitrary payload UID and attaches a global trusted credential.

## MQTT broker transport

The Wokwi/local defaults remain plaintext MQTT on `127.0.0.1:1883`. For a
cloud broker, enable verified TLS and configure broker credentials:

```powershell
$env:MQTT_HOST = "your-broker.example.com"
$env:MQTT_PORT = "8883"
$env:MQTT_TLS_ENABLED = "true"
$env:MQTT_USERNAME = "bridge-user"
$env:MQTT_PASSWORD = "replace-me"
python mock_device\mqtt_bridge.py
```

With no `MQTT_TLS_CA_FILE`, Python's trusted system CA store is used. Set it to
the provider's PEM CA bundle when the broker uses a private CA. Optional mutual
TLS uses `MQTT_TLS_CERT_FILE` and `MQTT_TLS_KEY_FILE`, which must be supplied
together. TLS requires version 1.2 or newer and verifies both the certificate
chain and broker hostname by default.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MQTT_HOST` | `127.0.0.1` | Broker DNS name or address |
| `MQTT_PORT` | `1883` | Broker port; cloud TLS commonly uses `8883` |
| `MQTT_CLIENT_ID` | `fish-feeder-http-bridge` | Broker client identifier |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | unset | Broker authentication; a password without a username is rejected |
| `MQTT_TLS_ENABLED` | `false` | Enable MQTT over TLS |
| `MQTT_TLS_CA_FILE` | system CA store | Optional PEM CA bundle |
| `MQTT_TLS_CERT_FILE` / `MQTT_TLS_KEY_FILE` | unset | Optional mutual-TLS client identity |
| `MQTT_TLS_INSECURE` | `false` | Disable CA and hostname verification for local development only |

`MQTT_TLS_INSECURE=true` is accepted only when TLS is enabled and emits a loud
startup warning. It must never be used with an internet broker. Username and
password authentication without TLS is retained for trusted local-broker
compatibility, but the bridge warns because those credentials are exposed on
the network.

Claimed commands include the API's `expires_at` value when present. The bridge
normalizes it to explicit UTC (`Z`) first, including SQLite values that arrive
without an offset, then appends that exact published value to the command HMAC
canonical value. It therefore cannot be removed or extended in transit. The
ESP32 rejects invalid or already-expired timestamps before actuation. Command
publishes always use `retain=False`; keep retained command messages disabled in
broker ACLs as an additional stale-command control.
