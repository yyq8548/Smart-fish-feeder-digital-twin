"""Add bounded command delivery windows for remote actuation safety."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_command_expiration"
down_revision: str | None = "0001_platform_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("device_commands")}
    if "expires_at" not in columns:
        op.add_column("device_commands", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # Commands created before delivery deadlines existed must never become
    # newly actionable just because an upgraded bridge starts polling them.
    op.execute(
        sa.text(
            "UPDATE device_commands "
            "SET status = 'EXPIRED', completed_at = CURRENT_TIMESTAMP, "
            "result = 'expired_during_expiry_migration' "
            "WHERE expires_at IS NULL AND status IN ('PENDING', 'CLAIMED')"
        )
    )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("device_commands")}
    if "ix_device_commands_expires_at" not in indexes:
        op.create_index("ix_device_commands_expires_at", "device_commands", ["expires_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("device_commands")}
    if "ix_device_commands_expires_at" in indexes:
        op.drop_index("ix_device_commands_expires_at", table_name="device_commands")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("device_commands")}
    if "expires_at" in columns:
        with op.batch_alter_table("device_commands") as batch:
            batch.drop_column("expires_at")
