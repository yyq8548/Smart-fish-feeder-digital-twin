# Smart Fish Feeder Cloud Control Board

[![CI](https://github.com/yyq8548/Smart-fish-feeder-digital-control/actions/workflows/ci.yml/badge.svg)](https://github.com/yyq8548/Smart-fish-feeder-digital-control/actions/workflows/ci.yml)
![Backend coverage](https://img.shields.io/badge/backend%20coverage-92%25-brightgreen)
![Frontend line coverage](https://img.shields.io/badge/frontend%20line%20coverage-95%25-brightgreen)
![ESP32](https://img.shields.io/badge/device-ESP32-blue)
![MQTT TLS](https://img.shields.io/badge/MQTT-TLS%201.2%2B-success)

An online control board for monitoring and operating a physical ESP32 fish feeder from a browser. It combines a responsive dashboard, FastAPI backend, persistent database, authenticated MQTT broker, ESP32 firmware, automated testing, and a production Docker deployment.

The dashboard is not a disconnected mockup. A control request becomes a durable backend command, travels to the feeder over MQTT/TLS, actuates GPIO-connected hardware, and returns a signed completion result to the website.

## Live website

**Control board:** [https://feeder.smartfishfeeder.org](https://feeder.smartfishfeeder.org)

The public website requires an operator account. Production usernames, passwords, device credentials, and signing secrets are intentionally not stored in this repository.

| Service | Address | Purpose |
| --- | --- | --- |
| Web control board | `https://feeder.smartfishfeeder.org` | Operator monitoring and physical-device controls |
| Health check | `https://feeder.smartfishfeeder.org/health` | Dashboard availability |
| Backend API | `https://feeder.smartfishfeeder.org/api` | Authenticated application API |
| ESP32 broker | `mqtt.smartfishfeeder.org:8883` | Authenticated MQTT over TLS |

![Authenticated control board showing the selected feeder](docs/images/control-board-overview.png)

The dashboard shows the selected feeder's temperature, cooling output, pump state, last accepted event, recent telemetry, alerts, and command history.

![Physical controls and completed command history](docs/images/control-board-demo.png)

## Website user manual

### 1. Sign in

1. Open [the live control board](https://feeder.smartfishfeeder.org).
2. Enter the operator username and password supplied by the system owner.
3. Select **Sign in**.
4. Confirm that the header changes from **Sign In Required** to the current system state.

The browser exchanges the credentials for a short-lived access token. The token is kept only in the current browser tab and is removed when the operator signs out.

### 2. Select a feeder

Use **Selected device** to choose the feeder you want to monitor or operate. Every metric, chart, alert, command, and history entry on the page is filtered to that device.

Always verify the selected device UID before issuing a physical command.

### 3. Check device status

Review the four status cards before operating the feeder:

| Card | Meaning |
| --- | --- |
| Reservoir Temperature | Latest accepted DS18B20 reading |
| Cooling | Current cooling output state |
| Pump State | `IDLE`, `FEEDING`, `CLEANING`, or `ERROR` |
| Last Seen | Time of the latest accepted device event |

The **Temperature History** chart shows recent ordered telemetry. An offline banner or stale **Last Seen** value means actuator controls will remain disabled.

### 4. Feed now

1. Confirm that the selected device is online and its pump state is `IDLE`.
2. Enter a feed duration between `500` and `60,000` milliseconds.
3. Select **Feed now**.
4. Read the confirmation dialog carefully and approve it.
5. Watch **Command history** for the final result.

The ESP32 runs the pump forward to dispense food, pauses for safety, reverses the pump to clean the tube, and then returns to idle.

### 5. Clean the pump

1. Confirm that the mechanism can operate safely.
2. Enter a cleaning duration between `500` and `60,000` milliseconds.
3. Select **Clean pump** and approve the confirmation dialog.
4. Wait for a terminal command result before sending another pump command.

The cleaning command operates the pump in reverse without running a complete feeding cycle.

### 6. Change cooling mode

Choose one of the following controls and confirm the request:

| Website control | Behavior |
| --- | --- |
| Automatic | ESP32 manages cooling with the configured temperature hysteresis |
| Force on | Enables the cooling output continuously |
| Force off | Disables the cooling output continuously |

Use forced modes only for supervised operation. Return the device to **Automatic** for normal unattended temperature control.

### 7. Read command history

Every accepted request is recorded with its command type, creation time, expiration time, status, and device result.

| Status | Meaning |
| --- | --- |
| `PENDING` | Stored by the cloud and waiting for the device |
| `CLAIMED` | Delivered to and accepted by the device |
| `COMPLETED` | Physical operation finished successfully |
| `FAILED` | Device rejected or could not complete the operation |
| `EXPIRED` | Device did not claim the command before its deadline |

Do not assume that an accepted command completed. Wait for `COMPLETED` and read the result text.

### 8. Review alerts

The **Recent alerts** panel displays temperature, sensor, pump, offline, and missed-feeding incidents. Check the timestamp, severity, category, and message before taking action. Resolve the physical cause before repeating a failed command.

### 9. Sign out

Select **Sign out** when finished, especially on a shared computer. Closing the browser tab also removes the in-tab session token.

## What the website controls

| Dashboard action | Cloud command | ESP32 behavior | Expected result |
| --- | --- | --- | --- |
| Feed now | `FEED_NOW` | Pump forward, safety pause, reverse clean, idle | Completed or failed feeding cycle |
| Clean pump | `CLEAN_PUMP` | Pump reverse for the requested duration | Completed or failed cleaning cycle |
| Automatic cooling | `SET_COOLING: AUTO` | Temperature-controlled cooling | Automatic mode enabled |
| Force cooling on | `SET_COOLING: FORCED_ON` | Cooling driver enabled | Output enabled |
| Force cooling off | `SET_COOLING: FORCED_OFF` | Cooling driver disabled | Output disabled |

The backend also supports timezone-aware feeding schedules, missed-feeding detection, alert acknowledgement, credential rotation, and device provisioning through its authenticated API.

## Connect a physical ESP32

The ESP32 connects directly to the production broker over Wi-Fi; it does not need to remain connected to a computer after flashing.

1. Copy `firmware/esp32_mqtt/feeder_secrets.example.h` to `firmware/esp32_mqtt/feeder_secrets.h`.
2. Add the device's Wi-Fi SSID and password.
3. Set the MQTT host to `mqtt.smartfishfeeder.org` and the port to `8883`.
4. Enable verified TLS and keep insecure TLS disabled.
5. Add the provisioned device UID, MQTT username/password, HMAC shared secret, and appropriate trusted root CA.
6. Compile and flash `firmware/esp32_mqtt/esp32_mqtt.ino`.
7. Commission the sensor first, then low-voltage outputs, and finally unloaded pump and cooling hardware.
8. Confirm that telemetry appears on the website before enabling actuators.
9. Test every command with the mechanism unloaded and supervised.

Never commit `feeder_secrets.h`. Follow the [physical commissioning checklist](docs/physical_commissioning.md) and [wiring guide](docs/wiring.md#networked-esp32-control-wiring) before connecting powered hardware.

### ESP32 pin map

| ESP32 pin | Connected component | Purpose |
| --- | --- | --- |
| GPIO 4 | DS18B20 | Reservoir temperature |
| GPIO 18 | Local feed button | Offline/manual feed input |
| GPIO 25 | Cooling driver | Peltier or cooling relay control |
| GPIO 26 | Pump driver forward | Dispense direction |
| GPIO 27 | Pump driver reverse | Tube-cleaning direction |
| GPIO 33 | Pump enable | Motor-driver enable |

## How a command reaches the feeder

```text
Operator browser
    |
    | HTTPS + short-lived JWT
    v
FastAPI control service -----> SQLite command and audit records
    |
    | signed pending command
    v
MQTT bridge -----> Mosquitto TLS broker -----> ESP32
                                              |
                                              | GPIO
                                              v
                              Pump, cooling driver, sensor

ESP32 ---- signed telemetry and result ----> MQTT bridge ----> FastAPI
                                                              |
                                                              v
                                                       Updated website
```

Commands are short-lived and non-retained. The ESP32 verifies the HMAC-SHA256 signature, expiration time, and monotonic command ID before operating hardware. It stores the accepted-command watermark in NVS so a reboot cannot replay an old feed instruction.

## Safety behavior

- Physical controls are disabled while the selected device is offline.
- Every actuator command requires operator confirmation.
- Feed and cleaning durations are validated by both the website and API.
- Manual commands expire instead of waiting indefinitely for a disconnected device.
- MQTT commands use QoS 1 and are never retained.
- Idempotency and replay protection prevent duplicate actuation.
- Invalid signatures, stale timestamps, expired commands, and out-of-order events are rejected.
- Sensor failure disables automatic cooling and creates an alert.
- The local physical feed button remains available without the website.

Software safeguards do not replace fuses, isolation, current limits, electrical protection, or supervised commissioning.

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

Local demonstration account:

```text
username: admin
password: local-development-admin-password
```

These credentials and the local MQTT settings are for development only. Never expose the development Compose profile to the internet or use its default secrets on physical hardware.

Run the same Compose smoke test used by CI:

```bash
bash scripts/compose-smoke.sh
```

## Run the virtual-hardware closed loop

The Wokwi test proves the complete path with the real dashboard and compiled ESP32 firmware:

```text
Chromium dashboard -> FastAPI -> MQTT bridge -> verified MQTT TLS
  -> Wokwi ESP32 GPIO -> signed result -> FastAPI -> dashboard
```

It submits `FEED_NOW`, verifies the forward-pump, safety-pause, reverse-clean, and final-idle GPIO states, validates the signed device result, and confirms that the website changes from `PENDING` to `COMPLETED`.

Prerequisites include Docker, Arduino CLI with ESP32 support, pnpm, Playwright Chromium, Wokwi CLI, and `WOKWI_CLI_TOKEN`.

```bash
bash scripts/wokwi-closed-loop.sh
```

See the [Wokwi ESP32 guide](simulation/esp32-mqtt/README.md) for setup and broker options.

## Production deployment

The production profile exposes only HTTPS and authenticated MQTT/TLS. The backend, dashboard, bridge, database, and plaintext broker listener remain on private Docker networks.

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

Replace every placeholder with a unique high-entropy value, configure separate dashboard and MQTT DNS records, and follow the [single-VPS deployment guide](docs/cloud_deployment.md).

## Security and reliability

- Argon2 operator password hashing and short-lived JWT sessions
- Per-device API and MQTT credentials
- HMAC-SHA256 telemetry, command, and result signatures
- TLS certificate and hostname verification
- Per-device MQTT topic ACLs
- Rate limiting, timestamp validation, monotonic ordering, and idempotency
- Durable devices, telemetry, schedules, executions, commands, and alerts
- ESP32 NVS replay protection and terminal-result retry behavior
- Alembic database migrations and container health checks

## Automated verification

GitHub Actions runs the following on every pull request:

- Ruff formatting and linting
- Strict mypy type checking
- 66 Python backend, MQTT transport, and Wokwi contract tests
- 20 dashboard tests covering live, empty, and failed API states
- Browser-driven dashboard-to-Wokwi closed-loop verification
- Python and JavaScript dependency vulnerability audits
- Plaintext and verified-TLS ESP32 firmware compilation
- Wokwi sensor, hysteresis, and pump-cycle simulation when its token is configured
- Development and production Docker configuration validation
- Complete Docker Compose build and end-to-end smoke test

Current measured coverage is 91.57% for Python and 94.63% line coverage for the dashboard.

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

## Repository map

```text
backend/                       FastAPI service, database, migrations, tests
dashboard/                     Browser control board and frontend tests
firmware/esp32_mqtt/           Physical ESP32 MQTT/TLS firmware
firmware/sketch.ino            Preserved original Arduino Mega prototype
mock_device/                   Local device simulator and MQTT bridge
simulation/esp32-mqtt/         Wokwi ESP32 virtual hardware
deploy/                        Production proxy, broker, ACL, and health files
docs/cloud_deployment.md       VPS, DNS, TLS, secrets, and operations guide
docs/wiring.md                 ESP32-to-hardware wiring map
docs/physical_commissioning.md Safe physical bring-up procedure
docker-compose.yml             Complete local demonstration stack
docker-compose.production.yml  HTTPS and MQTT/TLS production stack
```

## Additional demonstrations

- [Original physical feeder prototype](https://drive.google.com/file/d/1-BNHRS8WrIlX6UmlVeAYz3xfRProdbw3/view?usp=sharing)
- [Original Arduino/Wokwi simulation](https://wokwi.com/projects/468425567572330497)
- [ESP32 MQTT simulation instructions](simulation/esp32-mqtt/README.md)

