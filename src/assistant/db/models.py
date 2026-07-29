"""SQLAlchemy ORM models."""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False, default="imap.gmail.com")
    app_password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    sync_labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ics_url_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("account_id", "folder", name="uq_sync_state_account_folder"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    folder: Mapped[str] = mapped_column(String(255), nullable=False, default="[Gmail]/All Mail")
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_uid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class IcsSyncState(Base):
    __tablename__ = "ics_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), unique=True, nullable=False
    )
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint("account_id", "cal_uid", name="uq_calendar_events_account_cal_uid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    cal_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    source_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "gm_msgid", name="uq_raw_messages_account_gm_msgid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    gm_msgid: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    text_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PaymentRecord(Base):
    __tablename__ = "payment_records"
    __table_args__ = (
        UniqueConstraint(
            "payee_normalized",
            "subscriber_number",
            "amount_minor",
            "period_month",
            name="uq_payment_dedup",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payee: Mapped[str] = mapped_column(String(255), nullable=False)
    payee_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    subscriber_number: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_raw: Mapped[str] = mapped_column(String(64), nullable=False)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProfileFact(Base):
    __tablename__ = "profile_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(
        ForeignKey("profile_facts.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    derived_fact_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
