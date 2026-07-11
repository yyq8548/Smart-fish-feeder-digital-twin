from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PumpState = Literal["IDLE", "FEEDING", "CLEANING", "ERROR"]


class TelemetryIn(BaseModel):
    device_uid: str = Field(default="feeder-001", min_length=3, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=100)
    temperature_c: float = Field(ge=-20, le=80)
    cooling_on: bool
    pump_state: PumpState
    event_type: str | None = Field(default=None, max_length=80)


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    temperature_c: float
    cooling_on: bool
    pump_state: str
    event_type: str | None
    alert_level: str
    alert_message: str | None
    created_at: datetime


class DeviceStatus(BaseModel):
    device_uid: str
    online: bool
    temperature_c: float | None
    cooling_on: bool | None
    pump_state: str | None
    alert_level: str
    alert_message: str | None
    last_event_type: str | None
    last_seen: datetime | None


class HealthResponse(BaseModel):
    status: str
    database: str
