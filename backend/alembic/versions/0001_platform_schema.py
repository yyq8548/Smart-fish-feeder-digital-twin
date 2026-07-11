"""Create the v4 schema or upgrade an unversioned v3 prototype database."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app import models
from app.database import Base

revision: str = "0001_platform_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("devices"):
        Base.metadata.create_all(bind=bind)
        return

    device_columns = _columns("devices")
    if "api_key_hash" not in device_columns:
        op.add_column("devices", sa.Column("api_key_hash", sa.String(64), nullable=False, server_default=""))
        op.add_column("devices", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
        op.add_column("devices", sa.Column("last_sequence_number", sa.Integer(), nullable=True))
        op.add_column("devices", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    telemetry_columns = _columns("telemetry")
    if "payload_hash" not in telemetry_columns:
        op.add_column("telemetry", sa.Column("payload_hash", sa.String(64), nullable=True))
    if "sequence_number" not in telemetry_columns:
        op.add_column("telemetry", sa.Column("sequence_number", sa.Integer(), nullable=True))
        op.add_column("telemetry", sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("telemetry", sa.Column("sensor_status", sa.String(20), nullable=False, server_default="OK"))
        op.execute(sa.text("UPDATE telemetry SET sequence_number = id, recorded_at = created_at"))
        with op.batch_alter_table("telemetry") as batch:
            batch.alter_column("temperature_c", existing_type=sa.Float(), nullable=True)
        op.create_index("uq_telemetry_device_sequence", "telemetry", ["device_id", "sequence_number"], unique=True)
        op.execute(
            sa.text(
                "UPDATE devices SET "
                "last_sequence_number = (SELECT MAX(sequence_number) FROM telemetry WHERE device_id = devices.id), "
                "last_seen_at = (SELECT MAX(recorded_at) FROM telemetry WHERE device_id = devices.id)"
            )
        )

    schedule_columns = _columns("feeding_schedules")
    if "name" not in schedule_columns:
        op.add_column(
            "feeding_schedules",
            sa.Column("name", sa.String(120), nullable=False, server_default="Daily feeding"),
        )
        op.add_column(
            "feeding_schedules",
            sa.Column("days_of_week", sa.String(20), nullable=False, server_default="0,1,2,3,4,5,6"),
        )
        op.add_column("feeding_schedules", sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"))
        op.add_column(
            "feeding_schedules", sa.Column("grace_minutes", sa.Integer(), nullable=False, server_default="10")
        )
        op.add_column("feeding_schedules", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(sa.text("UPDATE feeding_schedules SET created_at = CURRENT_TIMESTAMP"))

    for table in (
        models.User.__table__,
        models.FeedingExecution.__table__,
        models.Alert.__table__,
        models.DeviceCommand.__table__,
    ):
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
