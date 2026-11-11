"""premium subscriptions, email/password accounts, billing, schedule uniqueness

- users: google_sub nullable; password_hash, email_verified (existing users are verified via Google/dev login)
- email_otps, login_attempts: email codes and sign-in rate limiting
- subscriptions, coupons, coupon_redemptions, billing_orders: premium and payments
- auto_schedules: drop exact duplicates, then one row per (user, style, interval)

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("google_sub", existing_type=sa.String(length=255), nullable=True)
        batch_op.add_column(sa.Column("password_hash", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET email_verified = true")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("email_verified", existing_type=sa.Boolean(), server_default=None)

    op.create_table(
        "email_otps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", "purpose"),
    )
    op.create_index(op.f("ix_email_otps_email"), "email_otps", ["email"], unique=False)

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=400), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_login_attempts_key"), "login_attempts", ["key"], unique=False)
    op.create_index(op.f("ix_login_attempts_created_at"), "login_attempts", ["created_at"], unique=False)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=False)
    op.create_index(op.f("ix_subscriptions_ends_at"), "subscriptions", ["ends_at"], unique=False)

    op.create_table(
        "coupons",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coupon_code", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["coupon_code"], ["coupons.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coupon_code", "user_id"),
    )
    op.create_index(op.f("ix_coupon_redemptions_coupon_code"), "coupon_redemptions", ["coupon_code"], unique=False)
    op.create_index(op.f("ix_coupon_redemptions_user_id"), "coupon_redemptions", ["user_id"], unique=False)

    op.create_table(
        "billing_orders",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("discount_paise", sa.Integer(), nullable=False),
        sa.Column("coupon_code", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_billing_orders_user_id"), "billing_orders", ["user_id"], unique=False)

    # Keep the oldest of any identical schedules, then enforce uniqueness.
    op.execute(
        "DELETE FROM auto_schedules WHERE id NOT IN ("
        "SELECT keep_id FROM (SELECT MIN(id) AS keep_id FROM auto_schedules "
        "GROUP BY user_id, style, interval_min) AS keep)"
    )
    with op.batch_alter_table("auto_schedules", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_auto_schedules_user_style_interval", ["user_id", "style", "interval_min"])


def downgrade() -> None:
    with op.batch_alter_table("auto_schedules", schema=None) as batch_op:
        batch_op.drop_constraint("uq_auto_schedules_user_style_interval", type_="unique")

    op.drop_index(op.f("ix_billing_orders_user_id"), table_name="billing_orders")
    op.drop_table("billing_orders")
    op.drop_index(op.f("ix_coupon_redemptions_user_id"), table_name="coupon_redemptions")
    op.drop_index(op.f("ix_coupon_redemptions_coupon_code"), table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_table("coupons")
    op.drop_index(op.f("ix_subscriptions_ends_at"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_login_attempts_created_at"), table_name="login_attempts")
    op.drop_index(op.f("ix_login_attempts_key"), table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index(op.f("ix_email_otps_email"), table_name="email_otps")
    op.drop_table("email_otps")

    # Password-only accounts can't exist before this revision.
    op.execute("DELETE FROM users WHERE google_sub IS NULL")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_verified")
        batch_op.drop_column("password_hash")
        batch_op.alter_column("google_sub", existing_type=sa.String(length=255), nullable=False)
