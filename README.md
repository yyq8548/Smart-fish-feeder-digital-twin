# Smart Fish Feeder Physical Control Board

[![CI](https://github.com/yyq8548/Smart-fish-feeder-digital-control/actions/workflows/ci.yml/badge.svg)](https://github.com/yyq8548/Smart-fish-feeder-digital-control/actions/workflows/ci.yml)
![Backend coverage](https://img.shields.io/badge/backend%20coverage-92%25-brightgreen)
![Frontend line coverage](https://img.shields.io/badge/frontend%20line%20coverage-95%25-brightgreen)

An authenticated online control board for monitoring and operating a physical ESP32 fish feeder. Operators can view live reservoir telemetry, feed fish, reverse-clean the pump, change cooling behavior, investigate alerts, and confirm the result of every device command from a browser.

The dashboard is not a disconnected mockup. Each control creates a durable backend command that is signed, delivered over MQTT/TLS, checked by the ESP32, executed through GPIO-connected hardware, and reported back to the dashboard.

## Control-board demo

### Live physical-device status

The selected feeder reports its temperature, cooling output, pump state, connection status, and recent telemetry to the control board.

![Authenticated control board showing a connected feeder](docs/images/control-board-overview.png)

### Physical controls and command results

`Feed now`, `Clean pump`, and cooling-mode controls are enabled only while the selected device is online. The audit trail shows commands that the device claimed and completed.

![Physical controls and completed command history](docs/images/control-board-demo.png)

Additional demos:

- [Original physical feeder prototype](https://drive.google.com/file/d/1-BNHRS8WrIlX6UmlVeAYz3xfRProdbw3/view?usp=sharing)
- [Original Arduino/Wokwi simulation](https://wokwi.com/projects/468425567572330497)
- [ESP32 MQTT simulation instructions](simulation/esp32-mqtt/README.md)

## What the control board operates

| Dashboard action | Cloud command | ESP32 physical behavior | Reported result |
| --- | --- | --- | --- |
| Feed now | `FEED_NOW` | Runs the pump forward, pauses, then reverses it to clean the tube | Completed or failed feeding cycle |
| Clean pump | `CLEAN_PUMP` | Runs the peristaltic pump in reverse | Completed or failed cleaning cycle |
| Automatic cooling | `SET_COOLING: AUTO` | Uses the 3–5°C temperature hysteresis | Active automatic mode |
| Force cooling on | `SET_COOLING: FORCED_ON` | Activates the cooling driver | Output enabled |
| Force cooling off | `SET_COOLING: FORCED_OFF` | Deactivates the cooling driver | Output disabled |

The ESP32 firmware maps those actions to the physical feeder:

| ESP32 pin | Connected component | Purpose |
| --- | --- | --- |
| GPIO 4 | DS18B20 | Reservoir temperature |
| GPIO 18 | Local feed button | Offline/manual feed input |
| GPIO 25 | Cooling driver | Peltier or cooling relay control |
| GPIO 26 | Pump driver forward | Dispense direction |
| GPIO 27 | Pump driver reverse | Tube-cleaning direction |
| GPIO 33 | Pump enable | Motor-driver enable |

See the [complete wiring guide](docs/wiring.md#networked-esp32-control-wiring) before connecting powered hardware.

## Physical-to-cloud command path

```text
Operator browser
    |
    | HTTPS + short-lived JWT
    v
FastAPI control service -----> SQLite command and audit records
    |
    | pending command
    v
MQTT bridge -----> Mosquitto TLS broker -----> ESP32
                                              |
                                              | GPIO
                                              v
                              Pump, cooling driver, sensor

ESP32 ---- signed telemetry and result ----> MQTT bridge ----> FastAPI
                                                              |
                                                              v
                                                       Updated dashboard
```

Commands are short-lived and non-retained. The ESP32 verifies their HMAC-SHA256 signature, expiry time, and monotonic command ID before operating the hardware. It stores the accepted command watermark in NVS so a reboot cannot replay an old feed instruction.

## Safety behavior

- Manual actuator controls are disabled when the device is offline.
- Every physical command requires operator confirmation.
- Feed and clean durations are limited to 500–60,000 ms by both the dashboard and API.
- Manual commands expire after 45 seconds by default instead of waiting indefinitely for a disconnected device.
- MQTT commands use QoS 1 but are not retained by the broker.
- Duplicate telemetry and commands are safe through idempotency and replay protection.
- Invalid signatures, stale timestamps, expired commands, and out-of-order events are rejected.
- Sensor failure turns automatic cooling off and generates an alert.
- The physical feed button remains available without the cloud dashboard.

Software safeguards do not replace electrical protection, motor-current limits, fuses, isolation, or supervised physical commissioning.

## Run the complete local demo

Requirements: Docker with Compose v2.

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Control board: <http://localhost:8080>
- FastAPI: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>

The default local operator is:

```text
username: admin
password: local-development-admin-password
```

These credentials and the anonymous loopback MQTT configuration are only for a local demonstration. Never expose the development Compose profile to a network or connect production hardware with its default secrets.

Run the same end-to-end smoke test used by CI:

```bash
bash scripts/compose-smoke.sh
```

## Connect a physical ESP32

1. Copy `firmware/esp32_mqtt/feeder_secrets.example.h` to `firmware/esp32_mqtt/feeder_secrets.h`.
2. Configure Wi-Fi, MQTT hostname, port `8883`, device username/password, root CA, device UID, and shared signing secret.
3. Deploy the production cloud stack and provision the matching device credentials.
4. Compile and flash `firmware/esp32_mqtt/esp32_mqtt.ino`.
5. Commission the sensor first, then low-voltage outputs, and finally the unloaded pump/cooling hardware.
6. Confirm telemetry appears before enabling any dashboard actuator.
7. Test each control with the mechanism unloaded and supervised.

Follow the [physical commissioning checklist](docs/physical_commissioning.md) for the required firmware-first upgrade order and failure tests.

## Run the dashboard-to-ESP32 closed loop

The optional closed-loop test proves the entire control path with the real
dashboard and firmware instead of synthesizing either side:

```text
Chromium dashboard -> FastAPI -> MQTT bridge -> verified MQTT TLS
  -> Wokwi ESP32 GPIO -> signed result -> FastAPI -> dashboard
```

It creates a unique device UID and random HMAC/API credentials, builds and
starts the complete Compose stack, compiles the ESP32 firmware with certificate
and hostname verification, runs Wokwi concurrently, and submits a 500 ms
`FEED_NOW` from Chromium. Wokwi asserts forward-pump, safety-pause,
reverse-clean, and final-idle GPIO states. The browser asserts that the command
was accepted as `PENDING` and later renders `COMPLETED` with
`feeding_and_cleaning_completed` after the bridge validates the signed result.

Prerequisites are Docker, Arduino CLI with the ESP32 core and libraries, pnpm
with the Playwright Chromium browser, Wokwi CLI, and `WOKWI_CLI_TOKEN`:

```bash
bash scripts/wokwi-closed-loop.sh
```

The default test transport is `broker.hivemq.com:8883` with the Amazon root CA,
TLS 1.2+, certificate/hostname verification, unique per-run topics, and HMAC
authentication for every application message. This public test broker does not
provide private topic ACLs, so it is not a production substitute. To use an
internet-reachable authenticated broker, set `WOKWI_E2E_MQTT_HOST`,
`WOKWI_E2E_MQTT_PORT`, `WOKWI_E2E_MQTT_USERNAME`,
`WOKWI_E2E_MQTT_PASSWORD`, and `WOKWI_E2E_MQTT_ROOT_CA_FILE`.

## Production cloud deployment

The production profile places the control board and API behind HTTPS and exposes only the authenticated MQTT/TLS listener on port `8883`. Backend, dashboard, bridge, database, and plaintext broker traffic stay on private Docker networks.

```bash
cp .env.production.example .env.production
chmod 600 .env.production

docker compose \
  --env-file .env.production \
  -f docker-compose.production.yml \
  config --quiet

docker compose \
  --env-file .env.production \
  -f docker-compose.production.yml \
  up -d --build
```

Before deployment, replace every placeholder with unique high-entropy values, configure the dashboard and MQTT DNS records, and follow the [single-VPS cloud deployment guide](docs/cloud_deployment.md).

## Main capabilities

### Device monitoring

- Ordered temperature, cooling, pump, sensor-health, and heartbeat telemetry
- Live online/offline state and last-seen time
- Local canvas temperature chart without third-party browser scripts
- Durable temperature, sensor, pump, offline, and missed-feeding alerts
- Operator alert acknowledgement and operational history

### Remote operation

- Immediate feeding and reverse-pump cleaning
- Automatic, forced-on, and forced-off cooling modes
- IANA-timezone feeding schedules and missed-feeding detection
- Pending, claimed, completed, failed, and expired command states
- Device command leases, completion grace periods, and audit records

### Security and reliability

- Argon2 operator passwords and short-lived JWT sessions
- Per-device API and MQTT credentials
- HMAC-SHA256 telemetry, command, and result signatures
- TLS certificate and hostname verification
- Per-device MQTT topic ACLs
- Rate limiting, timestamp validation, monotonic ordering, and idempotency
- ESP32 NVS replay protection and command-result resend behavior

## Main APIs

| Area | Endpoints |
| --- | --- |
| Authentication | `POST /auth/token`, `GET /users/me` |
| Devices | `POST/GET /devices`, `POST /devices/{uid}/rotate-key` |
| Telemetry | `POST/GET /telemetry`, `GET /device-status` |
| Schedules | `POST/GET /devices/{uid}/schedules`, `PATCH/DELETE /schedules/{id}` |
| Operations | `GET /feeding-executions`, `GET /alerts`, `POST /alerts/{id}/acknowledge` |
| Commands | `POST/GET /devices/{uid}/commands`, `POST /device-commands/claim`, `POST /device-commands/{id}/complete` |
| Reliability | `POST /reliability/scan` plus automatic schedule and offline scanning |

## Automated verification

GitHub Actions runs the following on every pull request:

- Ruff formatting and linting
- Strict mypy type checking
- 66 Python backend, MQTT transport, and Wokwi contract tests
- 20 dashboard tests with API failure and empty-state coverage
- Browser-driven dashboard-to-Wokwi closed-loop verification
- Python and JavaScript dependency vulnerability audits
- Plaintext and verified-TLS ESP32 firmware compilation
- Wokwi sensor, hysteresis, and pump-cycle simulation when the CI token is configured
- Development and production Docker configuration validation
- Complete Docker Compose build and end-to-end smoke test

Current measured coverage is 91.57% for the Python backend and 94.63% line coverage for the dashboard.

## Repository map

```text
backend/                       FastAPI service, database, migrations, tests
dashboard/                     Browser control board and frontend tests
firmware/esp32_mqtt/           Physical ESP32 MQTT/TLS firmware
firmware/sketch.ino            Preserved original Arduino Mega prototype
mock_device/                   Device simulator and MQTT-to-HTTP bridge
simulation/esp32-mqtt/         Wokwi ESP32 setup
deploy/                        Production proxy, broker, ACL, and health files
docs/cloud_deployment.md       VPS, DNS, TLS, secrets, and operations guide
docs/wiring.md                 ESP32-to-hardware wiring map
docs/physical_commissioning.md Safe physical bring-up procedure
docker-compose.yml             Complete local demonstration stack
docker-compose.production.yml  HTTPS and MQTT/TLS production stack
```

