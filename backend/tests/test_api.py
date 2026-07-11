from fastapi.testclient import TestClient

AUTH = {"X-Device-Key": "test-key"}


def test_root_and_health(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"status": "healthy", "database": "connected"}


def test_empty_endpoints(client: TestClient) -> None:
    assert client.get("/telemetry").json() == []
    assert client.get("/alerts").json() == []
    status = client.get("/device-status").json()
    assert status["online"] is False
    assert status["temperature_c"] is None


def test_ingest_requires_authentication(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    assert client.post("/telemetry", json=telemetry_payload).status_code == 422
    assert client.post("/telemetry", json=telemetry_payload, headers={"X-Device-Key": "wrong"}).status_code == 401


def test_ingest_and_read_every_endpoint(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    created = client.post("/telemetry", json=telemetry_payload, headers=AUTH)
    assert created.status_code == 200
    assert created.json()["alert_level"] == "normal"
    assert len(client.get("/telemetry").json()) == 1
    assert client.get("/device-status").json()["pump_state"] == "IDLE"
    assert client.get("/alerts").json() == []


def test_idempotency_returns_same_record(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    first = client.post("/telemetry", json=telemetry_payload, headers=AUTH).json()
    second = client.post("/telemetry", json=telemetry_payload, headers=AUTH).json()
    assert second["id"] == first["id"]
    assert len(client.get("/telemetry").json()) == 1


def test_alert_endpoint(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    telemetry_payload["temperature_c"] = 6.0
    response = client.post("/telemetry", json=telemetry_payload, headers=AUTH)
    assert response.json()["alert_level"] == "critical"
    assert len(client.get("/alerts").json()) == 1


def test_telemetry_validation(client: TestClient, telemetry_payload: dict[str, object]) -> None:
    telemetry_payload["pump_state"] = "BROKEN"
    assert client.post("/telemetry", json=telemetry_payload, headers=AUTH).status_code == 422

    telemetry_payload["pump_state"] = "IDLE"
    telemetry_payload["temperature_c"] = 100
    assert client.post("/telemetry", json=telemetry_payload, headers=AUTH).status_code == 422


def test_pagination_validation(client: TestClient) -> None:
    assert client.get("/telemetry?limit=0").status_code == 422
    assert client.get("/alerts?limit=101").status_code == 422
