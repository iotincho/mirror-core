"""Deployment data migrations, independent of extraction/profile versions."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class DataMigration(Base):
    __tablename__ = "data_migrations"

    migration_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    instance_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    target: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
