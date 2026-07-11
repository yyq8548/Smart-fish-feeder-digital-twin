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
