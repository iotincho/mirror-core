"""Public HTTP schemas exposed by the user-management module."""

from uuid import UUID

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(schemas.BaseUser[UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class SessionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: EmailStr
