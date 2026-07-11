import os
from collections.abc import Generator

os.environ["FISH_FEEDER_DATABASE_URL"] = "sqlite:///./test_fish_feeder.db"
os.environ["FISH_FEEDER_DEVICE_API_KEY"] = "test-key"

import pytest
from app.database import Base, engine
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def telemetry_payload() -> dict[str, object]:
    return {
        "device_uid": "feeder-001",
        "idempotency_key": "reading-1",
        "temperature_c": 4.0,
        "cooling_on": False,
        "pump_state": "IDLE",
        "event_type": None,
    }
