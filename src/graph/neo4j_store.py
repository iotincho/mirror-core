"""Neo4j adapter for the evidence-backed extraction graph."""

import json
import logging
from typing import Any

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
from src.reflection.contracts import ClaimRelation
from src.services.claim_embedding_store import ClaimEmbeddingStoreError
from src.services.document_embedding_store import (
    DocumentEmbeddingStoreError,
)
from src.services.extraction_store import ExtractionRun
from src.services.graph_store import GraphBackend, GraphPersistenceError
from src.services.reflection_context_store import (
    ReflectionContextStoreError,
)

logger = logging.getLogger(__name__)


class Neo4jGraphStore(GraphBackend):
    """Persist each immutable extraction run without canonicalizing knowledge yet."""

    def __init__(self, uri: str, username: str, password: str, driver: Any | None = None) -> None:
        self._uri = uri
        self._username = username
        self._password = password
        self._driver = driver
        self._schema_initialized = False
        self._vector_indices: set[str] = set()

    def persist(self, document: Document, extraction: ExtractionRun) -> None:
        if extraction.status != "completed" or extraction.result is None:
            raise GraphPersistenceError("Only completed extractions can be persisted in the graph")

        driver = self._get_driver()
        result = extraction.result
        logger.info(
            "graph_persistence_started document_id=%s run_id=%s concepts=%s entities=%s "
            "claims=%s relationships=%s",
            document.id,
            extraction.id,
            len(result.concepts),
            len(result.entities),
            len(result.claims),
            len(result.relationships),
        )
        try:
            with driver.session() as session:
                self._initialize_schema(session)
                session.execute_write(self._write_extraction, document, extraction)
            logger.info(
                "graph_persistence_completed document_id=%s run_id=%s relationships=%s",
                document.id,
                extraction.id,
                len(result.relationships),
            )
        except GraphPersistenceError:
            raise
        except Exception as error:
            raise GraphPersistenceError("Neo4j graph persistence failed") from error

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

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
        index_name = self._vector_index_name(spec)
        logger.info(
            "claim_embeddings_persist_started records=%s provider=%s model=%s dimensions=%s "
            "index_name=%s",
            len(records),
            spec.provider,
            spec.model,
            spec.dimensions,
            index_name,
        )
        try:
            with self._get_driver().session() as session:
                self._initialize_schema(session)
                self._initialize_vector_index(session, spec)
                session.execute_write(self._write_claim_embeddings, records, spec)
            logger.info(
                "claim_embeddings_persist_completed records=%s index_name=%s",
                len(records),
                index_name,
            )
        except ClaimEmbeddingStoreError:
            raise
        except Exception as error:
            raise ClaimEmbeddingStoreError("Neo4j claim embedding persistence failed") from error

    def search_claim_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarClaim]:
        if len(vector) != spec.dimensions or limit < 1:
            raise ClaimEmbeddingStoreError("Invalid vector-search request")
        index_name = self._vector_index_name(spec)
        logger.info(
            "claim_vector_search_started provider=%s model=%s dimensions=%s "
            "vector_dimensions=%s limit=%s index_name=%s",
            spec.provider,
            spec.model,
            spec.dimensions,
            len(vector),
            limit,
            index_name,
        )
        try:
            with self._get_driver().session() as session:
                self._initialize_schema(session)
                self._initialize_vector_index(session, spec)
                records = session.run(
                    """
                    CALL db.index.vector.queryNodes($index_name, $limit, $vector)
                    YIELD node, score
                    MATCH (claim:Claim)-[:HAS_EMBEDDING]->(node)
                    MATCH (run:ExtractionRun {id: claim.run_id})
                    MATCH (document:Document {id: claim.document_id})
                    OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)
                    WITH claim, run, document, score, collect(evidence) AS evidence_nodes
                    RETURN claim.id AS claim_id,
                           claim.local_id AS claim_local_id,
                           claim.document_id AS document_id,
                           claim.run_id AS run_id,
                           run.profile_name AS profile_name,
                           run.prompt_version AS prompt_version,
                           claim.text AS text,
                           claim.type AS type,
                           document.source AS document_source,
                           document.metadata_json AS document_metadata_json,
                           document.created_at AS document_created_at,
                           document.authored_at AS document_authored_at,
                           score,
                           [item IN evidence_nodes | {
                               quote: item.quote,
                               start_line: item.start_line,
                               end_line: item.end_line
                           }] AS evidence
                    ORDER BY score DESC
                    """,
                    index_name=index_name,
                    limit=limit,
                    vector=vector,
                )
                claims = [self._similar_claim(record.data()) for record in records]
            logger.info(
                "claim_vector_search_completed index_name=%s result_count=%s",
                index_name,
                len(claims),
            )
            return claims
        except ClaimEmbeddingStoreError:
            raise
        except Exception as error:
            logger.exception(
                "claim_vector_search_failed provider=%s model=%s dimensions=%s "
                "vector_dimensions=%s limit=%s index_name=%s error_type=%s",
                spec.provider,
                spec.model,
                spec.dimensions,
                len(vector),
                limit,
                index_name,
                type(error).__name__,
            )
            raise ClaimEmbeddingStoreError("Neo4j claim embedding search failed") from error


    def persist_document_embedding(
        self,
        record: DocumentEmbeddingRecord,
        spec: EmbeddingSpec,
    ) -> None:
        if record.spec != spec or len(record.vector) != spec.dimensions:
            raise DocumentEmbeddingStoreError(
                "Document embedding record does not match its specification"
            )
        try:
            with self._get_driver().session() as session:
                self._initialize_schema(session)
                self._initialize_document_vector_index(session, spec)
                session.execute_write(self._write_document_embedding, record, spec)
        except DocumentEmbeddingStoreError:
            raise
        except Exception as error:
            raise DocumentEmbeddingStoreError(
                "Neo4j document embedding persistence failed"
            ) from error

    def search_document_embeddings(
        self,
        vector: list[float],
        spec: EmbeddingSpec,
        limit: int,
    ) -> list[SimilarDocument]:
        if len(vector) != spec.dimensions or limit < 1:
            raise DocumentEmbeddingStoreError("Invalid vector-search request")
        index_name = self._document_vector_index_name(spec)
        try:
            with self._get_driver().session() as session:
                self._initialize_schema(session)
                self._initialize_document_vector_index(session, spec)
                records = session.run(
                    """
                    CALL db.index.vector.queryNodes($index_name, $limit, $vector)
                    YIELD node, score
                    MATCH (document:Document)-[:HAS_EMBEDDING]->(node)
                    RETURN document.id AS document_id,
                           node.content AS content,
                           node.source AS source,
                           node.metadata_json AS metadata_json,
                           node.created_at AS created_at,
                           node.authored_at AS authored_at,
                           score
                    ORDER BY score DESC
                    """,
                    index_name=index_name,
                    limit=limit,
                    vector=vector,
                )
                return [self._similar_document(record.data()) for record in records]
        except DocumentEmbeddingStoreError:
            raise
        except Exception as error:
            raise DocumentEmbeddingStoreError("Neo4j document embedding search failed") from error
    def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]:
        if not claim_ids:
            return []
        try:
            with self._get_driver().session() as session:
                records = session.run(
                    """
                    MATCH (source:Claim)-
                        [relationship:ABOUT|RELATES_TO|SUPPORTS|CONTRADICTS]->(target)
                    WHERE source.id IN $claim_ids
                    RETURN source.id AS source_claim_id,
                           type(relationship) AS relation_type,
                           target.id AS target_id,
                           CASE
                               WHEN target:Claim THEN 'claim'
                               WHEN target:Concept THEN 'concept'
                               WHEN target:Entity THEN 'entity'
                               ELSE 'unknown'
                           END AS target_kind,
                           coalesce(target.text, target.name) AS target_text
                    ORDER BY source_claim_id, relation_type, target_id
                    """,
                    claim_ids=claim_ids,
                )
                relations = [ClaimRelation(**record.data()) for record in records]
            logger.info(
                "reflection_graph_context_completed claim_count=%s relation_count=%s",
                len(claim_ids),
                len(relations),
            )
            return relations
        except Exception as error:
            logger.exception(
                "reflection_graph_context_failed claim_count=%s error_type=%s",
                len(claim_ids),
                type(error).__name__,
            )
            raise ReflectionContextStoreError(
                "Neo4j reflection context retrieval failed"
            ) from error

    def _get_driver(self) -> Any:
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._username, self._password),
            )
        return self._driver

    def _initialize_schema(self, session: Any) -> None:
        if self._schema_initialized:
            return
        for query in (
            (
                "CREATE CONSTRAINT document_id IF NOT EXISTS "
                "FOR (node:Document) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT extraction_run_id IF NOT EXISTS "
                "FOR (node:ExtractionRun) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT concept_id IF NOT EXISTS "
                "FOR (node:Concept) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT entity_id IF NOT EXISTS "
                "FOR (node:Entity) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT claim_id IF NOT EXISTS "
                "FOR (node:Claim) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT evidence_id IF NOT EXISTS "
                "FOR (node:Evidence) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT claim_embedding_id IF NOT EXISTS "
                "FOR (node:ClaimEmbedding) REQUIRE node.id IS UNIQUE"
            ),
            (
                "CREATE CONSTRAINT document_embedding_id IF NOT EXISTS "
                "FOR (node:DocumentEmbedding) REQUIRE node.id IS UNIQUE"
            ),
        ):
            session.run(query).consume()
        self._schema_initialized = True

    def _initialize_vector_index(self, session: Any, spec: EmbeddingSpec) -> None:
        index_name = self._vector_index_name(spec)
        if index_name in self._vector_indices:
            return
        label = self._vector_label(spec)
        session.run(
            f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (node:{label}) ON node.vector
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {spec.dimensions},
                `vector.similarity_function`: 'cosine'
            }}}}
            """
        ).consume()
        self._vector_indices.add(index_name)
        logger.info(
            "claim_vector_index_ensured index_name=%s label=%s dimensions=%s",
            index_name,
            label,
            spec.dimensions,
        )

    @staticmethod
    def _vector_index_name(spec: EmbeddingSpec) -> str:
        return f"claim_embedding_{spec.index_suffix}"

    @staticmethod
    def _vector_label(spec: EmbeddingSpec) -> str:
        return f"ClaimEmbedding_{spec.index_suffix}"

    @staticmethod
    def _write_extraction(transaction: Any, document: Document, extraction: ExtractionRun) -> None:
        result = extraction.result
        assert result is not None
        document_id = str(document.id)
        run_id = str(extraction.id)
        transaction.run(
            """
            MERGE (document:Document {id: $id})
            SET document.source = $source,
                document.metadata_json = $metadata_json,
                document.created_at = $created_at,
                document.authored_at = $authored_at
            MERGE (run:ExtractionRun {id: $run_id})
            SET run.document_id = $document_id,
                run.profile_name = $profile_name,
                run.schema_version = $schema_version,
                run.prompt_version = $prompt_version,
                run.provider = $provider,
                run.model = $model,
                run.created_at = $run_created_at
            MERGE (document)-[:HAS_EXTRACTION]->(run)
            """,
            id=document_id,
            source=document.source,
            metadata_json=json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
            created_at=document.created_at.isoformat(),
            authored_at=document.authored_at.isoformat() if document.authored_at else None,
            run_id=run_id,
            document_id=document_id,
            profile_name=extraction.profile_name,
            schema_version=extraction.schema_version,
            prompt_version=extraction.prompt_version,
            provider=extraction.provider,
            model=extraction.model,
            run_created_at=extraction.created_at.isoformat(),
        )
        Neo4jGraphStore._write_items(transaction, "Concept", result.concepts, run_id, document_id)
        Neo4jGraphStore._write_items(transaction, "Entity", result.entities, run_id, document_id)
        Neo4jGraphStore._write_items(transaction, "Claim", result.claims, run_id, document_id)
        Neo4jGraphStore._write_relationships(transaction, result, run_id, document_id)

    @staticmethod
    def _write_items(
        transaction: Any,
        label: str,
        items: list[Any],
        run_id: str,
        document_id: str,
    ) -> None:
        rows = []
        evidence_rows = []
        for item in items:
            item_id = f"{run_id}:{label.lower()}:{item.id}"
            row = {
                "id": item_id,
                "local_id": item.id,
                "run_id": run_id,
                "document_id": document_id,
                "name": getattr(item, "name", None),
                "text": getattr(item, "text", None),
                "type": getattr(item, "type", None),
            }
            rows.append(row)
            for index, evidence in enumerate(item.evidence):
                evidence_rows.append(
                    Neo4jGraphStore._evidence_row(
                        f"{item_id}:evidence:{index}",
                        item_id,
                        evidence,
                        run_id,
                        document_id,
                    )
                )

        if rows:
            transaction.run(
                f"""
                UNWIND $rows AS row
                MERGE (item:{label} {{id: row.id}})
                SET item.local_id = row.local_id,
                    item.run_id = row.run_id,
                    item.document_id = row.document_id,
                    item.name = row.name,
                    item.text = row.text,
                    item.type = row.type
                WITH item, row
                MATCH (run:ExtractionRun {{id: row.run_id}})
                MERGE (run)-[:EXTRACTED]->(item)
                """,
                rows=rows,
            )
        Neo4jGraphStore._write_evidence(transaction, evidence_rows)

    @staticmethod
    def _write_relationships(
        transaction: Any,
        result: ExtractionResult,
        run_id: str,
        document_id: str,
    ) -> None:
        rows_by_type: dict[str, list[dict[str, Any]]] = {}
        for index, relationship in enumerate(result.relationships):
            relation_type = relationship.type.value
            rows_by_type.setdefault(relation_type, []).append(
                {
                    "id": f"{run_id}:relationship:{index}",
                    "run_id": run_id,
                    "document_id": document_id,
                    "source_id": f"{run_id}:{relationship.source.kind}:{relationship.source.id}",
                    "target_id": f"{run_id}:{relationship.target.kind}:{relationship.target.id}",
                    "evidence_json": json.dumps(
                        [evidence.model_dump() for evidence in relationship.evidence],
                        ensure_ascii=False,
                    ),
                }
            )

        for relation_type, rows in rows_by_type.items():
            logger.info(
                "graph_relationships_write_started run_id=%s document_id=%s "
                "relationship_type=%s count=%s",
                run_id,
                document_id,
                relation_type,
                len(rows),
            )
            write_result = transaction.run(
                f"""
                UNWIND $rows AS row
                MATCH (source {{id: row.source_id}}), (target {{id: row.target_id}})
                MERGE (source)-[relationship:{relation_type} {{id: row.id}}]->(target)
                SET relationship.run_id = row.run_id,
                    relationship.document_id = row.document_id,
                    relationship.evidence_json = row.evidence_json
                RETURN count(relationship) AS persisted_count
                """,
                rows=rows,
            )
            persisted_count = write_result.single()["persisted_count"]
            logger.info(
                "graph_relationships_write_completed run_id=%s relationship_type=%s "
                "requested_count=%s persisted_count=%s",
                run_id,
                relation_type,
                len(rows),
                persisted_count,
            )
        if not rows_by_type:
            logger.info(
                "graph_relationships_skipped run_id=%s document_id=%s "
                "reason=no_extracted_relationships",
                run_id,
                document_id,
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
    def _write_evidence(transaction: Any, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        transaction.run(
            """
            UNWIND $rows AS row
            MERGE (evidence:Evidence {id: row.id})
            SET evidence.run_id = row.run_id,
                evidence.document_id = row.document_id,
                evidence.quote = row.quote,
                evidence.start_char = row.start_char,
                evidence.end_char = row.end_char,
                evidence.start_line = row.start_line,
                evidence.end_line = row.end_line
            WITH evidence, row
            MATCH (item {id: row.owner_id}), (document:Document {id: row.document_id})
            MERGE (item)-[:SUPPORTED_BY]->(evidence)
            MERGE (evidence)-[:FROM_DOCUMENT]->(document)
            """,
            rows=rows,
        )

    def _initialize_document_vector_index(self, session: Any, spec: EmbeddingSpec) -> None:
        index_name = self._document_vector_index_name(spec)
        if index_name in self._vector_indices:
            return
        label = self._document_vector_label(spec)
        session.run(
            f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (node:{label}) ON node.vector
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {spec.dimensions},
                `vector.similarity_function`: 'cosine'
            }}}}
            """
        ).consume()
        self._vector_indices.add(index_name)

    @staticmethod
    def _document_vector_index_name(spec: EmbeddingSpec) -> str:
        return f"document_embedding_{spec.index_suffix}"

    @staticmethod
    def _document_vector_label(spec: EmbeddingSpec) -> str:
        return f"DocumentEmbedding_{spec.index_suffix}"

    @staticmethod
    def _write_claim_embeddings(
        transaction: Any,
        records: list[ClaimEmbeddingRecord],
        spec: EmbeddingSpec,
    ) -> None:
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
        write_result = transaction.run(
            f"""
            UNWIND $rows AS row
            MERGE (embedding:ClaimEmbedding:{Neo4jGraphStore._vector_label(spec)} {{id: row.id}})
            SET embedding.claim_graph_id = row.claim_graph_id,
                embedding.claim_local_id = row.claim_local_id,
                embedding.document_id = row.document_id,
                embedding.run_id = row.run_id,
                embedding.profile_name = row.profile_name,
                embedding.prompt_version = row.prompt_version,
                embedding.text_hash = row.text_hash,
                embedding.vector = row.vector,
                embedding.provider = row.provider,
                embedding.model = row.model,
                embedding.dimensions = row.dimensions,
                embedding.created_at = row.created_at
            WITH embedding, row
            MATCH (claim:Claim {{id: row.claim_graph_id}})
            MERGE (claim)-[:HAS_EMBEDDING]->(embedding)
            RETURN count(embedding) AS persisted_count
            """,
            rows=rows,
        )
        logger.info(
            "claim_embedding_links_write_completed requested_count=%s persisted_count=%s "
            "index_name=%s",
            len(records),
            write_result.single()["persisted_count"],
            Neo4jGraphStore._vector_index_name(spec),
        )

    @staticmethod
    def _write_document_embedding(
        transaction: Any,
        record: DocumentEmbeddingRecord,
        spec: EmbeddingSpec,
    ) -> None:
        embedding_label = Neo4jGraphStore._document_vector_label(spec)
        transaction.run(
            f"""
            MERGE (embedding:DocumentEmbedding:{embedding_label} {{id: $id}})
            SET embedding.document_id = $document_id,
                embedding.text_hash = $text_hash,
                embedding.content = $content,
                embedding.source = $source,
                embedding.metadata_json = $metadata_json,
                embedding.created_at = $created_at,
                embedding.authored_at = $authored_at,
                embedding.vector = $vector,
                embedding.provider = $provider,
                embedding.model = $model,
                embedding.dimensions = $dimensions
            WITH embedding
            MATCH (document:Document {{id: $document_id}})
            MERGE (document)-[:HAS_EMBEDDING]->(embedding)
            """,
            id=record.id,
            document_id=record.document_id,
            text_hash=record.text_hash,
            content=record.content,
            source=record.source,
            metadata_json=json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
            created_at=record.created_at.isoformat(),
            authored_at=record.authored_at.isoformat() if record.authored_at else None,
            vector=record.vector,
            provider=record.spec.provider,
            model=record.spec.model,
            dimensions=record.spec.dimensions,
        ).consume()

    @staticmethod
    def _similar_document(record: dict[str, Any]) -> SimilarDocument:
        return SimilarDocument(
            document_id=record["document_id"],
            content=record["content"],
            source=record["source"],
            metadata=json.loads(record["metadata_json"]),
            created_at=record["created_at"],
            authored_at=record.get("authored_at"),
            score=record["score"],
        )

    @staticmethod
    def _similar_claim(record: dict[str, Any]) -> SimilarClaim:
        return SimilarClaim(
            claim_id=record["claim_id"],
            claim_local_id=record["claim_local_id"],
            document_id=record["document_id"],
            run_id=record["run_id"],
            profile_name=record["profile_name"],
            prompt_version=record["prompt_version"],
            text=record["text"],
            type=record["type"],
            score=record["score"],
            evidence=[EvidenceReference(**evidence) for evidence in record["evidence"]],
            document_source=record.get("document_source"),
            document_metadata=json.loads(record.get("document_metadata_json") or "{}"),
            document_created_at=record.get("document_created_at"),
            document_authored_at=record.get("document_authored_at"),
        )

    def delete_document(self, document_id: str) -> None:
        try:
            with self._get_driver().session() as session:
                session.execute_write(self._delete_document, document_id)
        except Exception as error:
            raise GraphPersistenceError("Neo4j document deletion failed") from error

    @staticmethod
    def _delete_document(transaction: Any, document_id: str) -> None:
        transaction.run(
            "MATCH (node) WHERE node.document_id = $document_id "
            "OR (node:Document AND node.id = $document_id) DETACH DELETE node",
            document_id=document_id,
        ).consume()
