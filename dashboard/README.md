# Dashboard

This Nginx-served operator console authenticates with the FastAPI backend, keeps its bearer token in tab-scoped session storage, and scopes live status, ordered telemetry, durable alerts, and command history to the selected device. Confirmed controls can issue `FEED_NOW`, `CLEAN_PUMP`, and `SET_COOLING`; the forward-feed phase and standalone clean duration default to a conservative 1,000 ms and accept whole numbers from 500 through 60,000 ms. The feed command still proceeds through its automatic wait and reverse-clean phases. Browser validation provides immediate feedback while the API remains authoritative. Every actuator is disabled when the device is offline or the session is unavailable. Request-generation guards prevent a delayed response for an old device or signed-out session from repopulating the console, and the temperature graph uses a repository-owned canvas renderer rather than third-party script execution. API failures, expired sessions, empty data, command conflicts, and command expiry remain visible instead of being presented as successful operations.

## Run

Start the backend first:

```bash
cd backend
uvicorn main:app --reload
```

Start the mock device in another terminal:

```bash
cd mock_device
python mock_esp32_client.py
```

For the complete container setup, open:

```text
http://localhost:8080
```

The dashboard uses:

- `POST /auth/token`
- `POST /auth/register`
- `POST /auth/verify-email`
- `POST /auth/password-reset/request`
- `POST /auth/password-reset/confirm`
- `GET /users/me`
- `GET /devices`
- `POST /devices/pair`
- `DELETE /devices/{device_uid}/pairing`
- `GET /device-status`
- `GET /telemetry`
- `GET /alerts`
- `POST/GET /devices/{device_uid}/commands`

Run its ESLint and Vitest quality gates with `pnpm lint` and `pnpm test`.
