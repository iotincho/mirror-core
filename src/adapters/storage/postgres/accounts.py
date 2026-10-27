"""Account, OAuth and session tables sharing one PostgreSQL metadata registry."""

from __future__ import annotations

from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseOAuthAccountTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import Boolean, DateTime, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.adapters.storage.postgres.base import Base as Base


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    user: Mapped[User] = relationship("User", back_populates="oauth_accounts")


class User(SQLAlchemyBaseUserTableUUID, Base):
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now()
    )
    laboratory_welcome_dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    laboratory_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    password_login_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="joined",
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
