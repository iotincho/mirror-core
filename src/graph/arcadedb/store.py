"""ArcadeDB implementation of the graph, vector, and reflection ports."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from src.constellation.contracts import CrossDocumentLink, LinkNeighborhood, LinkType, SavedLink
from src.domain.documents import Document
from src.embeddings.contracts import (
    ClaimEmbeddingRecord,
    DocumentEmbeddingRecord,
    EmbeddingSpec,
    EvidenceReference,
    SimilarClaim,
    SimilarDocument,
)
from src.extraction.contracts import ExtractionResult
from src.graph.arcadedb import queries
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.arcadedb.schema import embedding_type_names
from src.reflection.contracts import ClaimRelation
from src.services.claim_embedding_store import ClaimEmbeddingStoreError
from src.services.document_embedding_store import DocumentEmbeddingStoreError
from src.services.extraction_store import ExtractionRun
from src.services.graph_store import GraphBackend, GraphPersistenceError
from src.services.reflection_context_store import ReflectionContextStoreError

logger = logging.getLogger(__name__)

_ITEM_TYPES = {"Concept", "Entity", "Claim"}
_RELATION_TYPES = {
    "ABOUT", "RELATES_TO", "SUPPORTS", "CONTRADICTS", "EXPRESSES_EMOTION",
    "DESIRES", "FEARS", "VALUES", "QUESTIONS", "DECIDES", "ASSOCIATES_WITH",
}


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
    """Persist the application graph through ArcadeDB's HTTP API."""

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

    async def persist(self, document: Document, extraction: ExtractionRun) -> None:
        if extraction.status != "completed" or extraction.result is None:
            raise GraphPersistenceError("Only completed extractions can be persisted in the graph")

        try:
            async with self._client.transaction() as transaction:
                await self._write_extraction(transaction, document, extraction)
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB graph persistence failed") from error


    async def persist_verified(self, document: Document, extraction: ExtractionRun) -> None:
        """Replay deterministic writes, verify their identities before committing."""
        try:
            async with self._client.transaction() as transaction:
                await self._write_extraction(transaction, document, extraction)
                params = {"run_id": str(extraction.id)}
                items = self._rows(
                    await transaction.query(queries.RUN_ITEM_IDS, params, language="cypher")
                )
                relations = self._rows(
                    await transaction.query(queries.RUN_RELATION_IDS, params, language="cypher")
                )
                expected = {
                    f"{extraction.id}:{kind}:{item.id}"
                    for kind, values in (
                        ("concept", extraction.result.concepts),
                        ("entity", extraction.result.entities),
                        ("claim", extraction.result.claims),
                    )
                    for item in values
                }
                expected_relations = {
                    f"{extraction.id}:relationship:{index}"
                    for index in range(len(extraction.result.relationships))
                }
                runs = self._rows(
                    await transaction.query(
                        "MATCH (document:Document {id: $document_id})-[:HAS_EXTRACTION]->"
                        "(run:ExtractionRun {id: $run_id}) RETURN run.id AS id",
                        {**params, "document_id": str(document.id)},
                        language="cypher",
                    )
                )
                if (
                    {row["id"] for row in items} != expected
                    or {row["id"] for row in relations} != expected_relations
                    or {row["id"] for row in runs} != {str(extraction.id)}
                ):
                    raise GraphPersistenceError("Extraction write verification failed")
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB verified persistence failed") from error

    async def persist_claim_embeddings(
        self,
        records: list[ClaimEmbeddingRecord],
        spec: EmbeddingSpec,
        *,
        verify: bool = False,
    ) -> None:
        if not records:
            return
        if any(record.spec != spec or len(record.vector) != spec.dimensions for record in records):
            raise ClaimEmbeddingStoreError(
                "Claim embedding record does not match its specification"
            )

        embedding_type, _ = embedding_type_names(spec)
        rows = [
            {
                "id": record.id,
                "claim_graph_id": record.claim_graph_id,
                "claim_local_id": record.claim_local_id,
                "document_id": record.document_id,
                "run_id": record.run_id,
                "profile_name": record.profile_name,
                "prompt_version": record.prompt_version,
                "text_hash": record.text_hash,
                "vector": record.vector,
                "provider": record.spec.provider,
                "model": record.spec.model,
                "dimensions": record.spec.dimensions,
                "created_at": record.created_at.isoformat(),
            }
            for record in records
        ]
        try:
            if verify:
                async with self._client.transaction() as transaction:
                    response = await transaction.command(
                        queries.CLAIM_EMBEDDINGS.format(embedding_type=embedding_type)
                        + " RETURN embedding.id AS id",
                        {"rows": rows},
                        language="cypher",
                    )
                    if {row["id"] for row in self._rows(response)} != {r.id for r in records}:
                        raise ClaimEmbeddingStoreError("Embedding write verification failed")
                return
            await self._client.command(
                queries.CLAIM_EMBEDDINGS.format(embedding_type=embedding_type),
                {"rows": rows},
                language="cypher",
            )
        except Exception as error:
            raise ClaimEmbeddingStoreError("ArcadeDB claim embedding persistence failed") from error

    async def search_claim_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarClaim]:
        if len(vector) != spec.dimensions or limit < 1:
            raise ClaimEmbeddingStoreError("Invalid vector-search request")

        embedding_type, _ = embedding_type_names(spec)
        try:
            neighbors = self._rows(
                await self._client.query(
                    queries.vector_neighbors(embedding_type),
                    {"vector": vector, "limit": limit},
                )
            )
            score_by_claim_id = {
                str(self._neighbor_value(row, "claim_graph_id")): self._score(row)
                for row in neighbors
            }
            claim_ids = list(score_by_claim_id)
            if not claim_ids:
                return []
            details = self._rows(
                await self._client.query(
                    queries.CLAIM_DETAILS,
                    {"claim_ids": claim_ids},
                    language="cypher",
                )
            )
            by_id = {str(row["claim_id"]): row for row in details}
            return [
                self._similar_claim(by_id[claim_id], score_by_claim_id[claim_id])
                for claim_id in claim_ids
                if claim_id in by_id
            ]
        except ClaimEmbeddingStoreError:
            raise
        except Exception as error:
            raise ClaimEmbeddingStoreError("ArcadeDB claim embedding search failed") from error

    async def persist_document_embedding(
        self,
        record: DocumentEmbeddingRecord,
        spec: EmbeddingSpec,
        *,
        verify: bool = False,
    ) -> None:
        if record.spec != spec or len(record.vector) != spec.dimensions:
            raise DocumentEmbeddingStoreError("Document embedding specification mismatch")
        _, embedding_type = embedding_type_names(spec)
        params = {
            "id": record.id,
            "document_id": record.document_id,
            "text_hash": record.text_hash,
            "content": record.content,
            "source": record.source,
            "metadata_json": json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
            "created_at": record.created_at.isoformat(),
            "authored_at": record.authored_at.isoformat() if record.authored_at else None,
            "vector": record.vector,
            "provider": spec.provider,
            "model": spec.model,
            "dimensions": spec.dimensions,
        }
        statement = queries.DOCUMENT_EMBEDDING.format(embedding_type=embedding_type)
        try:
            if verify:
                async with self._client.transaction() as transaction:
                    response = await transaction.command(
                        statement + " RETURN embedding.id AS id", params, language="cypher"
                    )
                    if {row["id"] for row in self._rows(response)} != {record.id}:
                        raise DocumentEmbeddingStoreError("Embedding write verification failed")
            else:
                await self._client.command(statement, params, language="cypher")
        except Exception as error:
            raise DocumentEmbeddingStoreError(
                "ArcadeDB document embedding persistence failed"
            ) from error

    async def search_document_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarDocument]:
        if len(vector) != spec.dimensions or limit < 1:
            raise DocumentEmbeddingStoreError("Invalid vector-search request")

        _, embedding_type = embedding_type_names(spec)
        try:
            neighbors = self._rows(
                await self._client.query(
                    queries.vector_neighbors(embedding_type),
                    {"vector": vector, "limit": limit},
                )
            )
            return [self._similar_document(row) for row in neighbors]
        except DocumentEmbeddingStoreError:
            raise
        except Exception as error:
            raise DocumentEmbeddingStoreError(
                "ArcadeDB document embedding search failed"
            ) from error

    async def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]:
        if not claim_ids:
            return []
        try:
            response = await self._client.query(
                queries.CLAIM_RELATIONS,
                {"claim_ids": claim_ids},
                language="cypher",
            )
            return [ClaimRelation(**row) for row in self._rows(response)]
        except Exception as error:
            raise ReflectionContextStoreError(
                "ArcadeDB reflection context retrieval failed"
            ) from error

    async def persist_cross_document_links(self, links: list[CrossDocumentLink]) -> None:
        """Persist proposed links atomically inside the current user's database."""
        if not links:
            return
        try:
            async with self._client.transaction() as transaction:
                await self._write_cross_document_links(transaction, links)
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError(
                "ArcadeDB cross-document link persistence failed"
            ) from error

    async def existing_document_items(self, document_id: str) -> list[dict[str, Any]]:
        try:
            result = []
            for kind in ("Claim", "Entity", "Concept"):
                result.extend(self._rows(await self._client.query(
                    f"MATCH (item:{kind}) WHERE item.document_id = $document_id "
                    f"RETURN item.id AS id, '{kind.lower()}' AS kind, item.text AS text, "
                    "item.name AS name, item.type AS type ORDER BY id",
                    {"document_id": document_id}, language="cypher",
                )))
            return result
        except Exception as error:
            raise GraphPersistenceError("Existing source items are unavailable") from error

    async def persist_link_analysis(
        self, document: Document, supplement: ExtractionRun | None,
        links: list[CrossDocumentLink],
    ) -> None:
        try:
            async with self._client.transaction() as transaction:
                if supplement is not None:
                    if supplement.document_id != document.id or supplement.result is None:
                        raise GraphPersistenceError("Supplement belongs to another document")
                    await self._write_extraction(transaction, document, supplement)
                    found = self._rows(await transaction.query(
                        queries.RUN_ITEM_IDS, {"run_id": str(supplement.id)}, language="cypher",
                    ))
                    if {row["id"] for row in found} != set(supplement.item_graph_ids.values()):
                        raise GraphPersistenceError("Not all supplemental items were persisted")
                    found_relations = self._rows(await transaction.query(
                        queries.RUN_RELATION_IDS, {"run_id": str(supplement.id)},
                        language="cypher",
                    ))
                    expected_relations = {
                        f"{supplement.id}:relationship:{index}"
                        for index in range(len(supplement.result.relationships))
                    }
                    if {row["id"] for row in found_relations} != expected_relations:
                        raise GraphPersistenceError("Not all supplemental relations were persisted")
                await self._write_cross_document_links(transaction, links)
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("Link analysis transaction failed") from error

    async def supplemental_items_persisted(self, run: ExtractionRun) -> bool:
        try:
            found = self._rows(await self._client.query(
                queries.RUN_ITEM_IDS, {"run_id": str(run.id)}, language="cypher",
            ))
            return bool(found) and {row["id"] for row in found} == set(run.item_graph_ids.values())
        except Exception as error:
            raise GraphPersistenceError("Supplemental graph state is unavailable") from error

    @classmethod
    async def _write_cross_document_links(
        cls, transaction: ArcadeDBCommandClient, links: list[CrossDocumentLink],
    ) -> None:
        if not links:
            return
        rows_by_id: dict[str, dict[str, Any]] = {}
        for link in links:
            if link.source_document_id == link.target_document_id:
                raise GraphPersistenceError("Cross-document links require distinct documents")
            for row in cls._cross_document_link_rows(link):
                rows_by_id[row["id"]] = row
        rows = list(rows_by_id.values())
        response = await transaction.command(
            queries.CROSS_DOCUMENT_LINKS, {"rows": rows}, language="cypher"
        )
        persisted_ids = {
            str(row["persisted_id"]) for row in cls._rows(response)
            if row.get("persisted_id") is not None
        }
        if persisted_ids != set(rows_by_id):
            raise GraphPersistenceError(
                "ArcadeDB did not persist every requested cross-document link"
            )

    @staticmethod
    def _cross_document_link_rows(link: CrossDocumentLink) -> list[dict[str, Any]]:
        """Project one conceptual link into traversable, perspective-aware graph edges."""
        canonical_identity = ":".join(
            (link.profile, link.source_claim_id, link.target_claim_id, link.relation_type.value)
        )
        link_id = hashlib.sha256(canonical_identity.encode()).hexdigest()

        def row(
            source_claim_id: str,
            target_claim_id: str,
            source_document_id: str,
            target_document_id: str,
            relation_type: str,
            source_evidence: list[EvidenceReference],
            target_evidence: list[EvidenceReference],
        ) -> dict[str, Any]:
            identity = ":".join((link_id, source_claim_id, target_claim_id, relation_type))
            return {
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "link_id": link_id,
                "source_claim_id": source_claim_id,
                "target_claim_id": target_claim_id,
                "source_document_id": source_document_id,
                "target_document_id": target_document_id,
                "relation_type": relation_type,
                "profile": link.profile,
                "evidence_json": json.dumps(
                    {
                        "source": [item.model_dump() for item in source_evidence],
                        "target": [item.model_dump() for item in target_evidence],
                    },
                    ensure_ascii=False,
                ),
            }

        forward = row(
            link.source_claim_id,
            link.target_claim_id,
            link.source_document_id,
            link.target_document_id,
            link.relation_type.value,
            link.source_evidence,
            link.target_evidence,
        )
        reverse_type = {
            LinkType.SHIFTS: "SHIFTED_FROM",
            LinkType.REVISITS: "IS_REVISITED_BY",
        }.get(link.relation_type, link.relation_type.value)
        reverse = row(
            link.target_claim_id,
            link.source_claim_id,
            link.target_document_id,
            link.source_document_id,
            reverse_type,
            link.target_evidence,
            link.source_evidence,
        )
        return [forward, reverse]

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
        self, document_id: str, *, offset: int = 0, limit: int = 10,
        relation_type: LinkType | None = None,
    ) -> LinkNeighborhood:
        """Page neighbor documents in the database, with bounded link hydration."""
        params = {
            "document_id": document_id,
            "relation_types": (
                [relation_type.value] if relation_type else [t.value for t in LinkType]
            ),
            "offset": offset, "limit": limit,
        }
        try:
            count = self._rows(await self._client.query(
                queries.LINK_NEIGHBOR_COUNT, params, language="cypher"
            ))
            total = int(count[0]["total"]) if count else 0
            page = self._rows(await self._client.query(
                queries.LINK_NEIGHBOR_PAGE, params, language="cypher"
            ))
            neighbors = [str(row["neighbor_id"]) for row in page]
            detail_params = {
                **params, "document_ids": [document_id, *neighbors], "link_limit": 501,
            }
            rows = self._rows(await self._client.query(
                queries.LINK_NEIGHBOR_DETAILS, detail_params, language="cypher"
            )) if neighbors else []
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
                document_id=document_id, neighbor_ids=neighbors, total_neighbors=total,
                next_offset=consumed if neighbors and consumed < total else None,
                links=list(links_by_id.values()), links_truncated=len(rows) > 500,
            )
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB link neighborhood retrieval failed") from error

    async def ready_extraction_ids(
        self, expected_claim_counts: dict[str, int], spec: EmbeddingSpec,
    ) -> set[str]:
        if not expected_claim_counts:
            return set()
        try:
            rows = self._rows(await self._client.query(
                queries.EXTRACTION_READINESS,
                {"run_ids": list(expected_claim_counts), "provider": spec.provider,
                 "model": spec.model, "dimensions": spec.dimensions},
                language="cypher",
            ))
            return {
                str(row["run_id"]) for row in rows
                if int(row["claim_count"]) == expected_claim_counts.get(str(row["run_id"]))
                and int(row["embedded_count"]) == int(row["claim_count"])
            }
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB extraction readiness retrieval failed") from error

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    async def _write_extraction(
        transaction: ArcadeDBCommandClient,
        document: Document,
        extraction: ExtractionRun,
    ) -> None:
        result = extraction.result
        assert result is not None
        document_id = str(document.id)
        run_id = str(extraction.id)
        await transaction.command(
            queries.DOCUMENT_AND_RUN,
            {
                "id": document_id,
                "source": document.source,
                "title": document.title,
                "metadata_json": json.dumps(
                    document.metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "created_at": document.created_at.isoformat(),
                "authored_at": document.authored_at.isoformat()
                if document.authored_at
                else None,
                "run_id": run_id,
                "document_id": document_id,
                "profile_name": extraction.profile_name,
                "schema_version": extraction.schema_version,
                "prompt_version": extraction.prompt_version,
                "provider": extraction.provider,
                "model": extraction.model,
                "run_created_at": extraction.created_at.isoformat(),
                "origin": extraction.origin,
                "parent_run_id": (
                    str(extraction.parent_run_id) if extraction.parent_run_id else None
                ),
                "item_graph_ids_json": json.dumps(extraction.item_graph_ids, sort_keys=True),
            },
            language="cypher",
        )
        for item_type, items in (
            ("Concept", result.concepts),
            ("Entity", result.entities),
            ("Claim", result.claims),
        ):
            await ArcadeDBGraphStore._write_items(
                transaction,
                item_type,
                items,
                run_id,
                document_id,
                extraction.item_graph_ids,
                extraction.reused_item_keys,
            )
        await ArcadeDBGraphStore._write_relationships(
            transaction,
            result,
            run_id,
            document_id,
            extraction.item_graph_ids,
        )

    @staticmethod
    async def _write_items(
        transaction: ArcadeDBCommandClient,
        item_type: str,
        items: list[Any],
        run_id: str,
        document_id: str,
        item_graph_ids: dict[str, str],
        reused_item_keys: list[str],
    ) -> None:
        if item_type not in _ITEM_TYPES:
            raise GraphPersistenceError(f"Unsupported graph item type: {item_type}")
        rows: list[dict[str, Any]] = []
        evidence_rows: list[dict[str, Any]] = []
        reused_rows: list[dict[str, Any]] = []
        for item in items:
            key = f"{item_type.lower()}:{item.id}"
            item_id = item_graph_ids.get(key, f"{run_id}:{key}")
            if key in reused_item_keys:
                reused_rows.append({"id": item_id, "run_id": run_id,
                                    "document_id": document_id})
                continue
            rows.append(
                {
                    "id": item_id,
                    "local_id": item.id,
                    "run_id": run_id,
                    "document_id": document_id,
                    "name": getattr(item, "name", None),
                    "text": getattr(item, "text", None),
                    "type": getattr(item, "type", None),
                }
            )
            evidence_rows.extend(
                ArcadeDBGraphStore._evidence_row(
                    f"{item_id}:evidence:{index}",
                    item_id,
                    evidence,
                    run_id,
                    document_id,
                )
                for index, evidence in enumerate(item.evidence)
            )
        if reused_rows:
            await transaction.command(
                queries.ATTACH_EXISTING_ITEMS.format(item_type=item_type),
                {"rows": reused_rows}, language="cypher",
            )
        if rows:
            await transaction.command(
                queries.ITEMS.format(item_type=item_type),
                {"rows": rows},
                language="cypher",
            )
        if evidence_rows:
            await transaction.command(
                queries.EVIDENCE,
                {"rows": evidence_rows},
                language="cypher",
            )

    @staticmethod
    async def _write_relationships(
        transaction: ArcadeDBCommandClient,
        result: ExtractionResult,
        run_id: str,
        document_id: str,
        item_graph_ids: dict[str, str],
    ) -> None:
        rows_by_type: dict[str, list[dict[str, Any]]] = {}
        for index, relationship in enumerate(result.relationships):
            relation_type = relationship.type.value
            if relation_type not in _RELATION_TYPES:
                raise GraphPersistenceError(
                    f"Unsupported graph relationship type: {relation_type}"
                )
            rows_by_type.setdefault(relation_type, []).append(
                {
                    "id": f"{run_id}:relationship:{index}",
                    "run_id": run_id,
                    "document_id": document_id,
                    "source_id": item_graph_ids.get(
                        f"{relationship.source.kind}:{relationship.source.id}",
                        f"{run_id}:{relationship.source.kind}:{relationship.source.id}",
                    ),
                    "target_id": item_graph_ids.get(
                        f"{relationship.target.kind}:{relationship.target.id}",
                        f"{run_id}:{relationship.target.kind}:{relationship.target.id}",
                    ),
                    "evidence_json": json.dumps(
                        [evidence.model_dump() for evidence in relationship.evidence],
                        ensure_ascii=False,
                    ),
                }
            )
        for relation_type, rows in rows_by_type.items():
            await transaction.command(
                queries.RELATIONSHIPS.format(relation_type=relation_type),
                {"rows": rows},
                language="cypher",
            )

    @staticmethod
    def _evidence_row(
        evidence_id: str,
        owner_id: str,
        evidence: Any,
        run_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        return {
            "id": evidence_id,
            "owner_id": owner_id,
            "run_id": run_id,
            "document_id": document_id,
            "quote": evidence.quote,
            "start_char": evidence.start_char,
            "end_char": evidence.end_char,
            "start_line": evidence.start_line,
            "end_line": evidence.end_line,
        }

    @staticmethod
    def _rows(response: dict[str, Any]) -> list[dict[str, Any]]:
        rows = response.get("result", [])
        return rows if isinstance(rows, list) else []

    @staticmethod
    def _neighbor_value(row: dict[str, Any], key: str) -> Any:
        if key in row:
            return row[key]
        record = row.get("record")
        if isinstance(record, dict):
            return record.get(key)
        return None

    @staticmethod
    def _score(row: dict[str, Any]) -> float:
        return 1.0 - float(row["distance"])

    @staticmethod
    def _similar_document(row: dict[str, Any]) -> SimilarDocument:
        metadata_json = ArcadeDBGraphStore._neighbor_value(row, "metadata_json") or "{}"
        return SimilarDocument(
            document_id=str(ArcadeDBGraphStore._neighbor_value(row, "document_id")),
            content=str(ArcadeDBGraphStore._neighbor_value(row, "content")),
            source=str(ArcadeDBGraphStore._neighbor_value(row, "source")),
            metadata=json.loads(metadata_json),
            created_at=ArcadeDBGraphStore._neighbor_value(row, "created_at"),
            authored_at=ArcadeDBGraphStore._neighbor_value(row, "authored_at"),
            score=ArcadeDBGraphStore._score(row),
        )

    @staticmethod
    def _similar_claim(row: dict[str, Any], score: float) -> SimilarClaim:
        evidence = [
            EvidenceReference(**item)
            for item in row.get("evidence", [])
            if item and item.get("quote") is not None
        ]
        return SimilarClaim(
            claim_id=row["claim_id"],
            claim_local_id=row["claim_local_id"],
            document_id=row["document_id"],
            run_id=row["run_id"],
            profile_name=row["profile_name"],
            prompt_version=row["prompt_version"],
            text=row["text"],
            type=row["type"],
            score=score,
            evidence=evidence,
            document_source=row.get("document_source"),
            document_metadata=json.loads(row.get("document_metadata_json") or "{}"),
            document_created_at=row.get("document_created_at"),
            document_authored_at=row.get("document_authored_at"),
        )
