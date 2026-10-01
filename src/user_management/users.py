"""Configured FastAPI Users facade."""

from uuid import UUID

from fastapi_users import FastAPIUsers

from src.user_management.authentication import auth_backend
from src.user_management.manager import get_user_manager
from src.user_management.models import User

fastapi_users = FastAPIUsers[User, UUID](get_user_manager, [auth_backend])
