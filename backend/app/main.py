import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, engine, get_db
from .models import Device, TelemetryRecord
from .schemas import DeviceStatus, HealthResponse, TelemetryIn, TelemetryOut
from .services import create_alert

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Smart Fish Feeder Digital Twin API", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Device-Key"],
)


def require_device_key(x_device_key: str = Header(...)) -> None:
    if not secrets.compare_digest(x_device_key, settings.device_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device API key")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Smart Fish Feeder Digital Twin API", "version": "3.0.0", "docs": "/docs"}


@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="healthy", database="connected")


@app.post("/telemetry", response_model=TelemetryOut, dependencies=[Depends(require_device_key)])
def ingest_telemetry(payload: TelemetryIn, db: Session = Depends(get_db)) -> TelemetryRecord:
    device = db.scalar(select(Device).where(Device.device_uid == payload.device_uid))
    if device is None:
        device = Device(device_uid=payload.device_uid, name=payload.device_uid)
        db.add(device)
        db.flush()

    existing = db.scalar(
        select(TelemetryRecord).where(
            TelemetryRecord.device_id == device.id,
            TelemetryRecord.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing

    alert_level, alert_message = create_alert(payload.temperature_c, payload.pump_state)
    record = TelemetryRecord(
        device_id=device.id,
        idempotency_key=payload.idempotency_key,
        temperature_c=payload.temperature_c,
        cooling_on=payload.cooling_on,
        pump_state=payload.pump_state,
        event_type=payload.event_type,
        alert_level=alert_level,
        alert_message=alert_message,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(
            select(TelemetryRecord).where(
                TelemetryRecord.device_id == device.id,
                TelemetryRecord.idempotency_key == payload.idempotency_key,
            )
        )
        if duplicate is None:
            raise
        return duplicate
    db.refresh(record)
    return record


@app.get("/telemetry", response_model=list[TelemetryOut])
def list_telemetry(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> list[TelemetryRecord]:
    records = list(db.scalars(select(TelemetryRecord).order_by(desc(TelemetryRecord.created_at)).limit(limit)))
    return list(reversed(records))


@app.get("/device-status", response_model=DeviceStatus)
def get_device_status(device_uid: str = "feeder-001", db: Session = Depends(get_db)) -> DeviceStatus:
    device = db.scalar(select(Device).where(Device.device_uid == device_uid))
    latest = (
        None
        if device is None
        else db.scalar(
            select(TelemetryRecord)
            .where(TelemetryRecord.device_id == device.id)
            .order_by(desc(TelemetryRecord.created_at))
        )
    )
    if latest is None:
        return DeviceStatus(
            device_uid=device_uid,
            online=False,
            temperature_c=None,
            cooling_on=None,
            pump_state=None,
            alert_level="unknown",
            alert_message="No telemetry has been received yet.",
            last_event_type=None,
            last_seen=None,
        )
    last_seen = latest.created_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    online = (datetime.now(UTC) - last_seen).total_seconds() <= settings.offline_after_seconds
    return DeviceStatus(
        device_uid=device_uid,
        online=online,
        temperature_c=latest.temperature_c,
        cooling_on=latest.cooling_on,
        pump_state=latest.pump_state,
        alert_level=latest.alert_level if online else "warning",
        alert_message=latest.alert_message if online else "Device heartbeat is stale.",
        last_event_type=latest.event_type,
        last_seen=latest.created_at,
    )


@app.get("/alerts", response_model=list[TelemetryOut])
def list_alerts(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)) -> list[TelemetryRecord]:
    return list(
        db.scalars(
            select(TelemetryRecord)
            .where(TelemetryRecord.alert_level != "normal")
            .order_by(desc(TelemetryRecord.created_at))
            .limit(limit)
        )
    )
