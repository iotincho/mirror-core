"""Composition shared by HTTP, dispatcher and workers."""

from src.bootstrap.database import get_session_maker
from src.config import get_settings
from src.exteriorization.repository import InvitationError, InvitationRepository
from src.exteriorization.web_push import WebPushTransport
from src.use_cases.configure_invitations import ConfigureInvitations
from src.use_cases.send_invitation import SendInvitation


def get_invitation_repository() -> InvitationRepository:
    return InvitationRepository(get_session_maker())


def get_invitations() -> ConfigureInvitations:
    return ConfigureInvitations(get_invitation_repository())


def get_send_invitation() -> SendInvitation:
    return SendInvitation(get_invitation_repository(), WebPushTransport(get_settings()))


def require_push_configuration() -> None:
    settings = get_settings()
    if not (
        settings.web_push_public_key and settings.web_push_private_key and settings.web_push_subject
    ):
        raise InvitationError("web_push_not_configured", 503)
