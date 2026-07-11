# Firmware

This directory keeps both generations of the feeder firmware:

| Path | Target | Purpose |
| --- | --- | --- |
| `sketch.ino` | Arduino Mega | Original physical-prototype state machine with DS1307 scheduling |
| `esp32_mqtt/esp32_mqtt.ino` | ESP32 DevKit v1 | Networked digital-twin device used by the Wokwi MQTT simulation |

The original Mega sketch is intentionally preserved as evidence of the hardware
prototype. The ESP32 sketch is the active IoT path. It reads the DS18B20,
controls cooling with 3-5 C hysteresis, runs nonblocking feed/clean cycles, and
publishes state changes plus heartbeats to:

```text
fish-feeder/<device_uid>/telemetry
```

It also subscribes to signed commands and publishes signed terminal results:

```text
fish-feeder/<device_uid>/commands
fish-feeder/<device_uid>/command-results
```

Each JSON message includes `device_uid`, `sequence_number`,
`idempotency_key`, `recorded_at`, `temperature_c`, `cooling_on`,
`pump_state`, `sensor_status`, `event_type`, and `signature`. `pump_state` is
always one of the backend's accepted values: `IDLE`, `FEEDING`, `CLEANING`, or
`ERROR`. Invalid or disconnected sensors emit a null temperature with an
explicit error status instead of inventing a measurement.

The ESP32 authenticates every telemetry value with an mbedTLS HMAC-SHA256 over
a versioned UTF-8 canonical record. It begins with the literal version header,
then uses the following fixed field order:

```text
fish-feeder-telemetry-v1
device_uid:<byte_length>:<value>
sequence_number:<byte_length>:<value>
idempotency_key:<byte_length>:<value>
recorded_at:<byte_length>:<value>
temperature_mdeg:<byte_length>:<value>
cooling_on:<byte_length>:<value>
pump_state:<byte_length>:<value>
sensor_status:<byte_length>:<value>
event_type:<byte_length>:<value>
schedule_id:<byte_length>:<value>
```

Fields are separated by one LF byte (`\n`), and there is no trailing LF. Length
is the decimal number of bytes in the UTF-8 value, not its character count.
Temperature is a signed integer number of millidegrees Celsius, rounded to the
nearest millidegree with half values away from zero, or the literal `null`.
Firmware publishes `temperature_c` from this same quantized integer. Boolean is
`0` or `1`; absent `event_type` and `schedule_id` are the explicit four-byte
value `null`. All integers use base-10 without leading zeros. The `signature`
field itself is excluded.

`signature` is the resulting 32-byte digest encoded as 64 lowercase hexadecimal
characters. The bridge must use the same `FEEDER_MQTT_SHARED_SECRET`, reproduce
this record byte-for-byte, and compare signatures in constant time before
forwarding telemetry.

The command plane supports `FEED_NOW`, `CLEAN_PUMP`, `SET_COOLING`, and the
optional configuration-mirror command `SYNC_SCHEDULES`. Command signatures cover
`command_id|command_type|payload_json`; result signatures cover
`command_id|status|result`. Feed and clean commands remain in progress until
the state machine actually finishes or aborts. Before executing any accepted
command, the ESP32 persists its monotonically increasing ID as an NVS watermark.
An ID at or below that watermark can never actuate after a reboot. A 16-entry
RAM terminal-result cache still republishes exact recent outcomes during the
same boot; older/post-restart replays receive a signed terminal failure so the
backend can close its command lease honestly.

Schedules can be cached atomically at runtime by `SYNC_SCHEDULES` as a
non-actuating mirror of backend IDs, times, enabled state, and Python weekday
sets (Monday=0). The backend remains authoritative for timezone-aware due-time
calculation and is the only scheduler: it dispatches `FEED_NOW` with a positive
`schedule_id`, and firmware emits `scheduled_feeding` telemetry with that same
ID. A `FEED_NOW` without `schedule_id` remains a manual execution.

Configuration uses `FEEDER_*` compile-time constants. Defaults target Wokwi's
open `Wokwi-GUEST` network and a public demonstration broker. For physical
hardware, override the WiFi and MQTT values with build flags or a local secrets
header that is excluded from version control; do not commit credentials. The
included shared secret is for local development only and must be replaced with
a unique high-entropy value before connecting through a public broker.

See [`../simulation/esp32-mqtt/README.md`](../simulation/esp32-mqtt/README.md)
for the complete Wokwi-to-backend walkthrough.
