"""Journal-owned membership writes in the caller's acceptance/handoff transaction."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.journal_models import JournalEntryRecord, JournalInvitationRecord
from src.core.journals.contracts import EntryReference
from src.core.processing.submissions import SubmissionConflict


async def bind_journal_entry(session, owner, kind, resource_id, reference, accepted_at):
    if reference is None:
        return
    values = dict(
        owner_id=owner,
        resource_kind=kind,
        resource_id=resource_id,
        run_id=reference.run_id,
        revision=reference.run_revision,
        stage_id=reference.stage_id,
        accepted_at=accepted_at,
    )
    await session.execute(insert(JournalEntryRecord).values(**values).on_conflict_do_nothing())
    row = await session.get(JournalEntryRecord, (owner, kind, resource_id))
    if (row.run_id, row.revision, row.stage_id) != (
        reference.run_id,
        reference.run_revision,
        reference.stage_id,
    ):
        raise SubmissionConflict("journal_reference_conflict")


async def bind_derived_journal_entry(session, owner, audio_id, document_id, accepted_at):
    row = await session.scalar(
        select(JournalEntryRecord).where(
            JournalEntryRecord.owner_id == owner,
            JournalEntryRecord.resource_kind == "audio",
            JournalEntryRecord.resource_id == audio_id,
        )
    )
    if row is not None:
        await bind_journal_entry(
            session,
            owner,
            "document",
            document_id,
            EntryReference(
                run_id=row.run_id,
                run_revision=row.revision,
                stage_id=row.stage_id,
            ),
            accepted_at,
        )


async def bind_journal_invitation(session, owner, invitation_id, reference):
    session.add(
        JournalInvitationRecord(
            invitation_id=invitation_id,
            owner_id=owner,
            run_id=reference.run_id,
            revision=reference.run_revision,
            stage_id=reference.stage_id,
        )
    )
    await session.flush()
