"""Conference and career event tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_event_records"
down_revision: Union[str, None] = "0003_payment_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_messages",
        sa.Column(
            "event_extraction_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )

    op.create_table(
        "conference_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_message_id", sa.Integer(), sa.ForeignKey("raw_messages.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("name_normalized", sa.String(length=512), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column(
            "location_normalized",
            sa.String(length=512),
            nullable=False,
            server_default="",
        ),
        sa.Column("attendance_mode", sa.String(length=32), nullable=True),
        sa.Column("price_raw", sa.String(length=64), nullable=True),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("registration_deadline", sa.Date(), nullable=True),
        sa.Column("cfp_deadline", sa.Date(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("extractor_name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "name_normalized",
            "starts_on",
            "location_normalized",
            name="uq_conference_dedup",
        ),
    )
    op.create_index(
        "ix_conference_events_account_created",
        "conference_events",
        ["account_id", "created_at"],
    )

    op.create_table(
        "career_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("raw_message_id", sa.Integer(), sa.ForeignKey("raw_messages.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=False),
        sa.Column("company_normalized", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=255), nullable=True),
        sa.Column(
            "position_normalized",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("extractor_name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_normalized",
            "position_normalized",
            "event_type",
            "deadline",
            name="uq_career_dedup",
        ),
    )
    op.create_index(
        "ix_career_events_account_created",
        "career_events",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_career_events_account_created", table_name="career_events")
    op.drop_table("career_events")
    op.drop_index("ix_conference_events_account_created", table_name="conference_events")
    op.drop_table("conference_events")
    op.drop_column("raw_messages", "event_extraction_status")
