"""Document state machine; artifacts survive retries independently of the broker."""

from __future__ import annotations

import hashlib
from uuid import uuid5

from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError

from src.embeddings.contracts import DocumentEmbeddingRecord, EmbeddingVector
from src.extraction.profiles import get_profile
from src.processing.artifacts import ProcessingArtifacts
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for
from src.services.extraction_store import ExtractionRun
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.extract_document import resolve_evidence, validate_evidence
from src.use_cases.submit_processing import document_identity

VECTORS = TypeAdapter(list[EmbeddingVector])


class ProcessDocument:
    transitions = frozenset(
        {
            ("extraction", "graph_persistence"),
            ("graph_persistence", "claim_embeddings"),
            ("claim_embeddings", "document_embedding"),
            ("document_embedding", "done"),
        }
    )

    def __init__(self, runtime_factory, provider_factory):
        self.runtime_factory, self.provider_factory = runtime_factory, provider_factory

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        record = context.record
        service = "extraction"
        try:
            async with self.runtime_factory(record.user_id) as runtime:
                document = await runtime.document_store.get(record.resource_id)
                config = record.config
                profile = get_profile(config["profile"])
                if (
                    profile.prompt_version != config["prompt_version"]
                    or profile.schema_version != config["schema_version"]
                    or hashlib.sha256(profile.instructions.encode()).hexdigest()
                    != config["prompt_hash"]
                ):
                    raise WorkflowFailure("workflow_configuration_changed")
                extractor, _, embedder = self.provider_factory(config)
                artifacts = ProcessingArtifacts(
                    runtime.context.filesystem_root / "processing" / str(record.id)
                )
                identity = document_identity(document) + ":" + artifacts.digest(config)
                run_id = uuid5(record.id, "extraction")
                payload = await artifacts.read("extraction", identity)
                if record.stage == "extraction":
                    if payload is None:
                        await context.assert_lease()
                        try:
                            response = await extractor.extract(document, profile)
                            result = resolve_evidence(document.content, response.result)
                            validate_evidence(document.content, result)
                        except Exception as error:
                            failure = ExtractionRun(
                                id=uuid5(record.id, f"failed:{record.attempts}"),
                                document_id=document.id,
                                profile_name=profile.name,
                                schema_version=profile.schema_version,
                                prompt_version=profile.prompt_version,
                                provider=extractor.provider_name,
                                model=extractor.model_name,
                                status="failed",
                                created_at=record.created_at,
                                error=type(error).__name__,
                            )
                            await context.assert_lease()
                            await runtime.extraction_store.save(failure)
                            raise
                        run = ExtractionRun(
                            id=run_id,
                            document_id=document.id,
                            profile_name=profile.name,
                            schema_version=profile.schema_version,
                            prompt_version=profile.prompt_version,
                            provider=response.provider,
                            model=response.model,
                            status="completed",
                            created_at=record.created_at,
                            result=result,
                            response_id=response.response_id,
                            usage=response.usage,
                        )
                        payload = run.model_dump(mode="json")
                        await context.assert_lease()
                        await artifacts.write("extraction", identity, payload)
                    run = ExtractionRun.model_validate(payload)
                    await context.assert_lease()
                    await runtime.extraction_store.save(run)
                    if run.result.title:
                        document = await runtime.document_store.update_title(
                            document.id, run.result.title
                        )
                    await context.advance(
                        "graph_persistence",
                        extraction_run_id=str(run.id),
                        extraction_hash=artifacts.digest(payload),
                    )
                if payload is None:
                    raise WorkflowFailure("extraction_artifact_missing")
                run = ExtractionRun.model_validate(payload)
                if run.document_id != document.id or run.id != run_id:
                    raise WorkflowFailure("extraction_artifact_mismatch")
                if record.stage == "graph_persistence":
                    service = "graph"
                    await context.assert_lease()
                    # Deterministic IDs + MERGE permit replay after an ambiguous commit.
                    await runtime.graph_store.persist_verified(document, run)
                    await context.advance("claim_embeddings", graph_run_id=str(run.id))
                if record.stage == "claim_embeddings":
                    service = "embeddings"
                    claims = run.result.claims
                    vectors = await self.vectors(
                        context,
                        artifacts,
                        "claims",
                        identity,
                        [claim.text for claim in claims],
                        embedder,
                    )
                    if vectors:
                        spec = vectors[0].spec
                        records = [
                            EmbedClaims._record(
                                document, run, claim.id, claim.text, vector.vector, spec
                            )
                            for claim, vector in zip(claims, vectors, strict=True)
                        ]
                        await context.assert_lease()
                        await runtime.graph_store.persist_claim_embeddings(
                            records, spec, verify=True
                        )
                    await context.advance("document_embedding", claim_embeddings_count=len(vectors))
                if record.stage == "document_embedding":
                    service = "embeddings"
                    vectors = await self.vectors(
                        context, artifacts, "document", identity, [document.content], embedder
                    )
                    vector = vectors[0]
                    text_hash = hashlib.sha256(document.content.encode()).hexdigest()
                    embedding = DocumentEmbeddingRecord(
                        id=f"{document.id}:embedding:{vector.spec.index_suffix}:{text_hash[:16]}",
                        document_id=str(document.id),
                        text_hash=text_hash,
                        content=document.content,
                        source=document.source,
                        metadata=document.metadata,
                        created_at=document.created_at,
                        authored_at=document.authored_at,
                        vector=vector.vector,
                        spec=vector.spec,
                    )
                    await context.assert_lease()
                    await runtime.graph_store.persist_document_embedding(
                        embedding, vector.spec, verify=True
                    )
                    await context.advance("done", document_embedding_id=embedding.id)
        except (WorkflowFailure, LeaseLost, SQLAlchemyError):
            raise
        except Exception as error:
            raise failure_for(error, record.stage_attempts, service) from error

    @staticmethod
    async def vectors(context, artifacts, name, identity, texts, provider):
        if not texts:
            return []
        payload = await artifacts.read(name, identity)
        if payload is None:
            await context.assert_lease()
            vectors = await provider.embed(texts)
            if (
                len(vectors) != len(texts)
                or any(len(vector.vector) != vector.spec.dimensions for vector in vectors)
                or any(vector.spec != vectors[0].spec for vector in vectors)
            ):
                raise WorkflowFailure("invalid_embedding_response")
            payload = VECTORS.dump_python(vectors, mode="json")
            await context.assert_lease()
            await artifacts.write(name, identity, payload)
        return VECTORS.validate_python(payload)
