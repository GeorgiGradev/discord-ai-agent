"""Payment records schema."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_payment_records"
down_revision: Union[str, None] = "0002_calendar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_message_id", sa.Integer(), sa.ForeignKey("raw_messages.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("payee", sa.String(length=255), nullable=False),
        sa.Column("payee_normalized", sa.String(length=255), nullable=False),
        sa.Column("subscriber_number", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_raw", sa.String(length=64), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("payment_status", sa.String(length=32), nullable=True),
        sa.Column("period_month", sa.String(length=7), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("extractor_name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "payee_normalized",
            "subscriber_number",
            "amount_minor",
            "period_month",
            name="uq_payment_dedup",
        ),
    )
    op.create_index(
        "ix_payment_records_account_created",
        "payment_records",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_records_account_created", table_name="payment_records")
    op.drop_table("payment_records")
