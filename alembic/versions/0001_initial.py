"""Initial schema with pgvector extension."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("app_password_enc", sa.Text(), nullable=False),
        sa.Column("sync_labels", JSONB(), nullable=False),
        sa.Column("ics_url_enc", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("alias"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=True),
        sa.Column("last_uid", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("account_id", "folder", name="uq_sync_state_account_folder"),
    )

    op.create_table(
        "raw_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("gm_msgid", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=True),
        sa.Column("sender", sa.String(length=512), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("labels", JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("account_id", "gm_msgid", name="uq_raw_messages_account_gm_msgid"),
    )

    op.create_table(
        "profile_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.Integer(), sa.ForeignKey("profile_facts.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("derived_fact_ids", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("journal_entries")
    op.drop_table("memories")
    op.drop_table("profile_facts")
    op.drop_table("raw_messages")
    op.drop_table("sync_state")
    op.drop_table("accounts")
    op.execute("DROP EXTENSION IF EXISTS vector")
