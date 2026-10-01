"""ArcadeDB implementation of the graph, vector, and reflection ports."""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import AbstractContextManager
from typing import Any, Protocol

from src.constellation.contracts import CrossDocumentLink
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
from src.graph.arcadedb.client import ArcadeDBHTTPClient
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
    def command(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]: ...

    def query(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        language: str = "sql",
    ) -> dict[str, Any]: ...


class ArcadeDBStoreClient(ArcadeDBCommandClient, Protocol):
    def transaction(self) -> AbstractContextManager[ArcadeDBCommandClient]: ...

    def close(self) -> None: ...


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
        self._client = client or ArcadeDBHTTPClient(http_url, database, username, password)

    def persist(self, document: Document, extraction: ExtractionRun) -> None:
        if extraction.status != "completed" or extraction.result is None:
            raise GraphPersistenceError("Only completed extractions can be persisted in the graph")

        try:
            with self._client.transaction() as transaction:
                self._write_extraction(transaction, document, extraction)
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB graph persistence failed") from error

    def persist_claim_embeddings(
        self,
        records: list[ClaimEmbeddingRecord],
        spec: EmbeddingSpec,
    ) -> None:
        if not records:
            return
        if any(
            record.spec != spec or len(record.vector) != spec.dimensions for record in records
        ):
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
            self._client.command(
                queries.CLAIM_EMBEDDINGS.format(embedding_type=embedding_type),
                {"rows": rows},
                language="cypher",
            )
        except Exception as error:
            raise ClaimEmbeddingStoreError(
                "ArcadeDB claim embedding persistence failed"
            ) from error

    def search_claim_embeddings(
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
                self._client.query(
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
                self._client.query(
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

    def persist_document_embedding(
        self,
        record: DocumentEmbeddingRecord,
        spec: EmbeddingSpec,
    ) -> None:
        if record.spec != spec or len(record.vector) != spec.dimensions:
            raise DocumentEmbeddingStoreError(
                "Document embedding record does not match its specification"
            )

        _, embedding_type = embedding_type_names(spec)
        try:
            self._client.command(
                queries.DOCUMENT_EMBEDDING.format(embedding_type=embedding_type),
                {
                    "id": record.id,
                    "document_id": record.document_id,
                    "text_hash": record.text_hash,
                    "content": record.content,
                    "source": record.source,
                    "metadata_json": json.dumps(
                        record.metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "created_at": record.created_at.isoformat(),
                    "authored_at": record.authored_at.isoformat()
                    if record.authored_at
                    else None,
                    "vector": record.vector,
                    "provider": record.spec.provider,
                    "model": record.spec.model,
                    "dimensions": record.spec.dimensions,
                },
                language="cypher",
            )
        except Exception as error:
            raise DocumentEmbeddingStoreError(
                "ArcadeDB document embedding persistence failed"
            ) from error

    def search_document_embeddings(
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
                self._client.query(
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

    def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]:
        if not claim_ids:
            return []
        try:
            response = self._client.query(
                queries.CLAIM_RELATIONS,
                {"claim_ids": claim_ids},
                language="cypher",
            )
            return [ClaimRelation(**row) for row in self._rows(response)]
        except Exception as error:
            raise ReflectionContextStoreError(
                "ArcadeDB reflection context retrieval failed"
            ) from error

    def persist_cross_document_links(self, links: list[CrossDocumentLink]) -> None:
        """Persist proposed links atomically inside the current user's database."""
        if not links:
            return
        rows = []
        for link in links:
            if link.source_document_id == link.target_document_id:
                raise GraphPersistenceError("Cross-document links require distinct documents")
            identity = ":".join((link.profile, link.source_claim_id, link.target_claim_id,
                                 link.relation_type.value))
            rows.append({
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "source_claim_id": link.source_claim_id,
                "target_claim_id": link.target_claim_id,
                "source_document_id": link.source_document_id,
                "target_document_id": link.target_document_id,
                "relation_type": link.relation_type.value,
                "profile": link.profile,
                "evidence_json": json.dumps({
                    "source": [item.model_dump() for item in link.source_evidence],
                    "target": [item.model_dump() for item in link.target_evidence],
                }, ensure_ascii=False),
            })
        try:
            with self._client.transaction() as transaction:
                transaction.command(queries.CROSS_DOCUMENT_LINKS, {"rows": rows},
                                    language="cypher")
        except Exception as error:
            raise GraphPersistenceError(
                "ArcadeDB cross-document link persistence failed"
            ) from error

    def delete_document(self, document_id: str) -> None:
        try:
            self._client.command(
                queries.DELETE_DOCUMENT,
                {"document_id": document_id},
                language="cypher",
            )
        except Exception as error:
            raise GraphPersistenceError("ArcadeDB document deletion failed") from error

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _write_extraction(
        transaction: ArcadeDBCommandClient,
        document: Document,
        extraction: ExtractionRun,
    ) -> None:
        result = extraction.result
        assert result is not None
        document_id = str(document.id)
        run_id = str(extraction.id)
        transaction.command(
            queries.DOCUMENT_AND_RUN,
            {
                "id": document_id,
                "source": document.source,
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
            },
            language="cypher",
        )
        for item_type, items in (
            ("Concept", result.concepts),
            ("Entity", result.entities),
            ("Claim", result.claims),
        ):
            ArcadeDBGraphStore._write_items(
                transaction,
                item_type,
                items,
                run_id,
                document_id,
            )
        ArcadeDBGraphStore._write_relationships(
            transaction,
            result,
            run_id,
            document_id,
        )

    @staticmethod
    def _write_items(
        transaction: ArcadeDBCommandClient,
        item_type: str,
        items: list[Any],
        run_id: str,
        document_id: str,
    ) -> None:
        if item_type not in _ITEM_TYPES:
            raise GraphPersistenceError(f"Unsupported graph item type: {item_type}")
        rows: list[dict[str, Any]] = []
        evidence_rows: list[dict[str, Any]] = []
        for item in items:
            item_id = f"{run_id}:{item_type.lower()}:{item.id}"
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
        if rows:
            transaction.command(
                queries.ITEMS.format(item_type=item_type),
                {"rows": rows},
                language="cypher",
            )
        if evidence_rows:
            transaction.command(
                queries.EVIDENCE,
                {"rows": evidence_rows},
                language="cypher",
            )

    @staticmethod
    def _write_relationships(
        transaction: ArcadeDBCommandClient,
        result: ExtractionResult,
        run_id: str,
        document_id: str,
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
                    "source_id": (
                        f"{run_id}:{relationship.source.kind}:{relationship.source.id}"
                    ),
                    "target_id": (
                        f"{run_id}:{relationship.target.kind}:{relationship.target.id}"
                    ),
                    "evidence_json": json.dumps(
                        [evidence.model_dump() for evidence in relationship.evidence],
                        ensure_ascii=False,
                    ),
                }
            )
        for relation_type, rows in rows_by_type.items():
            transaction.command(
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
