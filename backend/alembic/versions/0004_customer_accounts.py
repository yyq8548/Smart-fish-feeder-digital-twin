"""Add customer accounts, device ownership, and pairing credentials."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_customer_accounts"
down_revision: str | None = "0003_user_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "email" not in user_columns:
        op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    if "email_verified" not in user_columns:
        op.add_column(
            "users",
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "auth_version" not in user_columns:
        op.add_column(
            "users",
            sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
        )

    device_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "pairing_code_hash" not in device_columns:
        op.add_column("devices", sa.Column("pairing_code_hash", sa.String(length=64), nullable=True))
    if "owner_user_id" not in device_columns:
        op.add_column("devices", sa.Column("owner_user_id", sa.Integer(), nullable=True))
        op.create_index("ix_devices_owner_user_id", "devices", ["owner_user_id"], unique=False)


def downgrade() -> None:
    device_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("devices")}
    if "owner_user_id" in device_columns:
        op.drop_index("ix_devices_owner_user_id", table_name="devices")
        op.drop_column("devices", "owner_user_id")
    if "pairing_code_hash" in device_columns:
        op.drop_column("devices", "pairing_code_hash")
    user_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "auth_version" in user_columns:
        op.drop_column("users", "auth_version")
    if "email_verified" in user_columns:
        op.drop_column("users", "email_verified")
    if "email" in user_columns:
        op.drop_index("ix_users_email", table_name="users")
        op.drop_column("users", "email")
