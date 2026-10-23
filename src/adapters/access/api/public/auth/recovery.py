"""Public recovery endpoints never reveal whether an email has a local account."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from src.adapters.access.api.public.auth.proxy import recovery_client_ip
from src.core.auth.recovery import RecoveryError
from src.use_cases.auth.recover_password import RecoverPassword


class RecoveryRequest(BaseModel):
    email: EmailStr


class RecoveryReset(RecoveryRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")
    password: str = Field(min_length=1, max_length=1024)


def public_error(error):
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    status = 429 if error.code == "recovery_rate_limited" else 400
    return HTTPException(status, detail=error.code, headers=headers)


def build_recovery_router(get_password_recovery, trusted_cidrs):
    router = APIRouter()

    @router.post("/forgot-password", status_code=202)
    async def forgot_password(
        payload: RecoveryRequest,
        request: Request,
        recovery: Annotated[RecoverPassword, Depends(get_password_recovery)],
    ):
        try:
            await recovery.request(
                str(payload.email),
                recovery_client_ip(request, trusted_cidrs()),
            )
        except RecoveryError as error:
            raise public_error(error) from None
        return {
            "message": "Si existe una cuenta con contraseña para ese email, recibirás un código.",
            "retry_after_seconds": 60,
        }

    @router.post("/reset-password", status_code=204)
    async def reset_password(
        payload: RecoveryReset,
        request: Request,
        recovery: Annotated[RecoverPassword, Depends(get_password_recovery)],
    ):
        try:
            await recovery.reset(
                str(payload.email),
                payload.code,
                payload.password,
                recovery_client_ip(request, trusted_cidrs()),
            )
        except RecoveryError as error:
            raise public_error(error) from None

    return router
