"""multiple auto-analysis schedules per user

Moves user_settings.auto_enabled / auto_interval_min / next_auto_run_at into an
auto_schedules table (one row per style+interval reminder).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("style", sa.String(length=32), nullable=False),
        sa.Column("interval_min", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("auto_schedules", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_auto_schedules_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_auto_schedules_next_run_at"), ["next_run_at"], unique=False)

    # Carry over each user's existing single schedule (only if it was switched on).
    op.execute(
        "INSERT INTO auto_schedules (user_id, style, interval_min, enabled, next_run_at, created_at) "
        "SELECT user_id, default_style, auto_interval_min, auto_enabled, next_auto_run_at, CURRENT_TIMESTAMP "
        "FROM user_settings WHERE auto_enabled = true"
    )

    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_settings_next_auto_run_at"))
        batch_op.drop_column("next_auto_run_at")
        batch_op.drop_column("auto_interval_min")
        batch_op.drop_column("auto_enabled")


def downgrade() -> None:
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("auto_interval_min", sa.Integer(), nullable=False, server_default="60"))
        batch_op.add_column(sa.Column("next_auto_run_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_user_settings_next_auto_run_at"), ["next_auto_run_at"], unique=False)

    op.execute(
        "UPDATE user_settings SET auto_enabled = true, auto_interval_min = s.interval_min "
        "FROM (SELECT user_id, MIN(interval_min) AS interval_min FROM auto_schedules WHERE enabled = true "
        "GROUP BY user_id) AS s WHERE user_settings.user_id = s.user_id"
    )

    with op.batch_alter_table("auto_schedules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_auto_schedules_next_run_at"))
        batch_op.drop_index(batch_op.f("ix_auto_schedules_user_id"))
    op.drop_table("auto_schedules")
