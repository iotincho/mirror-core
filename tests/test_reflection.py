from pathlib import Path

import pytest

from src.embeddings.contracts import SimilarClaim
from src.reflection.contracts import ClaimRelation, ReflectionObservation, ReflectionResult
from src.reflection.document_context import build_document_context
from src.services.reflection_provider import ProviderReflection
from src.services.reflection_store import FileReflectionStore
from src.use_cases.resolve_question import ReflectionRunFailedError, ResolveQuestion


def candidate() -> SimilarClaim:
    return SimilarClaim(
        claim_id="run:claim:autonomy",
        claim_local_id="autonomy",
        document_id="document",
        run_id="run",
        profile_name="v3",
        prompt_version="v3",
        text="Quiero más autonomía.",
        type="desire",
        score=0.9,
        evidence=[],
    )


class FakeSearch:
    def __init__(self, candidates: list[SimilarClaim]) -> None:
        self._candidates = candidates

    async def execute(self, question: str, limit: int) -> list[SimilarClaim]:
        assert question == "¿Qué aparece sobre autonomía?"
        assert limit == 5
        return self._candidates


class FakeContextStore:
    async def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]:
        assert claim_ids == ["run:claim:autonomy"]
        return [
            ClaimRelation(
                source_claim_id="run:claim:autonomy",
                relation_type="ABOUT",
                target_id="run:concept:autonomy",
                target_kind="concept",
                target_text="autonomía",
            )
        ]


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, result: ReflectionResult) -> None:
        self.result = result

    async def reflect(self, context, profile) -> ProviderReflection:
        assert context.claims == [candidate()]
        assert len(context.relations) == 1
        assert profile.name == "v1"
        return ProviderReflection(result=self.result, provider="fake", model="fake-model")


@pytest.mark.anyio
async def test_resolve_question_persists_only_observations_citing_retrieved_claims(
    tmp_path: Path,
) -> None:
    use_case = ResolveQuestion(
        FakeSearch([candidate()]),
        FakeContextStore(),
        FakeProvider(
            ReflectionResult(
                answer="La autonomía aparece como un deseo explícito.",
                observations=[
                    ReflectionObservation(
                        statement="El deseo de autonomía está expresado en la nota.",
                        source_claim_ids=["run:claim:autonomy"],
                    )
                ],
            )
        ),
        FileReflectionStore(tmp_path),
    )

    run = await use_case.execute("¿Qué aparece sobre autonomía?", limit=5)

    assert run.status == "completed"
    assert run.result is not None
    assert run.relations[0].relation_type == "ABOUT"
    assert (tmp_path / f"{run.id}.json").exists()


@pytest.mark.anyio
async def test_resolve_question_rejects_a_claim_not_in_the_retrieved_context(
    tmp_path: Path,
) -> None:
    use_case = ResolveQuestion(
        FakeSearch([candidate()]),
        FakeContextStore(),
        FakeProvider(
            ReflectionResult(
                answer="Respuesta no verificable.",
                observations=[
                    ReflectionObservation(
                        statement="No debe persistirse.",
                        source_claim_ids=["another-run:claim:invented"],
                    )
                ],
            )
        ),
        FileReflectionStore(tmp_path),
    )

    with pytest.raises(ReflectionRunFailedError):
        await use_case.execute("¿Qué aparece sobre autonomía?", limit=5)

    persisted = list(tmp_path.glob("*.json"))
    assert len(persisted) == 1
    assert '"status": "failed"' in persisted[0].read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_resolve_question_returns_a_persisted_insufficient_evidence_result(
    tmp_path: Path,
) -> None:
    class EmptyContextStore:
        async def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]:
            assert claim_ids == []
            return []

    use_case = ResolveQuestion(
        FakeSearch([]),
        EmptyContextStore(),
        FakeProvider(ReflectionResult(answer="No debería invocarse.")),
        FileReflectionStore(tmp_path),
    )

    run = await use_case.execute("¿Qué aparece sobre autonomía?", limit=5)

    assert run.provider == "system"
    assert run.result is not None
    assert run.result.uncertainties


def test_document_context_exposes_all_metadata_with_known_definitions() -> None:
    candidate_with_metadata = candidate().model_copy(
        update={
            "document_source": "alex-diary",
            "document_created_at": "2026-09-25T09:00:00-03:00",
            "document_authored_at": "2026-09-01T09:00:00-03:00",
            "document_metadata": {
                "note_number": "18",
                "phase": "incremental",
                "custom_field": "custom value",
            },
        }
    )

    documents, definitions = build_document_context([candidate_with_metadata])

    assert documents[0].metadata == candidate_with_metadata.document_metadata
    assert documents[0].created_at is not None
    assert documents[0].authored_at is not None
    assert definitions["authored_at"].description.startswith("When the user wrote")
    assert definitions["note_number"].description.startswith("Stable human reference")
    assert definitions["custom_field"].value_type == "string"
