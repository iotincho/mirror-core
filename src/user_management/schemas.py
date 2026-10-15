"""Public HTTP schemas exposed by the user-management module."""

from uuid import UUID

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(schemas.BaseUser[UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    def create_update_dict(self):
        return {**super().create_update_dict(), "password_login_enabled": True}

    def create_update_dict_superuser(self):
        return {**super().create_update_dict_superuser(), "password_login_enabled": True}


class UserUpdate(schemas.BaseUserUpdate):
    pass


class SessionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    email: EmailStr
