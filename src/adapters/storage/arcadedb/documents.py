"""Verified base document projection using an injected workspace client."""

import json
from typing import Any

from src.core.documents.ports import GraphPersistenceError
from src.core.domain.documents import Document

DOCUMENT = """
MERGE (document:Document {id: $id})
SET document.content = $content,
    document.source = $source,
    document.title = $title,
    document.metadata_json = $metadata_json,
    document.created_at = $created_at,
    document.authored_at = $authored_at
RETURN document.id AS id, document.content AS content
"""


class ArcadeDBDocumentProjection:
    def __init__(self, client):
        self._client = client

    async def persist_document(self, document: Document) -> None:
        try:
            async with self._client.transaction() as transaction:
                rows = self._rows(
                    await transaction.command(
                        DOCUMENT,
                        {
                            "id": str(document.id),
                            "content": document.content,
                            "source": document.source,
                            "title": document.title,
                            "metadata_json": json.dumps(
                                document.metadata, ensure_ascii=False, sort_keys=True
                            ),
                            "created_at": document.created_at.isoformat(),
                            "authored_at": document.authored_at.isoformat()
                            if document.authored_at
                            else None,
                        },
                        language="cypher",
                    )
                )
                if rows != [{"id": str(document.id), "content": document.content}]:
                    raise GraphPersistenceError("Document write could not be verified")
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB document persistence failed") from error

    @staticmethod
    def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
        rows = response.get("result")
        if response.get("truncated") or not isinstance(rows, list):
            raise GraphPersistenceError("ArcadeDB returned incomplete graph results")
        return rows
