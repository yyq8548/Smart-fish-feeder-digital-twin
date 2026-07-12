import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PumpState = Literal["IDLE", "FEEDING", "CLEANING", "ERROR"]
SensorStatus = Literal["OK", "ERROR", "DISCONNECTED"]
MAX_SERIALIZED_COMMAND_PAYLOAD_BYTES = 1024


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    active: bool


class DeviceCreate(BaseModel):
    device_uid: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_uid: str
    name: str
    active: bool
    last_sequence_number: int | None
    last_seen_at: datetime | None
    created_at: datetime


class DeviceProvisioned(DeviceOut):
    api_key: str


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_uid: str = Field(min_length=3, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=100)
    sequence_number: int = Field(ge=0)
    recorded_at: datetime
    temperature_c: float | None = Field(default=None, ge=-20, le=80)
    cooling_on: bool
    pump_state: PumpState
    sensor_status: SensorStatus = "OK"
    event_type: str | None = Field(default=None, max_length=80)
    schedule_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_sensor_reading(self) -> "TelemetryIn":
        if self.sensor_status == "OK" and self.temperature_c is None:
            raise ValueError("temperature_c is required when sensor_status is OK")
        return self


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sequence_number: int
    recorded_at: datetime
    temperature_c: float | None
    cooling_on: bool
    pump_state: str
    sensor_status: str
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
    sensor_status: str | None
    alert_level: str
    alert_message: str | None
    last_event_type: str | None
    last_sequence_number: int | None
    last_seen: datetime | None


class ScheduleCreate(BaseModel):
    name: str = Field(default="Daily feeding", min_length=1, max_length=120)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    days_of_week: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    grace_minutes: int = Field(default=10, ge=1, le=180)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_days(self) -> "ScheduleCreate":
        if any(day < 0 or day > 6 for day in self.days_of_week):
            raise ValueError("days_of_week values must be between 0 and 6")
        self.days_of_week = sorted(set(self.days_of_week))
        return self


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    days_of_week: list[int] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    grace_minutes: int | None = Field(default=None, ge=1, le=180)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    name: str
    hour: int
    minute: int
    days_of_week: str
    timezone: str
    grace_minutes: int
    enabled: bool
    created_at: datetime


class FeedingExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    schedule_id: int | None
    execution_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    details: str | None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    category: str
    level: str
    message: str
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime


class FeedCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_ms: int | None = Field(default=None, ge=500, le=60_000, strict=True)
    schedule_id: int | None = Field(default=None, ge=1, strict=True)


class CleanPumpCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_ms: int | None = Field(default=None, ge=500, le=60_000, strict=True)


class SetCoolingCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["AUTO", "FORCED_ON", "FORCED_OFF"] | None = None
    enabled: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_single_control(self) -> "SetCoolingCommandPayload":
        if (self.mode is None) == (self.enabled is None):
            raise ValueError("exactly one of mode or enabled is required")
        return self


ScheduleDay = Annotated[int, Field(ge=0, le=6, strict=True)]


class RuntimeSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1, strict=True)
    hour: int = Field(ge=0, le=23, strict=True)
    minute: int = Field(ge=0, le=59, strict=True)
    days_of_week: list[ScheduleDay] = Field(min_length=1, max_length=7)
    timezone: Literal["UTC"] = "UTC"
    enabled: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def normalize_days(self) -> "RuntimeSchedulePayload":
        self.days_of_week = sorted(set(self.days_of_week))
        return self


class SyncSchedulesCommandPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedules: list[RuntimeSchedulePayload] = Field(max_length=8)

    @model_validator(mode="after")
    def validate_unique_schedule_ids(self) -> "SyncSchedulesCommandPayload":
        schedule_ids = [schedule.id for schedule in self.schedules]
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("schedule IDs must be unique")
        return self


class CommandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=100)
    command_type: Literal["FEED_NOW", "CLEAN_PUMP", "SET_COOLING", "SYNC_SCHEDULES"]
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_command_payload(self) -> "CommandCreate":
        validated_payload: dict[str, object]
        if self.command_type == "FEED_NOW":
            validated_payload = FeedCommandPayload.model_validate(self.payload).model_dump(exclude_none=True)
        elif self.command_type == "CLEAN_PUMP":
            validated_payload = CleanPumpCommandPayload.model_validate(self.payload).model_dump(exclude_none=True)
        elif self.command_type == "SET_COOLING":
            validated_payload = SetCoolingCommandPayload.model_validate(self.payload).model_dump(exclude_none=True)
        else:
            validated_payload = SyncSchedulesCommandPayload.model_validate(self.payload).model_dump(exclude_none=True)

        self.payload = validated_payload
        serialized = json.dumps(self.payload, separators=(",", ":"), sort_keys=True)
        if len(serialized.encode("utf-8")) > MAX_SERIALIZED_COMMAND_PAYLOAD_BYTES:
            raise ValueError(f"serialized command payload must not exceed {MAX_SERIALIZED_COMMAND_PAYLOAD_BYTES} bytes")
        return self


class CommandComplete(BaseModel):
    status: Literal["COMPLETED", "FAILED"]
    result: str | None = Field(default=None, max_length=300)


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    idempotency_key: str
    command_type: str
    payload_json: str
    status: str
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    expires_at: datetime | None
    completed_at: datetime | None
    result: str | None
    created_at: datetime


class ReliabilityScanOut(BaseModel):
    missed_feedings_created: int
    offline_alerts_created: int
    scheduled_commands_created: int


class HealthResponse(BaseModel):
    status: str
    database: str
