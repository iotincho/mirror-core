"""Bounded limiter history and protected short-lived recovery credentials."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.accounts import Base


class RecoveryAddress(Base):
    __tablename__ = "password_recovery_addresses"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    sent_times: Mapped[list] = mapped_column(JSON, default=list)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    challenge_id: Mapped[UUID | None] = mapped_column()
    code_mac: Mapped[str | None] = mapped_column(String(64))
    code_ciphertext: Mapped[str | None] = mapped_column(Text)
    password_mac: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    __table_args__ = (Index("ix_recovery_address_cleanup", "updated_at"),)


class RecoveryIP(Base):
    __tablename__ = "password_recovery_ips"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_times: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class RecoveryDelivery(Base):
    __tablename__ = "password_recovery_deliveries"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    address_key: Mapped[str] = mapped_column(
        ForeignKey("password_recovery_addresses.key", ondelete="CASCADE")
    )
    challenge_id: Mapped[UUID] = mapped_column()
    processing_id: Mapped[UUID] = mapped_column(ForeignKey("processing_records.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
