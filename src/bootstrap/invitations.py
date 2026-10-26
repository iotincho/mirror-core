"""Compose invitation actions and bounded Web Push adapters for API/workers/dispatcher."""

from src.adapters.providers.web_push.configuration import PushConfiguration
from src.adapters.providers.web_push.transport import WebPushTransport as Transport
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.bootstrap.database import get_session_maker
from src.config import get_settings
from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations
from src.use_cases.exteriorization.send_invitation import SendInvitation


def get_invitation_repository():
    return InvitationRepository(get_session_maker())


def WebPushTransport(settings):
    return Transport(settings.web_push_private_key, settings.web_push_subject)


def build_invitations(repository):
    settings = get_settings()
    return ConfigureInvitations(
        repository,
        push=PushConfiguration(
            settings.web_push_public_key,
            settings.web_push_private_key,
            settings.web_push_subject,
            settings.web_push_allowed_hosts,
        ),
    )


def get_invitations():
    return build_invitations(get_invitation_repository())


def get_send_invitation():
    return SendInvitation(get_invitation_repository(), WebPushTransport(get_settings()))
