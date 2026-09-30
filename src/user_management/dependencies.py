"""Application-facing identity contract."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import EmailStr

from src.user_management.models import User
from src.user_management.users import fastapi_users

current_active_user = fastapi_users.current_user(active=True)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: EmailStr


def get_authenticated_user(
    user: Annotated[User, Depends(current_active_user)],
) -> AuthenticatedUser:
    return AuthenticatedUser(id=user.id, email=user.email)
