"""Canonical provenance and capture resolution through owner-scoped memory ports."""

# ruff: noqa: F811
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_journals_application import anyio_backend, env  # noqa: F401

from src.core.journals.contracts import ChangeLifecycle, EntryReference
from src.core.journals.entries import (
    manifest_reference,
    metadata_reference,
    reference_manifest,
    reference_metadata,
)
from src.core.journals.errors import JournalError
from src.use_cases.journals.resolve_capture import ResolveJournalCapture


def reference():
    return EntryReference(run_id=uuid4(), stage_id=uuid4(), run_revision=1)


def test_reference_serialization_distinguishes_original_metadata_and_manifest_identity():
    item = reference()
    assert metadata_reference(reference_metadata(item)) == item
    assert manifest_reference(reference_manifest(item)) == item
    assert "journal_identity" not in reference_metadata(item)
    assert reference_manifest(item)["journal_identity"] == "entry/1"
    assert reference_manifest(None) == reference_metadata(None) == {}
    assert manifest_reference({"invitation_id": str(uuid4())}) is None
    assert metadata_reference({"title": "Texto sintético"}) is None


@pytest.mark.parametrize(
    "data",
    [
        {"journal_identity": "entry/2"},
        {"journal_identity": "entry/1"},
    ],
)
def test_unknown_or_incomplete_manifests_are_not_accepted_as_free(data):
    with pytest.raises(JournalError, match="journal_invalid_reference_format"):
        manifest_reference(data)


def test_malformed_or_overextended_reference_metadata_is_rejected():
    with pytest.raises(ValidationError):
        metadata_reference({"journal_reference": "not-json"})
    with pytest.raises(ValidationError):
        EntryReference.model_validate({**reference().model_dump(), "owner_id": uuid4()})


@pytest.mark.anyio
async def test_capture_remains_valid_after_close_without_using_the_current_stage(env):
    receipt = await env.manage.activate(env.owner, env.command, uuid4())
    item = (await env.query.resolve(env.owner, env.repo.now)).reference
    env.repo.now += timedelta(days=1)
    await env.manage.lifecycle(
        env.owner, receipt.run_id, ChangeLifecycle(expected_revision=1, action="close"), uuid4()
    )
    assert await ResolveJournalCapture(env.repo).resolve(env.owner, item) == item
    assert await ResolveJournalCapture(env.repo).resolve(env.owner, None) is None


@pytest.mark.anyio
async def test_invitation_is_authoritative_and_does_not_take_the_active_run_implicitly(env):
    await env.manage.activate(env.owner, env.command, uuid4())
    item = (await env.query.resolve(env.owner, env.repo.now)).reference
    linked, free = uuid4(), uuid4()
    env.repo.responses = {linked: item, free: None}
    resolver = ResolveJournalCapture(env.repo)
    assert await resolver.resolve(env.owner, None, invitation_id=linked) == item
    assert await resolver.resolve(env.owner, None, invitation_id=free) is None
    with pytest.raises(JournalError, match="journal_reference_conflict"):
        await resolver.resolve(env.owner, item, invitation_id=free)
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        await resolver.resolve(env.owner, None, invitation_id=uuid4())
