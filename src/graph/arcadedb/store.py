"""Workspace database adapter for original documents and graph navigation."""

import json
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from src.domain.documents import Document
from src.graph.arcadedb import queries
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.contracts import LinkNeighborhood, LinkType, SavedLink
from src.services.graph_store import GraphBackend, GraphPersistenceError


class ArcadeDBCommandClient(Protocol):
    async def command(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]: ...

    async def query(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]: ...


class ArcadeDBStoreClient(ArcadeDBCommandClient, Protocol):
    def transaction(self) -> AbstractAsyncContextManager[ArcadeDBCommandClient]: ...

    async def close(self) -> None: ...


class ArcadeDBGraphStore(GraphBackend):
    """Documents and read-only presentation; each extractor owns its write schema."""

    def __init__(
        self,
        http_url: str,
        database: str,
        username: str,
        password: str,
        *,
        client: ArcadeDBStoreClient | None = None,
    ) -> None:
        self._client = client or AsyncArcadeDBHTTPClient(http_url, database, username, password)

    @property
    def database_client(self) -> ArcadeDBStoreClient:
        """Bound database command port for layers owning their own graph representation."""
        return self._client

    async def persist_document(self, document: Document) -> None:
        try:
            async with self._client.transaction() as transaction:
                rows = self._rows(
                    await transaction.command(
                        queries.DOCUMENT,
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

    async def delete_document(self, document_id: str) -> None:
        try:
            await self._client.command(
                queries.DELETE_DOCUMENT,
                {"document_id": document_id},
                language="cypher",
            )
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB document deletion failed") from error

    async def get_link_neighborhood(
        self,
        document_id: str,
        *,
        offset: int = 0,
        limit: int = 10,
        relation_type: LinkType | None = None,
    ) -> LinkNeighborhood:
        """Page neighbor documents in the database, with bounded link hydration."""
        params = {
            "document_id": document_id,
            "relation_types": (
                [relation_type.value] if relation_type else [t.value for t in LinkType]
            ),
            "offset": offset,
            "limit": limit,
        }
        try:
            types = self._rows(await self._client.query("SELECT name FROM schema:types"))
            if not any(row["name"] == "CROSS_DOCUMENT_LINK" for row in types):
                return LinkNeighborhood(
                    document_id=document_id,
                    neighbor_ids=[],
                    total_neighbors=0,
                    next_offset=None,
                    links=[],
                )
            count = self._rows(
                await self._client.query(queries.LINK_NEIGHBOR_COUNT, params, language="cypher")
            )
            total = int(count[0]["total"]) if count else 0
            page = self._rows(
                await self._client.query(queries.LINK_NEIGHBOR_PAGE, params, language="cypher")
            )
            neighbors = [str(row["neighbor_id"]) for row in page]
            detail_params = {
                **params,
                "document_ids": [document_id, *neighbors],
                "link_limit": 501,
            }
            rows = (
                self._rows(
                    await self._client.query(
                        queries.LINK_NEIGHBOR_DETAILS, detail_params, language="cypher"
                    )
                )
                if neighbors
                else []
            )
            links_by_id = {}
            for row in rows[:500]:
                row = dict(row)
                evidence = json.loads(row.pop("evidence_json"))
                link = SavedLink(
                    **row, source_evidence=evidence["source"], target_evidence=evidence["target"]
                )
                links_by_id[link.link_id] = link
            consumed = offset + len(neighbors)
            return LinkNeighborhood(
                document_id=document_id,
                neighbor_ids=neighbors,
                total_neighbors=total,
                next_offset=consumed if neighbors and consumed < total else None,
                links=list(links_by_id.values()),
                links_truncated=len(rows) > 500,
            )
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB link neighborhood retrieval failed") from error

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
        rows = response.get("result")
        if response.get("truncated") or not isinstance(rows, list):
            raise GraphPersistenceError("ArcadeDB returned incomplete graph results")
        return rows
