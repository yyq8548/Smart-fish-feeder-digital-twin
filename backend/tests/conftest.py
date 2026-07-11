import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

test_database_directory = TemporaryDirectory(prefix="fish-feeder-tests-")
test_database_path = Path(test_database_directory.name) / "fish-feeder.db"
os.environ["FISH_FEEDER_DATABASE_URL"] = f"sqlite:///{test_database_path.as_posix()}"
os.environ["FISH_FEEDER_DEVICE_API_KEY"] = "test-device-key"
os.environ["FISH_FEEDER_CREDENTIAL_PEPPER"] = "test-credential-pepper"
os.environ["FISH_FEEDER_ADMIN_USERNAME"] = "test-admin"
os.environ["FISH_FEEDER_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["FISH_FEEDER_JWT_SECRET"] = "test-jwt-secret-that-is-long-enough"
os.environ["FISH_FEEDER_OFFLINE_AFTER_SECONDS"] = "60"

import pytest
from app.database import Base, engine
from app.main import app
from app.rate_limit import rate_limiter
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database() -> Generator[None, None, None]:
    yield
    engine.dispose()
    test_database_directory.cleanup()


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def operator_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/token",
        data={"username": "test-admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def device_headers() -> dict[str, str]:
    return {"X-Device-ID": "feeder-001", "X-Device-Key": "test-device-key"}


@pytest.fixture
def telemetry_payload() -> dict[str, object]:
    return {
        "device_uid": "feeder-001",
        "idempotency_key": "reading-1",
        "sequence_number": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "temperature_c": 4.0,
        "cooling_on": False,
        "pump_state": "IDLE",
        "sensor_status": "OK",
        "event_type": None,
    }
