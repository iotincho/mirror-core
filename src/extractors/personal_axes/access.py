"""The global switch and the account grant must both permit new Laboratory work."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.storage.postgres.accounts import User
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_async_session
from src.bootstrap.settings import get_settings
from src.core.auth.identity import AuthenticatedUser


async def laboratory_available(session, owner):
    if not get_settings().personal_axes_enabled:
        return False
    return bool(
        await session.scalar(
            select(User.laboratory_enabled).where(User.id == owner, User.is_active.is_(True))
        )
    )


async def require_laboratory_access(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
):
    if not await laboratory_available(session, user.id):
        raise HTTPException(404, "Not found")
