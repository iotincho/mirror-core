"""Read journal snapshots inside the caller's SQL transaction; calendars stay in core."""

from sqlalchemy import select

from src.adapters.storage.postgres.journal_models import JournalEntryRecord, JournalStageRecord
from src.adapters.storage.postgres.journals import JournalTransaction
from src.core.journals.contracts import JournalQuestionContext, question_context
from src.core.processing.errors import WorkflowFailure


async def current_question_context(session, owner, due):
    run = await JournalTransaction(session, owner, None).current()
    return question_context(owner, run, due)


async def archived_question_context(session, owner, reference):
    run = await JournalTransaction(session, owner, None).run(
        reference.run_id, reference.run_revision
    )
    stage = (
        next((stage for stage in run.stages if stage.id == reference.stage_id), None)
        if run
        else None
    )
    if stage is None:
        raise WorkflowFailure("question_journal_context_unavailable")
    context = question_context(owner, run, stage.starts_at)
    if not isinstance(context, JournalQuestionContext) or context.reference != reference:
        raise WorkflowFailure("question_journal_context_unavailable")
    return context


def journal_source_query(owner, reference):
    stage = JournalStageRecord
    position = (
        select(stage.position)
        .where(
            stage.owner_id == owner,
            stage.run_id == reference.run_id,
            stage.revision == reference.run_revision,
            stage.stage_id == reference.stage_id,
        )
        .correlate(None)
        .scalar_subquery()
    )
    eligible = select(stage.stage_id).where(
        stage.owner_id == owner,
        stage.run_id == reference.run_id,
        stage.revision == reference.run_revision,
        stage.position <= position,
    )
    return select(JournalEntryRecord.resource_id, JournalEntryRecord.accepted_at).where(
        JournalEntryRecord.owner_id == owner,
        JournalEntryRecord.run_id == reference.run_id,
        JournalEntryRecord.resource_kind == "document",
        JournalEntryRecord.stage_id.in_(eligible),
    )


async def journal_source_ids(session, owner, reference, identifiers):
    return set(
        await session.scalars(
            journal_source_query(owner, reference)
            .with_only_columns(
                JournalEntryRecord.resource_id,
            )
            .where(JournalEntryRecord.resource_id.in_(identifiers))
        )
    )
