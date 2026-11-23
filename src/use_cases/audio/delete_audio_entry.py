from typing import Protocol
from uuid import UUID

from src.core.audio.errors import AudioNoteNotFoundError
from src.core.domain.audio_notes import AudioNote
from src.core.processing.submissions import SubmissionConflict
from src.core.processing.transactions import ProcessingRequests
from src.use_cases.documents.delete_document import DeleteDocument


class AudioOriginals(Protocol):
    async def get(self, note_id: UUID) -> AudioNote: ...

    async def delete(self, note: AudioNote) -> None: ...


class AudioDocuments(Protocol):
    async def audio_document_ids(self, audio_id: UUID) -> set[UUID]: ...


class DeleteAudioEntry:
    """Delete one logical entry under the guards of its audio and derived documents."""

    def __init__(
        self,
        owner: UUID,
        audio: AudioOriginals,
        documents: AudioDocuments,
        delete_document: DeleteDocument,
        processing: ProcessingRequests,
        delete_processing_artifacts,
    ) -> None:
        self._owner = owner
        self._audio = audio
        self._documents = documents
        self._delete_document = delete_document
        self._processing = processing
        self._delete_processing_artifacts = delete_processing_artifacts

    async def execute(self, audio_id: UUID, *, by_upload_key: bool = False) -> None:
        if by_upload_key:
            async with self._processing.transaction() as transaction:
                receipt = await transaction.receipt(self._owner, "upload_audio", audio_id)
            if receipt is None:
                raise AudioNoteNotFoundError("Audio entry not found")
            if receipt.accepted_at is None:
                raise SubmissionConflict("upload_in_progress")
            audio_id = receipt.resource_id

        _, document_ids = await self._find_entry(audio_id)
        resource_ids = document_ids | {audio_id}
        async with self._processing.lock_resources(self._owner, sorted(resource_ids)) as locked:
            if not locked:
                raise SubmissionConflict("processing_active")
            note, document_ids = await self._find_entry(audio_id)
            if not document_ids.issubset(resource_ids):
                raise SubmissionConflict("processing_active")
            try:
                for identifier in sorted(resource_ids):
                    await self._processing.assert_inactive(self._owner, identifier)
            except ValueError as error:
                raise SubmissionConflict("processing_active") from error

            async with self._processing.transaction() as transaction:
                jobs = await transaction.jobs_for_resources(self._owner, sorted(resource_ids))
            for identifier in sorted(resource_ids):
                await self._processing.mark_deleted(self._owner, identifier)
            for job in jobs:
                await self._delete_processing_artifacts(job.id)
            for document_id in sorted(document_ids):
                await self._delete_document.delete_content(document_id)
            if note is not None:
                await self._audio.delete(note)

    async def _find_entry(self, audio_id: UUID) -> tuple[AudioNote | None, set[UUID]]:
        try:
            note = await self._audio.get(audio_id)
        except AudioNoteNotFoundError:
            note = None
        document_ids = await self._documents.audio_document_ids(audio_id)
        if note is None and not document_ids:
            raise AudioNoteNotFoundError("Audio entry not found")
        if note is not None and note.document_id is not None:
            document_ids.add(note.document_id)
        return note, document_ids
