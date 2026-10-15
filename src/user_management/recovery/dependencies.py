"""Composition used identically by HTTP, dispatcher and Taskiq workers."""

from fastapi import HTTPException

from src.config import get_settings
from src.use_cases.recover_password import RecoverPassword
from src.use_cases.send_recovery_email import SendRecoveryEmail
from src.user_management.database import get_session_maker
from src.user_management.recovery.repository import RecoveryRepository
from src.user_management.recovery.resend import ResendMailTransport
from src.user_management.recovery.security import RecoverySecrets


def get_recovery_repository():
    return RecoveryRepository(get_session_maker())


def recovery_configuration():
    settings = get_settings()
    if not (
        settings.resend_api_key and settings.auth_email_from and settings.password_recovery_secret
    ):
        raise HTTPException(503, detail="recovery_not_configured")
    if len(settings.password_recovery_secret) < 32:
        raise HTTPException(503, detail="recovery_not_configured")
    return settings


def get_password_recovery():
    settings = recovery_configuration()
    return RecoverPassword(
        get_recovery_repository(), RecoverySecrets(settings.password_recovery_secret)
    )


def get_send_recovery_email():
    settings = recovery_configuration()
    return SendRecoveryEmail(
        get_recovery_repository(),
        RecoverySecrets(settings.password_recovery_secret),
        ResendMailTransport(settings.resend_api_key, settings.auth_email_from),
    )
