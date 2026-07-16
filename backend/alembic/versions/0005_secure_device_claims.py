"""Add expiring device claims, ownership transfers, and credential versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_secure_device_claims"
down_revision: str | None = "0004_customer_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "claim_expires_at" not in columns:
        op.add_column("devices", sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True))
    if "claim_consumed_at" not in columns:
        op.add_column("devices", sa.Column("claim_consumed_at", sa.DateTime(timezone=True), nullable=True))
    if "transfer_code_hash" not in columns:
        op.add_column("devices", sa.Column("transfer_code_hash", sa.String(length=64), nullable=True))
    if "transfer_expires_at" not in columns:
        op.add_column("devices", sa.Column("transfer_expires_at", sa.DateTime(timezone=True), nullable=True))
    if "credential_version" not in columns:
        op.add_column(
            "devices",
            sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    for column in (
        "credential_version",
        "transfer_expires_at",
        "transfer_code_hash",
        "claim_consumed_at",
        "claim_expires_at",
    ):
        if column in columns:
            op.drop_column("devices", column)
