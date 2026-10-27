"""Historical planning and write contexts through memory ports."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.domain.documents import NewDocument, build_document
from src.core.extractors.contracts import ExtractorProfile, content_hash
from src.core.extractors.personal_axes.configuration import with_axes
from src.core.extractors.personal_axes.definitions import AxisDefinition, AxisVersion
from src.core.extractors.personal_axes.history import HistoryRequest
from src.core.extractors.personal_axes.models import AxisError, AxisSpecification, AxisWriteContext
from src.core.processing.models import ProcessingJob
from src.use_cases.personal_axes.history import AxisHistory
from src.use_cases.personal_axes.persist import PersistPersonalAxis


@pytest.fixture
def anyio_backend():
    return "asyncio"


def definition():
    spec = AxisSpecification(
        profile=ExtractorProfile(id="fixture", instructions="Ideas."), model="fixture-model"
    )
    version = AxisVersion(
        id=uuid4(),
        number=1,
        title="Ideas",
        purpose="Recordar ideas",
        specification=spec.model_dump(mode="json"),
        specification_hash=spec.fingerprint,
        created_at=datetime.now(UTC),
    )
    return AxisDefinition(id=uuid4(), enabled=True, current_version_id=version.id, version=version)


def test_axis_snapshot_is_detached_and_preserves_profile_and_branch_identity():
    axis = definition()
    baseline = {"extractors": [{"name": "emotions"}], "document_workflow_version": 4}
    frozen = with_axes(baseline, [axis])
    assert baseline == {"extractors": [{"name": "emotions"}], "document_workflow_version": 4}
    assert frozen["document_workflow_version"] == 5
    assert frozen["extractors"][0] == {"name": "emotions", "key": "emotions"}
    branch = frozen["extractors"][1]
    assert branch["key"] == f"axis:{axis.id}"
    assert branch["version_id"] == str(axis.version.id)
    assert branch["specification"] == axis.version.specification
    frozen["extractors"][1]["specification"]["model"] = "changed-copy"
    assert axis.version.specification["model"] == "fixture-model"


@pytest.mark.anyio
async def test_persistence_receives_each_typed_context_without_mutating_the_extractor():
    owner, axis, version = uuid4(), uuid4(), uuid4()
    original = AxisWriteContext("unchanged")
    extractor = SimpleNamespace(write_context=original, persist=AsyncMock())
    contexts = SimpleNamespace(for_reservation=AsyncMock(return_value=AxisWriteContext("reserved")))
    case = PersistPersonalAxis(contexts)
    record = ProcessingJob(
        user_id=owner,
        workflow="extractor",
        resource_kind="document",
        resource_id=uuid4(),
        stage="persistence",
        config={"extractor": {"axis_id": str(axis), "version_id": str(version)}},
    )
    output = object()
    await case.execute(extractor, output, record)
    contexts.for_reservation.assert_awaited_once_with(owner, record.id, axis, version)
    extractor.persist.assert_awaited_once_with(output, write_context=AxisWriteContext("reserved"))
    assert extractor.write_context is original


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["version", "source"])
async def test_all_sources_and_version_are_verified_before_creating_batch_or_jobs(invalid):
    owner, axis = uuid4(), definition()
    document = build_document(NewDocument(content="Una idea sintética."))
    unit = SimpleNamespace(definition=axis, create_batch=AsyncMock(), create_jobs=AsyncMock())
    committed = []

    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield unit
        committed.append(True)

    @asynccontextmanager
    async def guard(*args):
        yield True

    store = SimpleNamespace(
        previous=AsyncMock(return_value=None), guard=guard, transaction=transaction
    )
    originals = SimpleNamespace(get=AsyncMock(return_value=document))
    case = AxisHistory(owner, originals, None, None, store)
    body = HistoryRequest(
        version_id=uuid4() if invalid == "version" else axis.version.id,
        documents=[
            {
                "document_id": document.id,
                "source_hash": "0" * 64 if invalid == "source" else content_hash(document.content),
            }
        ],
    )
    with pytest.raises(
        AxisError,
        match="axis_base_version_conflict" if invalid == "version" else "axis_source_changed",
    ):
        await case.start(axis.id, body, uuid4())
    assert not committed
    unit.create_batch.assert_not_awaited()
    unit.create_jobs.assert_not_awaited()
