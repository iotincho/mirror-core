"""Prepare bounded proposals with durable replay; publication stays in the scheduler."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from src.core.documents.original_access import OwnerOriginals
from src.core.documents.ports import DocumentNotFoundError
from src.core.exteriorization.personalization import (
    PreparationConfiguration,
    PreparationSnapshot,
    SourceReference,
    content_hash,
    encoded_input,
    validate_proposals,
)
from src.core.exteriorization.preparation_ports import (
    PreparationArtifacts,
    PreparationProvider,
    Preparations,
)
from src.core.processing.errors import LeaseLost, StorageUnavailable, WorkflowFailure
from src.core.processing.workflows import WorkflowDefinition


async def build_snapshot(repository, originals, owner, now, configuration):
    inventory, history, topics = await repository.inventory(owner, now)
    if len(topics) > 64:
        raise WorkflowFailure("question_topic_inventory_limit")
    snapshot = PreparationSnapshot(
        captured_at=now, sources=(), history=tuple(history), topics=tuple(topics)
    )
    data = snapshot.model_dump(mode="json")
    data["sources"] = []
    # UTF-8 bytes conservatively bound text tokens, reserving instructions/schema overhead.
    budget = configuration.max_input_tokens - 7000
    references = []
    for identifier, accepted_at in inventory[:20]:
        try:
            document = await originals.get(identifier)
        except DocumentNotFoundError:
            continue
        authored = document.authored_at or document.created_at
        if not now - timedelta(days=30) <= authored <= now:
            continue
        source = SourceReference(
            document_id=document.id,
            sha256=content_hash(document),
            authored_at=authored,
            accepted_at=accepted_at,
            excerpt_chars=len(document.content),
            truncated=False,
        )
        available = budget - len(encoded_input(data).encode("utf-8")) - 500
        if available < 128:
            break
        excerpt = document.content.encode("utf-8")[: min(available, 2400)].decode(
            "utf-8", errors="ignore"
        )
        if not excerpt.strip():
            continue
        source = source.model_copy(
            update={
                "excerpt_chars": len(excerpt),
                "truncated": len(excerpt) < len(document.content),
            }
        )
        references.append(source)
        data["sources"].append({**source.model_dump(mode="json"), "content": excerpt})
    if len(encoded_input(data).encode("utf-8")) > budget:
        raise WorkflowFailure("question_context_budget")
    return snapshot.model_copy(update={"sources": tuple(references)}), data


async def restore_input(snapshot, originals):
    data = snapshot.model_dump(mode="json")
    data["sources"] = []
    for source in snapshot.sources:
        try:
            document = await originals.get(source.document_id)
        except DocumentNotFoundError:
            raise WorkflowFailure("question_evidence_unavailable") from None
        if content_hash(document) != source.sha256:
            raise WorkflowFailure("question_evidence_changed")
        data["sources"].append(
            {**source.model_dump(mode="json"), "content": document.content[: source.excerpt_chars]}
        )
    return data


class PrepareQuestions:
    transitions = frozenset(
        {
            ("question_context", "question_proposals"),
            ("question_proposals", "question_selection"),
            ("question_selection", "done"),
        }
    )

    def __init__(
        self,
        repository: Preparations,
        originals: OwnerOriginals,
        artifact_factory: Callable[[UUID, UUID], PreparationArtifacts],
        provider_factory: Callable[[PreparationConfiguration], PreparationProvider],
        select,
    ):
        self.repository, self.originals = repository, originals
        self.artifact_factory, self.provider_factory, self.select = (
            artifact_factory,
            provider_factory,
            select,
        )

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        try:
            owner, identifier = context.record.user_id, context.record.resource_id
            live = await self.repository.live(owner, identifier)
            if live is None:
                return
            configuration = PreparationConfiguration.model_validate(context.record.config)
            store = self.artifact_factory(owner, identifier)
            originals = await self.originals.documents(owner)
            identity = str(identifier)
            if context.record.stage == "question_context":
                saved = await store.read("context", identity)
                if saved is None:
                    snapshot, _ = await build_snapshot(
                        self.repository, originals, owner, live["now"], configuration
                    )
                    await context.assert_lease()
                    await store.write("context", identity, snapshot.model_dump(mode="json"))
                await context.advance("question_proposals")
            snapshot = PreparationSnapshot.model_validate(await store.read("context", identity))
            if context.record.stage == "question_proposals":
                saved = await store.read("proposals", identity)
                if saved is None:
                    if snapshot.sources:
                        data = await restore_input(snapshot, originals)
                        provider = self.provider_factory(configuration)
                        await context.assert_lease()
                        live = await self.repository.live(owner, identifier)
                        if live is None:
                            return
                        remaining = (live["due_at"] - live["now"]).total_seconds()
                        if remaining <= 0:
                            return
                        async with asyncio.timeout(min(configuration.timeout_seconds, remaining)):
                            result, usage = await provider.propose(data)
                        result = validate_proposals(result, snapshot)
                        saved = {"result": result.model_dump(mode="json"), "usage": usage}
                    else:
                        saved = {"result": {"proposals": []}, "usage": {}}
                    await context.assert_lease()
                    if await self.repository.live(owner, identifier) is None:
                        return
                    await store.write("proposals", identity, saved)
                await context.advance("question_selection")
            if context.record.stage == "question_selection":
                saved = await store.read("proposals", identity)
                proposals = validate_proposals(saved["result"], snapshot)
                # Sources are revalidated again before final publication.
                await restore_input(snapshot, originals)
                selection = await store.read("selection", identity)
                if selection is None:
                    selection = self.select(identifier, owner, snapshot, proposals)
                    await context.assert_lease()
                    await store.write("selection", identity, selection)
                await context.assert_lease()
                await self.repository.accept(context, snapshot, proposals, selection)
                await context.advance("done")
            if context.record.stage != "done":
                raise WorkflowFailure("invalid_workflow_stage")
        except (LeaseLost, StorageUnavailable, WorkflowFailure):
            raise
        except OSError:
            raise StorageUnavailable("question_original_storage") from None
        except Exception:
            # Validation/provider errors may embed private text. Do not retain chains.
            raise WorkflowFailure("question_preparation_failed") from None
