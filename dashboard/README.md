# Dashboard

This Nginx-served dashboard fetches live status, ordered telemetry, and durable alerts from the FastAPI backend. It renders offline and empty states and exposes API failures instead of silently displaying stale data.

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

The dashboard reads:

- `GET /device-status`
- `GET /telemetry`
- `GET /alerts`

Run its ESLint and Vitest quality gates with `pnpm lint` and `pnpm test`.
