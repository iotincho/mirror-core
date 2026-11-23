"""Version 2 of the shared preparation workflow, pinned to immutable journal context."""

from src.core.exteriorization.journal_questions import (
    JournalPreparationConfiguration,
    JournalPreparationSnapshot,
    context_hash,
)
from src.core.processing.errors import WorkflowFailure
from src.use_cases.exteriorization.prepare_questions import (
    PrepareQuestions,
    build_snapshot,
    restore_input,
)


def generation_data(context):
    return context.model_dump(mode="json", exclude={"owner_id", "reference", "catalog"})


class PrepareJournalQuestions(PrepareQuestions):
    configuration_type = JournalPreparationConfiguration
    snapshot_type = JournalPreparationSnapshot

    async def build_snapshot(self, originals, owner, now, configuration):
        reference = configuration.journal_reference
        journal = await self.repository.journal_context(owner, reference)
        inventory = await self.repository.inventory(owner, now, journal_reference=reference)
        if len(inventory[2]) > 64:
            raise WorkflowFailure("question_topic_inventory_limit")
        snapshot = JournalPreparationSnapshot(
            captured_at=now,
            sources=(),
            history=tuple(inventory[1]),
            topics=tuple(inventory[2]),
            journal_reference=reference,
            context_hash=context_hash(journal),
        )
        return await build_snapshot(
            self.repository,
            originals,
            owner,
            now,
            configuration,
            inventory=inventory,
            snapshot=snapshot,
            journal_context=generation_data(journal),
            max_age_days=None,
        )

    async def restore_input(self, snapshot, originals, owner):
        identifiers = {source.document_id for source in snapshot.sources}
        members = await self.repository.journal_sources(
            owner, snapshot.journal_reference, identifiers
        )
        if members != identifiers:
            raise WorkflowFailure("question_evidence_unavailable")
        journal = await self.repository.journal_context(owner, snapshot.journal_reference)
        if context_hash(journal) != snapshot.context_hash:
            raise WorkflowFailure("question_journal_context_changed")
        data = await restore_input(snapshot, originals)
        data["journal_context"] = generation_data(journal)
        return data
