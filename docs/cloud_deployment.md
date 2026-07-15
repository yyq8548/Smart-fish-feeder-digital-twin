# Single-VPS production deployment

This profile deploys the dashboard, API, SQLite database, MQTT bridge, and MQTT
broker on one Linux VPS. Traefik exposes only three public ports:

- `80/tcp` for ACME HTTP challenges and HTTP-to-HTTPS redirects
- `443/tcp` for the HTTPS dashboard and same-origin API under `/api`
- `8883/tcp` for TLS MQTT used by a physical ESP32

Ports `1883`, `8000`, and `8080` remain on private Docker networks. Traefik
terminates public TLS and forwards MQTT to a private Mosquitto listener that
still requires a username/password and topic ACLs. Anonymous MQTT is disabled.

## Prerequisites

Use a maintained Linux VPS with Docker Engine and the Docker Compose v2 plugin.
Before starting the stack:

1. Create DNS `A` records for the dashboard and MQTT hostnames, such as
   `feeder.example.com` and `mqtt.example.com`, pointing to the VPS public IPv4
   address.
2. Create `AAAA` records only when the VPS is reachable over IPv6. A broken
   `AAAA` record commonly prevents certificate issuance and device connections.
3. Allow inbound TCP `80`, `443`, and `8883` in both the cloud firewall and the
   host firewall. Do not open `1883`, `8000`, or `8080`.
4. Ensure no other service is already bound to ports `80`, `443`, or `8883`.
5. Use a real operations email address for Let's Encrypt expiry notices.

Traefik requests and renews certificates automatically through the HTTP-01
challenge. Both DNS names must resolve to this VPS and port `80` must remain
reachable during issuance and renewal.

## Configure secrets

Copy the production template and restrict it to the deployment account:

```bash
cp .env.production.example .env.production
chmod 600 .env.production
git check-ignore --quiet .env.production
```

Replace every placeholder. Generate each secret independently; never reuse a
value between the API key, credential pepper, operator password, JWT secret,
MQTT HMAC secret, bridge password, and device broker password.

```bash
openssl rand -hex 32
```

Run that command once per secret line. The credentials have different roles:

- `FISH_FEEDER_DEVICE_API_KEY` authenticates the bridge to the HTTP ingestion
  and command APIs. The backend stores only its keyed hash.
- `MQTT_SHARED_SECRET` signs telemetry, commands, and command results end to
  end. It is not a broker password.
- `MQTT_DEVICE_PASSWORD` authenticates the physical ESP32 to Mosquitto.
- `MQTT_BRIDGE_PASSWORD` authenticates the server-side bridge to Mosquitto.
- `FISH_FEEDER_CREDENTIAL_PEPPER` protects keyed credential hashes and must be
  backed up with the database.
- `FISH_FEEDER_JWT_SECRET` signs short-lived operator sessions.

`MQTT_DEVICE_USERNAME` must exactly match `DEVICE_UID`. The broker ACL uses the
authenticated username as the topic segment, so `feeder-001` can access only
`fish-feeder/feeder-001/*`. The bridge account is fixed as `bridge` by the
included ACL.

Customer registration also requires a transactional SMTP account. Configure
`FISH_FEEDER_SMTP_HOST`, `FISH_FEEDER_SMTP_PORT`, `FISH_FEEDER_SMTP_USERNAME`,
`FISH_FEEDER_SMTP_PASSWORD`, and `FISH_FEEDER_SMTP_FROM_EMAIL`. Keep
`FISH_FEEDER_EMAIL_DELIVERY_MODE=smtp` in production. The backend builds
verification and password-reset links from `https://DASHBOARD_DOMAIN`; it never
returns those tokens through the public API. If SMTP is missing or unavailable,
registration fails safely instead of creating an account that cannot be
verified.

For the first certificate test, you may temporarily set `ACME_CA_SERVER` to
Let's Encrypt staging:

```text
https://acme-staging-v02.api.letsencrypt.org/directory
```

Return it to the production URL after the routing and DNS checks pass. Staging
certificates are intentionally not trusted by browsers or devices.

## Existing-device upgrade order

If a feeder is already running an older MQTT firmware, upgrade the physical
ESP32 **before** deploying this backend and bridge release. The current firmware
accepts the old three-field signed command while the old bridge is still live,
but older firmware does not understand the new expiry-bound signature and will
reject every command emitted by the new bridge.

1. Flash the current ESP32 firmware while the existing control plane is still
   running.
2. Verify its heartbeat and one load-free test command.
3. Stop operator actuation, then deploy the new backend, migration, and bridge.
4. Confirm that new commands include `expires_at` and reach a terminal result
   before reconnecting physical loads.

Migration `0002_command_expiration` deliberately marks every pre-upgrade
`PENDING` or `CLAIMED` command without a deadline as `EXPIRED`; those legacy
rows are never delivered after the upgrade.

## Validate and start

Validate interpolation before creating containers:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml config --quiet
```

Then build and start the stack:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d --build
```

Inspect startup and certificate issuance:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml ps
docker compose --env-file .env.production \
  -f docker-compose.production.yml logs --tail=200 traefik mqtt mqtt-bridge backend
```

The one-shot `mqtt-init` container must exit with code `0`. It rejects short,
reused, or placeholder production secrets, placeholder domains/email, validates
the broker identities, and writes a hashed Mosquitto password file into the `mqtt-secrets` volume. The
backend waits for this gate before starting. The long-running services include
health checks for the proxy, database-backed API, dashboard, authenticated
broker handshake, and bridge credentials.

The production command lease is intentionally shorter than the manual-command
deadline (10 seconds versus 45 seconds). A lost, non-retained MQTT publish can
therefore be reclaimed and retried while the signed command is still valid.
After a command has been claimed, the 90-second result grace covers the longest
allowed pump cycle before a missing terminal result is labeled timed out.

## Verify the public endpoints

Replace the example domains in these commands:

```bash
curl --fail --show-error https://feeder.example.com/health
curl --fail --show-error https://feeder.example.com/api/health
curl --fail --show-error https://feeder.example.com/api/openapi.json >/dev/null
openssl s_client -connect mqtt.example.com:8883 \
  -servername mqtt.example.com </dev/null
```

An MQTT client can confirm both TLS and broker authentication:

```bash
read -rsp "Device MQTT password: " MQTT_DEVICE_PASSWORD
echo
mosquitto_sub \
  -h mqtt.example.com -p 8883 \
  -u feeder-001 -P "$MQTT_DEVICE_PASSWORD" \
  --cafile /etc/ssl/certs/ca-certificates.crt \
  -t 'fish-feeder/feeder-001/commands' -d
unset MQTT_DEVICE_PASSWORD
```

The ACL should reject the same device account if it attempts to subscribe to a
different device's command topic.

## Configure a physical ESP32

Copy `firmware/esp32_mqtt/feeder_secrets.example.h` to
`firmware/esp32_mqtt/feeder_secrets.h`; the destination is ignored by Git. Set:

- `FEEDER_MQTT_HOST` to `MQTT_DOMAIN`
- `FEEDER_MQTT_PORT` to `8883`
- `FEEDER_MQTT_USE_TLS` to `1`
- `FEEDER_MQTT_TLS_INSECURE` to `0`
- `FEEDER_MQTT_USERNAME` to the exact `DEVICE_UID`
- `FEEDER_MQTT_PASSWORD` to `MQTT_DEVICE_PASSWORD`
- `FEEDER_MQTT_SHARED_SECRET` to `MQTT_SHARED_SECRET`
- `FEEDER_MQTT_ROOT_CA` to the PEM root CA that validates the Let's Encrypt
  certificate chain used by the MQTT hostname

The firmware uses `WiFiClientSecure`, waits for NTP before certificate
validation, and fails closed when verified TLS has no CA. Never use
`FEEDER_MQTT_TLS_INSECURE=1` on an internet-facing broker. Broker credentials
protect the connection; the separate HMAC secret protects message integrity
after Traefik terminates TLS.

## Persistence and backups

The profile creates four named volumes:

- `feeder-data` for the SQLite database
- `mqtt-data` for broker persistence
- `mqtt-secrets` for hashed broker credentials
- `traefik-acme` for issued certificates and ACME account state

Back up all four, plus the root-owned `.env.production` file, using encrypted
off-host storage. Before a raw filesystem copy, stop every writer so SQLite,
Mosquitto persistence, and ACME account state are all crash-consistent:

```bash
docker compose --env-file .env.production -f docker-compose.production.yml \
  stop mqtt-bridge backend mqtt traefik
# Copy or snapshot the four volumes and .env.production here.
docker compose --env-file .env.production -f docker-compose.production.yml \
  start traefik mqtt backend mqtt-bridge
```

An atomic volume/storage snapshot can replace the downtime if the VPS provider
guarantees consistency across all four volumes. Test a restore on a separate
VPS; an untested backup is not a recovery plan.

Changing `FISH_FEEDER_DEVICE_API_KEY` in the environment does not rotate the key
for an existing database record. Use the authenticated key-rotation API and
update the bridge configuration together. To rotate MQTT passwords, update the
environment, force-recreate `mqtt-init`, then recreate `mqtt` and `mqtt-bridge`;
update the physical device before ending the maintenance window.

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml up --force-recreate mqtt-init
docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d --force-recreate mqtt mqtt-bridge
```

Likewise, changing `FISH_FEEDER_ADMIN_PASSWORD` does not update an existing
operator row: bootstrap credentials are applied only when that user is first
created. Add an authenticated password-change workflow or perform a controlled
password-hash migration before relying on an environment change. Changing the
credential pepper invalidates existing device-key hashes and requires a planned
rotation of every device credential.

## Operations and upgrades

Use the same explicit environment and Compose file for every command:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml pull
docker compose --env-file .env.production \
  -f docker-compose.production.yml up -d --build
```

Review release notes and vulnerability reports before changing pinned image
versions. Apply VPS security updates, restrict SSH to keys, disable password
login, use a host firewall, and monitor disk space because SQLite, broker
persistence, container logs, and certificates all share one machine. The
Compose profile uses Docker's rotating `local` log driver (10 MB × 5 files per
service); preserve an equivalent bounded policy if the logging driver changes.

## Security boundaries and limitations

- This is a single-node deployment. The VPS, its disk, and its network are
  single points of failure; there is no automatic failover.
- SQLite is suitable for this small single-process deployment, not horizontally
  scaled API replicas. Move to a managed PostgreSQL service before scaling out.
- Rate limits are process-local. Place a distributed rate limiter at the edge
  before running multiple backend processes.
- Traefik's Docker provider reads the Docker socket. The mount is read-only, but
  Docker API access remains sensitive; a production hardening step is to place a
  least-privilege Docker socket proxy between Traefik and the daemon.
- MQTT TLS is terminated at Traefik. The Traefik-to-Mosquitto hop is plaintext
  on an internal Docker network but remains username/password authenticated and
  is not published on the host.
- Broker username/passwords and application secrets are supplied through the
  environment and are visible to privileged VPS/Docker administrators. Use an
  external secret manager if the threat model requires separation from host
  administrators.
- The telemetry chart is rendered by a small repository-owned canvas module, so
  the authenticated console does not execute scripts from a third-party CDN.
- The included broker initialization and ACL cover one physical device. For
  multiple devices, create one broker user per device UID, extend the password
  initialization, and provide matching `DEVICE_CREDENTIALS_JSON` and
  `MQTT_SHARED_SECRETS_JSON` maps.
- Mosquitto 2.1 retains `password_file` and `acl_file` for compatibility but
  deprecates them. Migrate this profile to Mosquitto's password-file and ACL-file
  plugins before a future 3.0 image upgrade removes the legacy directives.

Reference documentation:

- [Traefik TCP TLS routing](https://doc.traefik.io/traefik/reference/routing-configuration/tcp/tls/)
- [Traefik Docker provider security note](https://doc.traefik.io/traefik/reference/install-configuration/providers/docker/)
- [Mosquitto authentication](https://mosquitto.org/documentation/authentication-methods/)
- [Mosquitto ACL patterns](https://mosquitto.org/documentation/plugins/acl-file/)
