"""Compose portable import/export and guarded deletion with durable request ports."""

from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.submissions import SubmissionRepository
from src.bootstrap.acceptance import validate_invitation, workflow_config
from src.bootstrap.processing import requests_store
from src.core.documents.archive import ArchiveConflict as ArchiveConflict
from src.core.documents.archive import ArchivedDocument as ArchivedDocument
from src.core.documents.archive import DocumentArchive as DocumentArchive


def DocumentArchiveTransfer(
    documents, processing=None, user_id=None, submissions=None, *, graph=None
):
    from src.adapters.storage.postgres.submission_port import PostgresSubmissions
    from src.adapters.storage.postgres.submissions import SubmissionRepository as SQLSubmissions
    from src.use_cases.documents.archive import DocumentArchiveTransfer as Case

    if submissions is None and processing is not None:
        submissions = SubmissionRepository(processing)
    if isinstance(submissions, SQLSubmissions):
        # Historical archive imports use the ordinary layer snapshot, without resolving axes.
        submissions = PostgresSubmissions(
            processing,
            submissions=submissions,
            config_factory=None,
            invitation_validator=validate_invitation,
        )
    if isinstance(processing, ProcessingRepository):
        processing = requests_store(processing)
    return Case(
        documents, processing, user_id, submissions, graph=graph, workflow_config=workflow_config
    )


def build_delete_document(documents, graph, processing=None, user_id=None, layer_artifacts=None):
    from src.use_cases.documents.delete_document import DeleteDocument

    if isinstance(processing, ProcessingRepository):
        processing = requests_store(processing)
    return DeleteDocument(documents, graph, processing, user_id, layer_artifacts)
