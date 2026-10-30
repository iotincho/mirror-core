"""Coordinate public ingestion, snapshots and requests through application ports."""

from src.core.processing.reads import ProcessingNotFound, ProcessingReads
from src.use_cases.documents.ingest_document_file import IngestDocumentFile

INTERNAL_WORKFLOWS = frozenset(
    {
        "invitation_push",
        "question_preparation",
        "password_recovery_email",
        "axis_preview",
        "axis_history_note",
    }
)


class PublicProcessing:
    def __init__(self, runtime, reads: ProcessingReads, submissions, audio, requests, titles):
        self.runtime, self.reads = runtime, reads
        self.submissions, self.audio = submissions, audio
        self.requests, self.titles = requests, titles

    @property
    def changed(self):
        return self.requests.changed

    async def submit_document(
        self, original, key, *, invitation_id=None, invitation_question_id=None
    ):
        return await self.submissions.execute(
            original,
            key,
            invitation_id=invitation_id,
            invitation_question_id=invitation_question_id,
        )

    async def submit_file(self, filename, content, document_id, authored_at, key):
        original = IngestDocumentFile(self.runtime.document_store).build_new_document(
            filename, content, document_id, authored_at
        )
        return await self.submit_document(original, key)

    async def submit_audio(
        self,
        filename,
        media_type,
        content,
        authored_at,
        key,
        invitation_id,
        invitation_question_id=None,
    ):
        return await self.audio.execute(
            filename,
            media_type,
            content,
            authored_at,
            key,
            invitation_id=invitation_id,
            invitation_question_id=invitation_question_id,
        )

    async def list(self, *, active, cursor, limit):
        return await self.reads.list_for_owner(
            self.runtime.context.user_id, active=active, cursor=cursor, limit=limit
        )

    async def get(self, processing_id):
        record = await self.reads.get(processing_id, self.runtime.context.user_id)
        if record is None or record.workflow in INTERNAL_WORKFLOWS:
            raise ProcessingNotFound()
        return record

    async def children(self, processing_id):
        record = await self.get(processing_id)
        return await self.reads.extractor_children(record.id, self.runtime.context.user_id)

    async def retry(self, processing_id, key):
        return await self.requests.retry(processing_id, key)

    async def reprocess_document(self, document_id, key):
        return await self.requests.reprocess_document(document_id, key)

    async def reprocess_documents(self, document_ids, key):
        return await self.requests.reprocess_documents(document_ids, key)

    async def recover_audio(self, audio_note_id, key):
        return await self.requests.recover_audio(audio_note_id, key)

    async def _snapshot(self, original, workflow):
        record = await self.reads.latest(self.runtime.context.user_id, original.id, workflow)
        return original, record

    async def documents(self):
        originals = await self.runtime.document_store.list()
        await self.titles.execute(originals)
        return [await self._snapshot(original, "document") for original in originals]

    async def document(self, document_id):
        original = await self.runtime.document_store.get(document_id)
        await self.titles.execute([original])
        return await self._snapshot(original, "document")

    async def audio_note(self, audio_note_id):
        return await self._snapshot(await self.runtime.audio_note_store.get(audio_note_id), "audio")
