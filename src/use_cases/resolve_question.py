"""Retrieve evidence, invoke a resolver, and persist a verifiable reflection."""

import logging

from src.reflection.contracts import ReflectionContext, ReflectionResult
from src.reflection.document_context import build_document_context
from src.reflection.profiles import get_profile
from src.services.reflection_context_store import (
    ReflectionContextStore,
    ReflectionContextStoreError,
)
from src.services.reflection_provider import ReflectionProvider, ReflectionProviderError
from src.services.reflection_store import ReflectionRun, ReflectionStore, new_reflection_run
from src.use_cases.search_similar_claims import SearchSimilarClaims, SemanticSearchFailedError

logger = logging.getLogger(__name__)


class ReflectionEvidenceError(RuntimeError):
    """The provider cited material outside the retrieved context."""


class ReflectionRunFailedError(RuntimeError):
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        super().__init__(f"Reflection run {run_id} failed")


class ResolveQuestion:
    def __init__(
        self,
        search_claims: SearchSimilarClaims,
        context_store: ReflectionContextStore,
        provider: ReflectionProvider,
        store: ReflectionStore,
    ) -> None:
        self._search_claims = search_claims
        self._context_store = context_store
        self._provider = provider
        self._store = store

    async def execute(
        self, question: str, limit: int = 10, profile_name: str = "v1"
    ) -> ReflectionRun:
        if not question.strip() or not 1 <= limit <= 50:
            raise ValueError("question must not be blank and limit must be between 1 and 50")
        profile = get_profile(profile_name)
        try:
            candidates = await self._search_claims.execute(question, limit)
            relations = await self._context_store.get_claim_relations(
                [claim.claim_id for claim in candidates]
            )
        except (SemanticSearchFailedError, ReflectionContextStoreError) as error:
            logger.exception(
                "reflection_context_failed question_length=%s limit=%s error_type=%s",
                len(question),
                limit,
                type(error).__name__,
            )
            raise ReflectionRunFailedError("unpersisted") from error

        if not candidates:
            run = new_reflection_run(
                question=question,
                profile_name=profile.name,
                prompt_version=profile.prompt_version,
                provider="system",
                model="not-invoked",
                status="completed",
                candidates=[],
                relations=[],
                result=ReflectionResult(
                    answer="No encontré material recuperado que permita responder esta pregunta.",
                    uncertainties=["La evidencia disponible no fue suficiente para una reflexión."],
                ),
            )
            await self._store.save(run)
            return run

        documents, metadata_definitions = build_document_context(candidates)
        context = ReflectionContext(
            question=question,
            claims=candidates,
            relations=relations,
            documents=documents,
            metadata_definitions=metadata_definitions,
        )
        try:
            provider_reflection = await self._provider.reflect(context, profile)
            self._validate_sources(provider_reflection.result, candidates)
            run = new_reflection_run(
                question=question,
                profile_name=profile.name,
                prompt_version=profile.prompt_version,
                provider=provider_reflection.provider,
                model=provider_reflection.model,
                status="completed",
                candidates=candidates,
                relations=relations,
                result=provider_reflection.result,
                response_id=provider_reflection.response_id,
                usage=provider_reflection.usage,
            )
            await self._store.save(run)
            logger.info(
                "reflection_completed run_id=%s claims=%s relations=%s observations=%s",
                run.id,
                len(candidates),
                len(relations),
                len(run.result.observations),
            )
            return run
        except (ReflectionProviderError, ReflectionEvidenceError) as error:
            run = new_reflection_run(
                question=question,
                profile_name=profile.name,
                prompt_version=profile.prompt_version,
                provider=self._provider.provider_name,
                model=self._provider.model_name,
                status="failed",
                candidates=candidates,
                relations=relations,
                error=type(error).__name__,
            )
            await self._store.save(run)
            logger.exception(
                "reflection_failed run_id=%s claims=%s relations=%s error_type=%s",
                run.id,
                len(candidates),
                len(relations),
                type(error).__name__,
            )
            raise ReflectionRunFailedError(str(run.id)) from error

    @staticmethod
    def _validate_sources(result: ReflectionResult, candidates: list) -> None:
        allowed_ids = {claim.claim_id for claim in candidates}
        cited_ids = {
            claim_id
            for observation in result.observations
            for claim_id in observation.source_claim_ids
        }
        if not cited_ids.issubset(allowed_ids):
            raise ReflectionEvidenceError("Reflection cited a claim outside the retrieved context")
