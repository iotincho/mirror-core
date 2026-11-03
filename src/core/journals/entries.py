"""Canonical journal provenance without changing identities of unassociated originals."""

from src.core.journals.contracts import EntryReference
from src.core.journals.errors import JournalError

REFERENCE_KEY = "journal_reference"
IDENTITY_KEY = "journal_identity"
IDENTITY_VERSION = "entry/1"


def metadata_reference(metadata: dict[str, str]) -> EntryReference | None:
    raw = metadata.get(REFERENCE_KEY)
    return EntryReference.model_validate_json(raw) if raw is not None else None


def reference_metadata(reference: EntryReference | None) -> dict[str, str]:
    return {REFERENCE_KEY: reference.model_dump_json()} if reference is not None else {}


def reference_manifest(reference: EntryReference | None) -> dict[str, str]:
    if reference is None:
        return {}
    return {IDENTITY_KEY: IDENTITY_VERSION, **reference_metadata(reference)}


def manifest_reference(manifest: dict) -> EntryReference | None:
    if IDENTITY_KEY not in manifest:
        return None
    if manifest[IDENTITY_KEY] != IDENTITY_VERSION or REFERENCE_KEY not in manifest:
        raise JournalError("journal_invalid_reference_format")
    return metadata_reference(manifest)
