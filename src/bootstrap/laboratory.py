"""Compose account-only Laboratory access before opening workspace resources."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.storage.postgres.personal_axes.laboratory import PostgresLaboratory
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_async_session
from src.bootstrap.settings import get_settings
from src.core.auth.identity import AuthenticatedUser
from src.use_cases.personal_axes.laboratory import Laboratory


def get_laboratory(session: Annotated[AsyncSession, Depends(get_async_session)]):
    return Laboratory(PostgresLaboratory(session=session), get_settings().personal_axes_enabled)


async def laboratory_available(session, owner):
    return await get_laboratory(session).available(owner)


async def require_laboratory_access(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    laboratory: Annotated[Laboratory, Depends(get_laboratory)],
):
    if not await laboratory.available(user.id):
        raise HTTPException(404, "Not found")
