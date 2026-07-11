# Resume bullets

Use only metrics supported by the current repository and CI results.

## Backend / platform version

- Built an authenticated IoT operations platform with FastAPI, SQLAlchemy, Alembic, MQTT, and Docker Compose, modeling devices, ordered telemetry, feeding schedules and executions, durable alerts, and remote commands.
- Implemented per-device credential hashing, Argon2/JWT operator authentication, idempotent ingestion, event-order validation, rate limiting, heartbeat monitoring, and automated missed-feeding detection.
- Added 42 backend tests plus frontend state tests and GitHub Actions gates for strict typing, linting, dependency audits, firmware compilation, container builds, and a full-stack MQTT/API/dashboard smoke test.

## Embedded / IoT version

- Upgraded a physical Arduino liquid-feeder prototype into an ESP32/Wokwi digital twin that publishes DS18B20 readings and nonblocking feed/reverse-clean state transitions through MQTT.
- Designed reconnect and buffering behavior with full-payload HMAC authentication, monotonic sequences, idempotency keys, UTC event timestamps, explicit sensor-failure payloads, a bounded in-memory event queue, and NVS-backed command replay protection.
