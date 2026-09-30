"""HTTP routes owned by user management."""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.user_management.authentication import auth_backend
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user
from src.user_management.schemas import SessionRead, UserCreate, UserRead
from src.user_management.users import fastapi_users

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_auth_router(auth_backend))
router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))


@router.get("/session", response_model=SessionRead)
def session(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> SessionRead:
    return SessionRead(user_id=user.id, email=user.email)
