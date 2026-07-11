from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_uid: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="Fish Feeder")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    telemetry: Mapped[list["TelemetryRecord"]] = relationship(back_populates="device")


class TelemetryRecord(Base):
    __tablename__ = "telemetry"
    __table_args__ = (UniqueConstraint("device_id", "idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    temperature_c: Mapped[float] = mapped_column(Float)
    cooling_on: Mapped[bool] = mapped_column(Boolean)
    pump_state: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    alert_level: Mapped[str] = mapped_column(String(20), default="normal")
    alert_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    device: Mapped[Device] = relationship(back_populates="telemetry")


class FeedingSchedule(Base):
    __tablename__ = "feeding_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    hour: Mapped[int] = mapped_column(Integer)
    minute: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
