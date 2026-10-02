"""Resolve proposed source-only additions and their stable graph identities."""

import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from src.domain.documents import Document
from src.extraction.contracts import ExtractionResult
from src.services.extraction_store import ExtractionRun
from src.use_cases.extract_document import resolve_evidence, validate_evidence


def item_identity(kind: str, item: dict) -> tuple[str, str, str]:
    value = item.get("text") if kind == "claim" else item.get("name")
    value = unicodedata.normalize("NFC", value or "").strip()
    if kind != "claim":
        value = value.casefold()
    return kind, value, str(item.get("type") or "")


def prepare_supplement(
    document: Document, parent: ExtractionRun, additions: ExtractionResult,
    existing: list[dict], *, provider: str, model: str,
) -> ExtractionRun | None:
    result = resolve_evidence(document.content, additions)
    validate_evidence(document.content, result)
    for claim in result.claims:
        if unicodedata.normalize("NFC", claim.text) not in unicodedata.normalize(
            "NFC", document.content
        ):
            raise ValueError("Supplemental claims must preserve the source author's words")
    all_items = [(kind, item) for kind, items in (
        ("concept", result.concepts), ("entity", result.entities), ("claim", result.claims)
    ) for item in items]
    if not all_items and not result.relationships:
        return None
    keys = [f"{kind}:{item.id}" for kind, item in all_items]
    if len(set(keys)) != len(keys):
        raise ValueError("Supplemental item IDs must be unique within their kind")
    index = {}
    for item in sorted(existing, key=lambda item: item["id"]):
        index.setdefault(item_identity(item["kind"], item), item["id"])
    aliases, reused = {}, []
    for kind, item in all_items:
        key = f"{kind}:{item.id}"
        identity = item_identity(kind, item.model_dump(mode="json"))
        graph_id = index.get(identity)
        if graph_id is not None:
            reused.append(key)
        else:
            stable = uuid5(NAMESPACE_URL, json.dumps([str(document.id), *identity]))
            graph_id = f"constellation:{stable}:{kind}"
        aliases[key] = graph_id
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("Supplement contains duplicate items with different local IDs")
    serialized = result.model_dump_json()
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    return ExtractionRun(
        id=uuid5(NAMESPACE_URL, f"constellation:link-v2:{parent.id}:{digest}"),
        document_id=document.id, profile_name=parent.profile_name, schema_version="v3",
        prompt_version="link-v2", provider=provider, model=model, status="completed",
        created_at=datetime.now(UTC), result=result, origin="constellation",
        parent_run_id=parent.id, item_graph_ids=aliases, reused_item_keys=reused,
    )
