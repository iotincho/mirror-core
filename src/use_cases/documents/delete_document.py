from contextlib import suppress
from uuid import UUID

from src.core.documents.ports import DocumentNotFoundError, DocumentStore
from src.core.graph.ports import GraphStore


class DeleteDocument:
    def __init__(
        self,
        documents: DocumentStore,
        graph: GraphStore,
        processing=None,
        user_id=None,
        layer_artifacts=None,
        delete_processing_artifacts=None,
    ) -> None:
        self._documents = documents
        self._graph = graph
        self._processing, self._user_id = processing, user_id
        self._layer_artifacts = layer_artifacts
        self._delete_processing_artifacts = delete_processing_artifacts

    async def execute(self, document_id: UUID) -> None:
        if self._processing is not None:
            from src.core.processing.submissions import SubmissionConflict

            async with self._processing.lock_resource(self._user_id, document_id) as locked:
                if not locked:
                    raise SubmissionConflict("processing_active")
                try:
                    await self._processing.assert_inactive(self._user_id, document_id)
                except ValueError as error:
                    raise SubmissionConflict("processing_active") from error
                await self._documents.get(document_id)
                await self._processing.mark_deleted(self._user_id, document_id)
                if self._delete_processing_artifacts is not None:
                    async with self._processing.transaction() as transaction:
                        jobs = await transaction.jobs_for_resources(self._user_id, [document_id])
                    for job in jobs:
                        await self._delete_processing_artifacts(job.id)
                await self.delete_content(document_id)
            return
        await self._documents.get(document_id)
        await self.delete_content(document_id)

    async def delete_content(self, document_id: UUID) -> None:
        """Remove the content of a document already guarded by its caller."""
        await self._graph.delete_document(str(document_id))
        if self._layer_artifacts is not None:
            await self._layer_artifacts.delete_for_document(document_id)
        with suppress(DocumentNotFoundError):
            await self._documents.delete(document_id)
