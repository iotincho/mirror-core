"""Bind transactional acceptance to a workspace and explicit configuration snapshots."""

from src.bootstrap import processing_configuration
from src.config import get_settings
from src.observability import report_issue
from src.use_cases.processing.submit_processing import audio_manifest as audio_manifest
from src.use_cases.processing.submit_processing import audio_metadata as audio_metadata
from src.use_cases.processing.submit_processing import document_identity as document_identity
from src.use_cases.processing.submit_processing import (
    imported_document_identity as imported_document_identity,
)
from src.use_cases.processing.submit_processing import (
    verify_audio_original as verify_audio_original,
)


def document_title_specification(settings=None):
    return processing_configuration.document_title_specification(settings or get_settings())


def workflow_config():
    return processing_configuration.workflow_config(get_settings())


async def validate_invitation(session, owner, invitation_id):
    from src.adapters.storage.postgres.invitations import InvitationRepository

    await InvitationRepository(None).invitation(session, owner, invitation_id)


def build_submission_port(repository, *, submissions=None):
    from src.adapters.storage.postgres.submission_port import PostgresSubmissions
    from src.extractors.personal_axes.configuration import user_workflow_config

    return PostgresSubmissions(
        repository,
        config_factory=user_workflow_config,
        invitation_validator=validate_invitation,
        submissions=submissions,
    )


def adapt_submissions(submissions):
    from src.adapters.storage.postgres.submission_port import PostgresSubmissions

    if isinstance(submissions, PostgresSubmissions):
        return submissions
    return build_submission_port(submissions.processing, submissions=submissions)


def SubmitDocument(submissions, runtime):
    from src.use_cases.processing.submit_processing import SubmitDocument as Case

    return Case(adapt_submissions(submissions), runtime, workflow_config=workflow_config)


def SubmitAudioNote(submissions, runtime, max_bytes):
    from src.use_cases.processing.submit_processing import SubmitAudioNote as Case

    return Case(adapt_submissions(submissions), runtime, max_bytes, workflow_config=workflow_config)


async def recover_submissions(submissions, runtime_factory):
    from src.use_cases.processing.submit_processing import recover_submissions as recover

    await recover(adapt_submissions(submissions), runtime_factory, report_issue=report_issue)
