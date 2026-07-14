# ESP32 MQTT Wokwi simulation

This simulation replaces the Python-only telemetry source with the same ESP32
state machine that can run on physical hardware:

```text
DS18B20 + button <-> ESP32 <-> MQTT <-> MQTT bridge <-> FastAPI/dashboard
```

## Files

- `../../firmware/esp32_mqtt/esp32_mqtt.ino` - the single firmware source
- `diagram.json` - ESP32, DS18B20, button, and output indicators
- `libraries.txt` - Arduino libraries installed by Wokwi
- `wokwi.toml` - local Wokwi for VS Code/CLI configuration
- `verify_feeder.yaml` - automated hysteresis and pump-cycle scenario
- `verify_closed_loop.yaml` - waits for a dashboard command and asserts its GPIO lifecycle
- `amazon-root-ca-1.pem` - public root used by the default verified-TLS test broker

## Run it directly from this repository

Install Arduino CLI, the ESP32 core, the four libraries in `libraries.txt`, and
either Wokwi for VS Code or Wokwi CLI. From the repository root, compile the
firmware into the location referenced by `wokwi.toml`:

```bash
arduino-cli core install esp32:esp32
arduino-cli lib install ArduinoJson DallasTemperature OneWire PubSubClient
arduino-cli compile \
  --fqbn esp32:esp32:esp32 \
  --build-path build/wokwi \
  firmware/esp32_mqtt
```

Open `simulation/esp32-mqtt/diagram.json` with Wokwi for VS Code and start the
simulator, or run the automated hardware-in-the-loop scenario:

```bash
wokwi-cli simulation/esp32-mqtt \
  --scenario verify_feeder.yaml \
  --timeout 45000
```

Wokwi CLI requires `WOKWI_CLI_TOKEN`. The same scenario runs in GitHub Actions
when that repository secret is configured. The non-token contract tests still
run on every pull request and verify that the diagram wiring, firmware pin
constants, Wokwi configuration, and scenario coverage remain aligned.

## Run it in Wokwi

1. Create an Arduino ESP32 project at <https://wokwi.com/projects/new/esp32>.
2. Replace its `sketch.ino` with
   `firmware/esp32_mqtt/esp32_mqtt.ino` from this repository.
3. Replace its `diagram.json` and `libraries.txt` with the two files in this
   directory.
4. Start the simulator. Wokwi connects to the open `Wokwi-GUEST` network on
   channel 6, obtains UTC from NTP, and then connects to the MQTT broker.
5. Confirm the serial monitor prints `MQTT connected` followed by JSON payloads.

Wokwi documents its guest network and gateway behavior in the
[ESP32 WiFi guide](https://docs.wokwi.com/guides/esp32-wifi).

## Connect the simulation to the local application

The default sketch uses the public, unauthenticated
`broker.hivemq.com:1883` demonstration broker. Start the API and dashboard, then
run the repository's MQTT bridge against that same broker and the exact device
topic.

PowerShell:

```powershell
docker compose up -d backend dashboard
python -m pip install -r mock_device/requirements.txt
$env:MQTT_HOST = "broker.hivemq.com"
$env:DEVICE_UID = "feeder-001"
$env:API_URL = "http://127.0.0.1:8000/telemetry"
$env:DEVICE_API_KEY = "local-development-key"
$env:MQTT_SHARED_SECRET = "local-development-mqtt-secret"
python mock_device/mqtt_bridge.py
```

Bash:

```bash
docker compose up -d backend dashboard
python -m pip install -r mock_device/requirements.txt
MQTT_HOST=broker.hivemq.com \
DEVICE_UID=feeder-001 \
API_URL=http://127.0.0.1:8000/telemetry \
DEVICE_API_KEY=local-development-key \
MQTT_SHARED_SECRET=local-development-mqtt-secret \
python mock_device/mqtt_bridge.py
```

Open <http://localhost:8080> and sign in with the local operator credentials
from Compose (`admin` / `local-development-admin-password` unless overridden in
`.env`). The dashboard should update after the first heartbeat. If the
configured API key has been changed, give `DEVICE_API_KEY` the same value. The
firmware's default `feeder-001` UID matches the backend's bootstrap device. If
you choose a different UID, provision that device in the API first and run the
bridge with its returned key.

For a fully local broker, use Wokwi's Private IoT Gateway, change
`FEEDER_MQTT_HOST` to `host.wokwi.internal`, and run the complete Compose stack.
The public Wokwi gateway cannot reach a broker bound only to your computer.

For an automated end-to-end run without the paid Private Gateway, execute
`bash scripts/wokwi-closed-loop.sh` from the repository root. It connects both
the Compose MQTT bridge and Wokwi firmware to a unique topic namespace on a
certificate-verified TLS broker, drives `FEED_NOW` through the Chromium
dashboard, checks the physical GPIO sequence in Wokwi, validates the signed
result in the bridge, and waits for `COMPLETED` in the dashboard. The public
default broker is suitable only for isolated test traffic; provide the
`WOKWI_E2E_MQTT_*` variables documented in the main README to use an
authenticated broker.

## Exercise the state machine

- Click the DS18B20 and move its temperature above 5 C. The blue cooling LED
  turns on and subsequent telemetry reports `cooling_on: true`.
- Set the sensor to exactly 5 C. Cooling retains its previous state because the
  3-5 C band is deliberate hysteresis.
- Move it to 2.5 C. Cooling turns off.
- Press the green button. The green/yellow LEDs show a 10-second feed, followed
  by a 2-second wait and a 10-second red/yellow reverse-clean cycle.
- Press `F` while the diagram has focus as a keyboard shortcut for the manual
  feed button.
- The backend evaluates schedule timezones and due times. Its bridge dispatches
  a signed `FEED_NOW` with `schedule_id`; the device does not independently
  trigger schedules and therefore cannot double-feed because of clock or
  timezone disagreement.

Typical payload:

```json
{
  "device_uid": "feeder-001",
  "sequence_number": 1783773296000123,
  "idempotency_key": "mqtt-a1b2c3d4-1783773296000123",
  "recorded_at": "2026-07-11T12:34:56Z",
  "temperature_c": 4.0,
  "cooling_on": false,
  "pump_state": "IDLE",
  "sensor_status": "OK",
  "event_type": "heartbeat",
  "schedule_id": null,
  "signature": "b58ac41df15885ef3bc69f89b0e34782c67d5edd5f289d96917e4acb8ced8d02"
}
```

For that example, both sides sign or verify this exact canonical value:

```text
fish-feeder-telemetry-v1
device_uid:10:feeder-001
sequence_number:16:1783773296000123
idempotency_key:30:mqtt-a1b2c3d4-1783773296000123
recorded_at:20:2026-07-11T12:34:56Z
temperature_mdeg:4:4000
cooling_on:1:0
pump_state:4:IDLE
sensor_status:2:OK
event_type:9:heartbeat
schedule_id:4:null
```

There is one LF byte between lines and no trailing LF. Each decimal length is
the number of UTF-8 bytes in the value. The fixed order, labels, explicit nulls,
and length prefixes remove delimiter and optional-field ambiguity. The
signature authenticates every telemetry field except `signature` itself.

The bridge can reproduce the firmware bytes with this Python algorithm:

```python
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac


def canonical_field(label: str, value: str) -> bytes:
    value_bytes = value.encode("utf-8")
    return (
        label.encode("ascii")
        + b":"
        + str(len(value_bytes)).encode("ascii")
        + b":"
        + value_bytes
    )


def telemetry_canonical(payload: dict[str, object]) -> bytes:
    temperature = payload["temperature_c"]
    if temperature is None:
        temperature_mdeg = "null"
    else:
        temperature_mdeg = str(
            int(
                (Decimal(str(temperature)) * Decimal(1000)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        )

    values = (
        ("device_uid", str(payload["device_uid"])),
        ("sequence_number", str(int(payload["sequence_number"]))),
        ("idempotency_key", str(payload["idempotency_key"])),
        ("recorded_at", str(payload["recorded_at"])),
        ("temperature_mdeg", temperature_mdeg),
        ("cooling_on", "1" if payload["cooling_on"] else "0"),
        ("pump_state", str(payload["pump_state"])),
        ("sensor_status", str(payload["sensor_status"])),
        ("event_type", "null" if payload.get("event_type") is None else str(payload["event_type"])),
        ("schedule_id", "null" if payload.get("schedule_id") is None else str(int(payload["schedule_id"]))),
    )
    lines = [b"fish-feeder-telemetry-v1"]
    lines.extend(canonical_field(label, value) for label, value in values)
    return b"\n".join(lines)


canonical = telemetry_canonical(payload)
expected = hmac.new(
    MQTT_SHARED_SECRET.encode("utf-8"), canonical, hashlib.sha256
).hexdigest()
```

The temperature is rounded to signed integer millidegrees using half-away-from-
zero behavior. Firmware stores this integer in the queued snapshot and derives
the published `temperature_c` from it, so signing and serialization use the
same quantized measurement. All integers are plain base-10 with no leading
zeros; booleans are `0`/`1`; optional values are the four UTF-8 bytes `null`.

The firmware uses mbedTLS HMAC-SHA256 and emits lowercase hex. The signature is
stored in the queued snapshot, so retransmitting a message does not change its
authenticated fields. The bridge must reject missing, malformed, or invalid
signatures before making an authenticated API request. Use the same secret on
both sides; `local-development-mqtt-secret` is only the reproducible demo
default. Override `FEEDER_MQTT_SHARED_SECRET` in firmware and
`MQTT_SHARED_SECRET` for the bridge with a unique random value for public use.

## Signed command plane

The device subscribes to:

```text
fish-feeder/feeder-001/commands
```

Commands use a positive, strictly increasing per-device integer ID and a
JSON-encoded **string** for `payload_json`. The same monotonic ID sequence must
cover operator commands and optional `SYNC_SCHEDULES` mirror messages. The sender
signs the decoded string exactly as transmitted; it must not parse and
reserialize the inner JSON after calculating the signature. Online operator
commands also carry a signed UTC `expires_at` deadline so a request cannot wait
through a long outage and actuate unexpectedly after reconnection.

```json
{
  "command_id": 42,
  "command_type": "FEED_NOW",
  "payload_json": "{\"duration_ms\":1000}",
  "expires_at": "2026-07-11T12:35:30Z",
  "signature": "5e508b65506a280503c153d1ac72327210d5e59856f258d4d8983c4d2f72aba5"
}
```

That signature is HMAC-SHA256 of this exact canonical UTF-8 text:

```text
42|FEED_NOW|{"duration_ms":1000}|2026-07-11T12:35:30Z
```

The example uses `local-development-mqtt-secret`. The bridge normalizes API
timestamps to explicit UTC before publishing and signs the exact transmitted
expiry. The ESP32 rejects malformed or expired values before actuation and
publishes the signed terminal result `FAILED / command_expired`. Legacy local
commands without an expiry keep the original three-field canonical format.

Supported commands:

| Type | `payload_json` | Completion behavior |
| --- | --- | --- |
| `FEED_NOW` | `{}`, `{"duration_ms":1000}`, or `{"schedule_id":7}` | Completes only after forward feeding, the wait, and reverse cleaning finish |
| `CLEAN_PUMP` | `{}` or `{"duration_ms":1000}` | Completes only after reverse cleaning finishes |
| `SET_COOLING` | `{"enabled":true}`, `{"enabled":false}`, or `{"mode":"AUTO"}` | Completes after the output mode is applied |
| `SYNC_SCHEDULES` | `{"schedules":[...]}` | Atomically replaces the non-actuating schedule mirror; the server remains the only scheduler |

Pump durations must be between 500 and 60,000 milliseconds. Forced cooling-on
is rejected when the temperature sensor is unavailable. `AUTO`, `FORCED_ON`,
and `FORCED_OFF` are also accepted as explicit cooling modes.

The schedule-sync payload accepts up to eight schedules. IDs must be positive,
hours/minutes valid, timezone absent or a string, and `days_of_week` either a
backend string such as `"0,1,2,3,4"` or an array such as `[0,1,2,3,4]`.
Weekdays follow Python/backend numbering: Monday is 0 and Sunday is 6. An empty
array clears the device schedule mirror. The device stores these operational
fields, while timezone-aware due-time calculation remains on the backend.
Example inner payload:

```json
{"schedules":[{"id":7,"hour":8,"minute":0,"days_of_week":"0,1,2,3,4","timezone":"UTC","enabled":true}]}
```

When the bridge dispatches `FEED_NOW` with `{"schedule_id":7}`, its
`scheduled_feeding` telemetry includes `"schedule_id": 7`, allowing the
backend to link the device event to the stored schedule and feeding execution.
Without that field, the same command emits `manual_feeding` and a null schedule
ID.

The device publishes terminal outcomes to:

```text
fish-feeder/feeder-001/command-results
```

```json
{
  "device_uid": "feeder-001",
  "command_id": 42,
  "status": "COMPLETED",
  "result": "feeding_and_cleaning_completed",
  "signature": "ca3b9b0363a01faf0f352d490b40925cdb48192711b7b7570e662b7a4e85dd4a"
}
```

The result signature canonical is:

```text
42|COMPLETED|feeding_and_cleaning_completed
```

No completion is published merely because `FEED_NOW` or `CLEAN_PUMP` was
accepted. Sensor aborts produce a signed `FAILED` result at the abort point.
Before parsing a verified command into an operation, firmware writes its ID to
ESP32 Preferences/NVS as `cmd_watermark`. Physical actuation happens only after
that write succeeds. Any later command ID at or below the persisted watermark
is blocked, including a command interrupted by power loss and redelivered after
restart. If its exact outcome is no longer in RAM, the device publishes:

```json
{"status":"FAILED","result":"replay_after_restart_blocked"}
```

This lets the backend terminate the claimed command without falsely reporting
that an interrupted pump cycle completed. If NVS cannot be opened or written,
new commands fail with `command_watermark_persist_failed` and no command-driven
output changes. Within the same boot, the most recent 16 exact command IDs cache
their true terminal results: an in-progress duplicate is ignored and a recent
completed duplicate republishes its cached outcome.

Sequence numbers use NTP-synchronized UTC microseconds and are clamped to remain
strictly increasing inside a running session. This avoids relying on simulated
flash persistence between Wokwi runs. The timestamp-derived sequence and
per-boot nonce make each idempotency key stable for a queued message and unique
across restarts. Short MQTT outages retain up to 12 state-change snapshots in
RAM; disposable heartbeats are not backlogged.

## Demo limitations

- The public broker is shared and plaintext. Payload HMAC prevents parties that
  do not know the shared secret from injecting accepted telemetry, but it does
  not encrypt readings or topic names. Replace the documented development
  secret, choose a unique `FEEDER_DEVICE_UID`, and use TLS plus broker
  credentials in a deployment.
- PubSubClient publishes at MQTT QoS 0. Backend idempotency still protects the
  bridge's HTTP retries, but an MQTT packet can be lost.
- The RAM queue does not survive power loss. A production device should persist
  important feeding events and terminal result bodies in flash or an embedded
  database and replay them after reconnecting. The NVS command watermark does
  survive, so a lost result cannot cause repeated physical actuation.
- Each newly accepted command writes one NVS watermark. High-frequency command
  workloads should use wear-levelled storage or reserve ID ranges to reduce
  flash wear.
- The LEDs visualize control signals; they do not model pump current, motor
  faults, or Peltier electrical behavior.
