"""Axis reads through semantic ports: ownership, provenance and original integrity."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.contracts import content_hash
from src.core.extractors.personal_axes.models import AxisError
from src.core.extractors.personal_axes.read_models import EvidenceFacts, FindingFacts
from src.use_cases.personal_axes.exploration import AxisExploration


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def reading():
    owner, axis, version, run, finding = (uuid4() for _ in range(5))
    document = build_document(NewDocument(content="Una idea para recordar."))
    fact = FindingFacts(
        id=str(finding),
        document_id=str(document.id),
        axis_id=str(axis),
        version_id=str(version),
        run_id=str(run),
        title="Idea",
        content="Una idea.",
        tags=("Ideas",),
        content_hash=content_hash(document.content),
    )
    edge = EvidenceFacts(
        finding_id=str(finding),
        extraction_id=str(run),
        extraction_axis=str(axis),
        extraction_version=str(version),
        extraction_document=str(document.id),
        id=str(uuid4()),
        quote=document.content,
        start_char=0,
        end_char=len(document.content),
        axis_id=str(axis),
        version_id=str(version),
        run_id=str(run),
        document_id=str(document.id),
    )
    calls = []
    reader = SimpleNamespace(
        finding=AsyncMock(return_value=[fact]), evidence=AsyncMock(return_value=[edge])
    )

    @asynccontextmanager
    async def read(*args):
        calls.append(args)
        yield reader

    definitions = SimpleNamespace(get=AsyncMock(), version=AsyncMock())
    documents = SimpleNamespace(get=AsyncMock(return_value=document))
    case = AxisExploration(definitions, SimpleNamespace(read=read), documents, owner)
    return SimpleNamespace(**locals())


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["axis", "version"])
async def test_ownership_and_version_are_checked_before_opening_graph(reading, missing):
    env = reading
    code = "axis_not_found" if missing == "axis" else "axis_version_not_found"
    getattr(env.definitions, "get" if missing == "axis" else "version").side_effect = AxisError(
        code
    )
    with pytest.raises(AxisError, match=code):
        await env.case.finding(env.axis, env.finding, env.version)
    assert env.calls == []
    env.documents.get.assert_not_awaited()


@pytest.mark.anyio
async def test_read_uses_real_version_and_checks_literal_evidence_without_provider(reading):
    env = reading
    result = await env.case.finding(env.axis, env.finding, env.version)
    env.definitions.get.assert_awaited_once_with(env.owner, env.axis)
    env.definitions.version.assert_awaited_once_with(env.owner, env.axis, env.version)
    assert env.calls == [(env.axis, env.version)]
    assert result["version_id"] == str(env.version)
    assert result["evidence"][0]["quote"] == env.document.content
    assert result["source_hash"] == content_hash(env.document.content)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field",
    [
        "axis_id",
        "version_id",
        "run_id",
        "document_id",
        "extraction_id",
        "extraction_axis",
        "extraction_version",
        "extraction_document",
        "start_char",
        "quote",
    ],
)
async def test_inconsistent_relationship_evidence_is_rejected(reading, field):
    env = reading
    value = "0" if field == "start_char" else "different"
    env.reader.evidence.return_value = [env.edge.model_copy(update={field: value})]
    with pytest.raises(AxisError, match="axis_evidence_invalid"):
        await env.case.finding(env.axis, env.finding)


@pytest.mark.anyio
async def test_changed_original_is_rejected_even_when_graph_is_consistent(reading):
    env = reading
    env.documents.get.return_value = env.document.model_copy(update={"content": "Otra fuente."})
    with pytest.raises(AxisError, match="axis_source_changed"):
        await env.case.finding(env.axis, env.finding)
