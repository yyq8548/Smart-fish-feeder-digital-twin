# Backend API v4

The FastAPI backend owns authenticated device ingestion, operator workflows, operational persistence, alerts, commands, and reliability scanning.

## Run locally

From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\alembic.exe upgrade head
..\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

## Configuration

All variables use the `FISH_FEEDER_` prefix:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy connection URL |
| `DEVICE_API_KEY` | Initial key for the bootstrap device |
| `BOOTSTRAP_DEVICE_UID` | Initial device identity |
| `CREDENTIAL_PEPPER` | Secret used for device-key digests |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Initial operator credentials |
| `JWT_SECRET` / `JWT_EXPIRE_MINUTES` | Operator access tokens |
| `CORS_ORIGINS` | Comma-separated allowed dashboard origins |
| `OFFLINE_AFTER_SECONDS` | Heartbeat timeout |
| `MAX_TELEMETRY_AGE_SECONDS` | Maximum accepted event age |
| `MAX_FUTURE_SKEW_SECONDS` | Allowed device clock skew |
| `TELEMETRY_RATE_LIMIT_PER_MINUTE` | Per-device ingestion limit |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | Per-client login limit |
| `RELIABILITY_SCAN_INTERVAL_SECONDS` | Automatic missed/offline scan interval |
| `COMMAND_LEASE_SECONDS` | Time before an unconfirmed command can be reclaimed |
| `MANUAL_COMMAND_TTL_SECONDS` | Maximum time an operator command may wait before delivery |
| `COMMAND_RESULT_GRACE_SECONDS` | Time a claimed command may await its physical terminal result after the delivery deadline |
| `ROOT_PATH` | Optional reverse-proxy prefix used by OpenAPI and Swagger links |
| `REQUIRE_ONLINE_FOR_ACTUATION` | Reject feed, clean, and cooling commands when heartbeats are stale |
| `CREDENTIAL_ATTEMPT_RATE_LIMIT_PER_MINUTE` | Per-client invalid/valid ingestion-attempt limit |

## Migrations

`alembic upgrade head` creates a new v4 database. The initial revision also detects and upgrades the unversioned v3 prototype tables while preserving their telemetry records. Migration behavior is integration-tested with both empty and legacy databases.

## Security model

- Operators authenticate with Argon2-hashed passwords and short-lived HS256 JWTs.
- Devices use a UID and high-entropy API key. Only an HMAC-SHA256 digest is stored.
- Device keys can be rotated through the authenticated operator API.
- Login and telemetry ingestion use bounded in-process rate limits.
- CORS explicitly allows configured origins and headers.
- Operational telemetry, status, alerts, schedules, and commands require an operator bearer token.

Telemetry idempotency is backed by a canonical SHA-256 payload fingerprint, so concurrent exact retries return the winning row while key reuse with changed content returns `409`.

Commands require caller-provided idempotency keys. Their type-specific payloads reject unknown fields and invalid actuator values and are capped at 1,024 serialized bytes. Manual actuation is refused while the device is offline, and every operator command receives a short delivery deadline so an old pending request cannot run after a later reconnect. Claiming uses conditional database updates and expiring leases; once delivered, a separate result grace keeps long-running pump cycles in `CLAIMED` state while their signed terminal result is still expected. Firmware persists a monotonic NVS watermark before actuation so a reclaimed command cannot repeat a physical operation after reboot. Terminal completion calls are themselves idempotent, and a signed scheduled-feed completion reconciles execution history when telemetry was lost.

The in-process limiter assumes one API process. Use a shared rate-limit store before horizontal scaling.
