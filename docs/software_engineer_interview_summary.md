# Smart Fish Feeder interview summary

## Brief answer

I built the Smart Fish Feeder because I keep reef aquariums and could not find an affordable product that handled liquid food the way I needed. The food has to stay cool, feeding has to work when nobody is home, and the pump line should be cleaned after each cycle. Other hobbyists around me had the same problem, so I built 10 additional units for them. My original unit is still in service.

I designed the physical feeder around an ESP32, a temperature sensor, a cooling output, and a reversible pump. I also built the cloud side: a FastAPI service, SQLite database, MQTT messaging, browser dashboard, device onboarding, and a Docker deployment on a public VPS. A user can monitor temperature, schedule feedings, send a Feed Now command, and see the signed completion result from the device.

The hardest part was making remote physical actions safe under retries, disconnects, and reboots. I added short-lived HMAC-signed commands, idempotency, event ordering, and ESP32 replay protection. I also addressed SQLite lock contention with WAL mode, a busy timeout, shorter transactions, and bounded retries. The repository now has 91 Python tests, 34 dashboard tests, and browser-to-Wokwi closed-loop validation.

## Complete project summary

### Why I built it

I started this project to solve a problem in my own reef aquarium. Liquid food needs refrigeration, but feeding also needs to happen consistently when I am away. A normal automatic feeder handles dry food, not a chilled liquid reservoir and a pump line that can retain food after dispensing. At the time, I could not find an affordable product that combined those needs.

My first goal was practical: build a feeder I could rely on at home. Once the physical prototype worked, I saw that the harder problem was not merely turning on a pump. An unattended device needs to report what happened, reject unsafe or repeated instructions, recover from network failures, and give the owner enough information to decide whether a feeding actually completed. That led me to build the cloud control platform around the feeder.

### Who used it and what problem it solved

The original unit remains in service on my aquarium. I also built and delivered 10 additional units to other hobbyists who had a similar need for refrigerated, unattended liquid feeding. This was not a hypothetical portfolio prompt. The requirements came from a problem I experienced and from conversations with people using the same kind of aquarium setup.

In practice, owners needed more than a timer. The feeder tracks the reservoir temperature, runs scheduled or manual feedings, and reverses the pump afterward to clear the line. The website lets the owner check the outcome remotely instead of assuming the feeding happened.

### What I owned

I owned the project from the physical prototype through production deployment. On the device side, I wrote the ESP32 behavior for temperature sensing, pump direction, cooling, local input, network provisioning, and persistent replay state. On the cloud side, I designed the API and data model, connected the device through an MQTT bridge, built the account and ownership flows, and shipped the dashboard and containers to a VPS.

I also handled the operational work that is easy to leave out of a prototype: per-device credentials, customer email flows, one-time claims, monitoring, backup validation, manufacturing output, and commissioning documentation. Working across those boundaries made me treat firmware, cloud software, and operations as one system rather than as separate demos.

### How the system works

The ESP32 reads the reservoir temperature and controls a reversible pump and cooling output. In automatic mode, the firmware uses temperature hysteresis so the cooling output does not rapidly switch near a threshold. A feeding cycle runs the pump forward, pauses, reverses it to clean the tube, and then returns to idle. A separate command can run only the reverse cleaning cycle.

The web application is a modular FastAPI service backed by SQLAlchemy, Alembic, and SQLite. It stores users, device ownership, telemetry, schedules, feeding executions, alerts, commands, and audit history. The browser dashboard displays live state and temperature history, supports recurring schedules in a chosen timezone, and exposes manual feed, cleaning, and cooling controls only when the selected device is online.

MQTT separates intermittent device connectivity from the request and database layers. Mosquitto handles device messaging, while a bridge translates signed MQTT payloads into authenticated API calls. Docker Compose runs the dashboard, backend, migration process, broker, and bridge. Traefik provides HTTPS and MQTT over TLS on the public VPS.

### Command and telemetry flow

When a user selects Feed Now, the browser sends an authenticated HTTPS request with an idempotency key. The backend validates the duration and device ownership, checks that the device is online, creates a durable command record, and assigns a short expiration time. The MQTT bridge claims pending work and publishes a signed command to that device's restricted topic.

Before moving hardware, the ESP32 verifies the HMAC signature, expiration time, and monotonic command ID. It persists the accepted command watermark in NVS before actuation. After the pump cycle finishes, the device publishes a signed result. The bridge sends that result to FastAPI, the command changes from pending or claimed to completed or failed, and the dashboard shows the terminal state.

Telemetry follows the reverse path. The ESP32 publishes signed temperature, pump, cooling, and heartbeat events. The backend validates the timestamp and monotonic sequence before storing an event. This prevents an old or out-of-order reading from replacing newer device state. If connectivity drops, the device uses a bounded queue and retries results after reconnecting.

### Security and physical safety

The main security question was how to make a cloud request trustworthy without assuming that TLS alone solved message integrity. Each device has its own API, MQTT, and HMAC credentials. MQTT traffic uses TLS, per-device topic access controls, and HMAC-SHA256 signatures for commands, telemetry, and results. Long-term secrets are not placed in the customer-facing QR code. The code contains only an expiring, one-time proof used to claim a factory-provisioned device.

I designed command handling around the fact that MQTT QoS 1 and HTTP retries can deliver the same logical request more than once. The API uses idempotency keys, commands expire, result submission is idempotent, and the ESP32 stores a monotonic watermark in NVS. A reconnect or reboot therefore cannot turn a stale redelivery into a second physical feeding.

Software checks also limit the physical action. The UI and API validate pump durations, require confirmation, and disable controls when the device is offline. Commands are short-lived and non-retained. Sensor failure disables automatic cooling and creates an alert. These controls reduce software-related risk, but they do not replace electrical protection, safe drivers, fuses, or supervised hardware commissioning.

### The SQLite concurrency problem

SQLite was a reasonable choice for a single-VPS system at its current scale. It keeps deployment and backup simple, but the workload is not purely sequential. Telemetry writes, command claims, schedule scans, and dashboard reads can overlap. Under that pattern, long write transactions can cause `database is locked` failures.

I treated this as a concurrency design issue instead of hiding the exception. I enabled WAL mode so reads can continue during a write, configured a 10-second busy timeout, shortened write transactions, made empty command polls read-only, and added bounded retries for temporary lock conflicts. I then added concurrent tests that combine telemetry ingestion, command claiming, and dashboard queries. During the recorded post-deployment observation, the logs showed no database-lock errors, retry exhaustion, or HTTP 5xx responses.

The lesson was that a small database still needs deliberate transaction boundaries. SQLite fits this deployment, but I would move to PostgreSQL before supporting a large multi-tenant workload or multiple application hosts.

### Testing and CI

The test strategy follows the risks in the system. The current suite has 91 Python tests and 34 dashboard tests. Backend tests cover API behavior, alert rules, account onboarding, device claims and transfers, migrations, MQTT signatures, replay handling, database concurrency, monitoring, backup verification, and the virtual device lifecycle. Frontend tests cover live data, demo behavior, onboarding, scheduling, empty states, and API failures.

I also use Wokwi as virtual ESP32 hardware. The browser-to-Wokwi closed-loop test starts the application stack, submits Feed Now through the dashboard, checks the simulated GPIO sequence, validates the signed device result, and confirms that the command reaches a completed state. This does not replace testing a physical pump, but it catches integration problems across the browser, API, database, bridge, broker, and firmware.

GitHub Actions runs six jobs for backend quality, frontend checks, firmware, closed-loop validation, dependency security, and containers. The pipeline includes formatting, linting, strict type checking, tests, dependency audits, firmware compilation, Docker configuration checks, image builds, and an end-to-end Compose smoke test. The current measured coverage is 91.23 percent for Python and 84.53 percent for dashboard lines.

### Production deployment and operations

I deployed the control board to a public Linux VPS using Docker Compose and Traefik. Public traffic is limited to HTTPS and authenticated MQTT over TLS. The backend, database, bridge, dashboard service, and plaintext broker listener stay on private Docker networks. Environment files hold production configuration and are kept out of source control.

The production monitor runs every five minutes. It checks the website, API, MQTT certificate, Resend SMTP authentication, Compose service health, recent backend failures, database lock messages, email delivery errors, and offline customer devices. Notifications are based on state transitions, so a new failure sends immediately, an unchanged failure repeats after an hour, and a recovery sends once.

For recovery, I built a drill that copies a SQLite backup into an isolated temporary directory, upgrades the copy to the current Alembic revision, and checks integrity, foreign keys, schema version, important row counts, and a rolled-back write probe. It produces an evidence report without opening or modifying the production database. I still treat broker state, TLS certificate state, and production secrets as separate recovery assets.

### Results, limitations, and lessons

The original feeder remains in use, and I built and delivered 10 more units to other hobbyists. As I moved from that first prototype to the cloud control system, I kept asking what could go wrong when a physical action depends on networked software. That question led to the command history, signed device path, schedules, alerts, monitoring, and recovery checks.

The project does not contain an AI feature, and I would not add one only to make the stack sound more current. The core problem is deterministic control and reliability. A future prediction feature would need a clear user benefit, suitable data, and a safe boundary that prevents a model output from directly controlling hardware.

There are also honest limits. The system has not been independently safety certified. Wokwi validates firmware and integration behavior, not real voltage, current, tubing, food handling, or mechanical wear. Final acceptance of each physical unit still depends on the documented commissioning checklist and supervised hardware tests. SQLite also limits how far I would scale the current architecture without changing the database layer.

The most important lesson was to define success as a verified outcome, not a successful API request. For a physical system, `200 OK` means the server accepted work. It does not mean the pump moved. That distinction shaped the command state machine, signed terminal results, dashboard history, alerts, and tests.

### What I would build next

My next step is to complete the documented first-unit acceptance flow on the real ESP32 hardware. That includes SoftAP Wi-Fi setup, QR claim, verified MQTT/TLS connection, live telemetry, GPIO actuation, signed completion, disconnect recovery, reboot replay tests, and a provisioning reset.

After physical acceptance, I would improve maintainability before adding broad features. I would automate credential rotation during device servicing, test full recovery of every production asset, and define the threshold for migrating from SQLite to PostgreSQL. If the number of deployed devices grows, I would also separate background scheduling and message processing from the API process and add device fleet metrics.

## Behavioral interview map

| Question | Best example | Point to emphasize |
| --- | --- | --- |
| Tell me about something you built. | The complete feeder, from the ESP32 and pump through the public control board | I started with a real hobbyist problem, owned the system end to end, and delivered 10 additional units. |
| Tell me about a difficult technical problem. | Reliable cloud commands across retries, disconnects, and reboots | A successful request was not enough. I designed a command lifecycle with signatures, expiration, idempotency, durable state, and device results. |
| Tell me about a time you worked through ambiguity. | Turning a working physical prototype into a remotely operated product | I translated unclear expectations such as "feed reliably" into explicit states, failure cases, alerts, and acceptance tests. |
| Tell me about a failure or risk you prevented. | Preventing duplicate physical actuation | MQTT and HTTP may redeliver messages, so I combined idempotency keys with an ESP32 NVS watermark that survives reboot. |
| Tell me about a security trade-off. | One-time device claims without exposing long-term credentials | The QR stays convenient for a customer, but it contains only an expiring proof. Device API, MQTT, and HMAC secrets remain private. |
| Tell me about a time you improved reliability. | Fixing SQLite lock contention | I identified overlapping writers, changed transaction behavior, added WAL, timeout, and bounded retries, then verified the behavior with concurrency tests and production logs. |
| Tell me about user feedback or impact. | My own long-term use and 10 units delivered to other hobbyists | The project solved a shared practical need. I should describe what users needed without inventing adoption or revenue metrics. |
| Tell me about something you would do differently. | Choosing the database and defining hardware acceptance earlier | SQLite was appropriate for one VPS, but I would set migration thresholds earlier and create the physical acceptance checklist sooner. |
