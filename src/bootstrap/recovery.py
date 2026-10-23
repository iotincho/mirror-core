"""Compose recovery policy, protected state and email independently of workspaces."""

from fastapi import HTTPException
from fastapi_users.password import PasswordHelper

from src.adapters.access.api.public.auth.proxy import recovery_client_ip as recovery_client_ip
from src.adapters.access.api.public.auth.recovery import build_recovery_router
from src.adapters.providers.email.resend import ResendMailTransport
from src.adapters.providers.security.recovery import RecoverySecrets
from src.adapters.storage.postgres.recovery_repository import RecoveryRepository
from src.bootstrap.database import get_session_maker
from src.config import get_settings
from src.use_cases.auth.recover_password import RecoverPassword as RecoveryCase
from src.use_cases.auth.send_recovery_email import SendRecoveryEmail


def RecoverPassword(repository, secrets):
    return RecoveryCase(repository, secrets, PasswordHelper())


def get_recovery_repository():
    return RecoveryRepository(get_session_maker())


def recovery_configuration():
    settings = get_settings()
    if (
        not (
            settings.resend_api_key
            and settings.auth_email_from
            and settings.password_recovery_secret
        )
        or len(settings.password_recovery_secret) < 32
    ):
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


router = build_recovery_router(
    get_password_recovery,
    lambda: get_settings().password_recovery_trusted_proxy_cidrs,
)
