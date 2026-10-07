"""Embedding-owned persistence/search port and native ArcadeDB implementation."""

from math import isfinite
from typing import Protocol
from uuid import UUID, uuid5

from src.extractors.contracts import ExtractionOutput, FrozenModel, content_hash, digest
from src.extractors.document_embeddings import DocumentEmbeddings, EmbeddingConfiguration


class MatchingSection(FrozenModel):
    text: str
    start_char: int
    end_char: int
    distance: float


class SimilarDocument(FrozenModel):
    document_id: UUID
    distance: float
    sections: list[MatchingSection]


class DocumentEmbeddingStore(Protocol):
    async def existing(self, document_id: UUID) -> ExtractionOutput | None: ...
    async def persist(self, output: ExtractionOutput, payload: DocumentEmbeddings) -> None: ...
    async def search(
        self, vector: list[float], configuration: EmbeddingConfiguration, *, limit: int = 10
    ) -> list[SimilarDocument]: ...


class ArcadeDBDocumentEmbeddingStore:
    def __init__(self, graph):
        self.graph = graph

    @staticmethod
    def rows(response):
        if response.get("truncated") or not isinstance(response.get("result"), list):
            raise ValueError("embedding_graph_incomplete_response")
        return response["result"]

    async def has_schema(self, name):
        types = self.rows(await self.graph.query("SELECT name FROM schema:types"))
        return any(row["name"] == name for row in types)

    async def existing(self, document_id):
        if not await self.has_schema("DocumentSemanticIndex"):
            return None
        rows = self.rows(
            await self.graph.query(
                "SELECT artifact_json FROM DocumentSemanticIndex WHERE document_id=:document_id",
                {"document_id": str(document_id)},
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("embedding_index_duplicate")
        output = ExtractionOutput.model_validate_json(rows[0]["artifact_json"])
        output.verify()
        if output.document_id != document_id or output.extractor != "document_embeddings":
            raise ValueError("embedding_index_identity_mismatch")
        return output

    async def initialize_schema(self, configuration):
        for kind, name in (
            ("VERTEX", "DocumentSemanticIndex"),
            ("VERTEX", "DocumentEmbeddingSection"),
            ("EDGE", "HAS_DOCUMENT_EMBEDDINGS"),
            ("EDGE", "HAS_EMBEDDING_SECTION"),
        ):
            await self.graph.command(f"CREATE {kind} TYPE {name} IF NOT EXISTS")
            await self.graph.command(f"CREATE PROPERTY {name}.id IF NOT EXISTS STRING")
            await self.graph.command(f"CREATE INDEX IF NOT EXISTS ON {name} (id) UNIQUE")
        name = configuration.index_type
        await self.graph.command(
            f"CREATE VERTEX TYPE {name} IF NOT EXISTS EXTENDS DocumentEmbeddingSection"
        )
        await self.graph.command(f"CREATE PROPERTY {name}.vector IF NOT EXISTS ARRAY_OF_FLOATS")
        await self.graph.command(
            f"CREATE INDEX IF NOT EXISTS ON {name} (vector) LSM_VECTOR "
            f"METADATA {{dimensions: {configuration.dimensions}, similarity: 'COSINE'}}"
        )

    async def persist(self, output, payload):
        await self.initialize_schema(payload.configuration)
        params = {
            "document_id": str(output.document_id),
            "run_id": str(output.run_id),
            "artifact_json": output.model_dump_json(),
            "artifact_hash": digest(output.model_dump(mode="json")),
            "content_hash": output.content_hash,
            "configuration_hash": payload.configuration_hash,
            "layer": "document_embeddings",
            "profile_id": output.profile.id,
            "profile_hash": output.profile_hash,
            "count": len(payload.sections),
            "edge_id": str(uuid5(output.document_id, "document-embeddings")),
        }
        async with self.graph.transaction() as tx:
            source = self.rows(
                await tx.query("SELECT content FROM Document WHERE id=:document_id", params)
            )
            if len(source) != 1 or content_hash(source[0]["content"]) != output.content_hash:
                raise ValueError("embedding_graph_source_missing_or_changed")
            old = self.rows(
                await tx.query(
                    "SELECT artifact_hash, configuration_hash, content_hash, section_count "
                    "FROM DocumentSemanticIndex WHERE document_id=:document_id",
                    params,
                )
            )
            if old:
                if len(old) != 1:
                    raise ValueError("embedding_index_duplicate")
                compatible = (
                    old[0].get("content_hash") == output.content_hash
                    and old[0].get("configuration_hash") == payload.configuration_hash
                )
                if old[0].get("artifact_hash") == params["artifact_hash"] or (
                    compatible and not payload.force
                ):
                    await self.verify(tx, params, old[0]["section_count"])
                    return
                if not payload.force:
                    raise ValueError("embedding_reprocessing_requires_force")
            # Delete + insert happen only after all vectors have been generated/validated.
            await tx.command(
                "MATCH (n) WHERE n.document_id=$document_id AND "
                "(n:DocumentSemanticIndex OR n:DocumentEmbeddingSection) DETACH DELETE n",
                params,
                language="cypher",
            )
            await tx.command(
                """
MATCH (d:Document {id:$document_id})
CREATE (r:DocumentSemanticIndex {id:$document_id})
SET r.document_id=$document_id, r.run_id=$run_id, r.layer=$layer,
    r.profile_id=$profile_id, r.profile_hash=$profile_hash, r.content_hash=$content_hash,
    r.configuration_hash=$configuration_hash, r.visualizable=false, r.artifact_hash=$artifact_hash,
    r.artifact_json=$artifact_json, r.section_count=$count
CREATE (d)-[e:HAS_DOCUMENT_EMBEDDINGS {id:$edge_id}]->(r)
SET e.document_id=$document_id, e.layer=$layer, e.visualizable=false
""",
                params,
                language="cypher",
            )
            for index, section in enumerate(payload.sections):
                values = {
                    **params,
                    **section.model_dump(),
                    "id": str(uuid5(output.run_id, f"embedding:{index}")),
                    "section_edge_id": str(uuid5(output.run_id, f"embedding-edge:{index}")),
                }
                await tx.command(
                    f"CREATE VERTEX {payload.configuration.index_type} SET "
                    "id=:id, document_id=:document_id, run_id=:run_id, layer=:layer, "
                    "configuration_hash=:configuration_hash, profile_id=:profile_id, "
                    "text=:text, start_char=:start_char, end_char=:end_char, "
                    "tokens=:tokens, visualizable=false, vector=:vector",
                    values,
                )
                await tx.command(
                    """
MATCH (r:DocumentSemanticIndex {id:$document_id}), (s:DocumentEmbeddingSection {id:$id})
CREATE (r)-[e:HAS_EMBEDDING_SECTION {id:$section_edge_id}]->(s)
SET e.document_id=$document_id, e.layer=$layer, e.visualizable=false
""",
                    values,
                    language="cypher",
                )
            await self.verify(tx, params, len(payload.sections))
            actual = self.rows(
                await tx.query(
                    "SELECT id, text, start_char, end_char FROM "
                    "DocumentEmbeddingSection WHERE document_id=:document_id",
                    params,
                )
            )
            expected = [
                {
                    "id": str(uuid5(output.run_id, f"embedding:{index}")),
                    "text": s.text,
                    "start_char": s.start_char,
                    "end_char": s.end_char,
                }
                for index, s in enumerate(payload.sections)
            ]
            if sorted(actual, key=lambda row: row["id"]) != sorted(
                expected, key=lambda row: row["id"]
            ):
                raise ValueError("embedding_section_verification_failed")

    async def verify(self, tx, params, count):
        roots = self.rows(
            await tx.query(
                """
MATCH (d:Document {id:$document_id})-[e:HAS_DOCUMENT_EMBEDDINGS]->(r:DocumentSemanticIndex)
RETURN r.content_hash AS content_hash, r.configuration_hash AS configuration_hash
""",
                params,
                language="cypher",
            )
        )
        if roots != [
            {
                "content_hash": params["content_hash"],
                "configuration_hash": params["configuration_hash"],
            }
        ]:
            raise ValueError("embedding_index_verification_failed")
        rows = self.rows(
            await tx.query(
                "SELECT count(*) AS total FROM DocumentEmbeddingSection "
                "WHERE document_id=:document_id",
                params,
            )
        )
        edges = self.rows(
            await tx.query(
                """
MATCH (r:DocumentSemanticIndex {id:$document_id})-[e:HAS_EMBEDDING_SECTION]->
      (s:DocumentEmbeddingSection)
RETURN count(e) AS total
""",
                params,
                language="cypher",
            )
        )
        if rows != [{"total": count}] or edges != [{"total": count}]:
            raise ValueError("embedding_count_verification_failed")

    async def search(self, vector, configuration, *, limit=10):
        if (
            not 1 <= limit <= 100
            or len(vector) != configuration.dimensions
            or (not all(isfinite(x) for x in vector) or not any(vector))
        ):
            raise ValueError("embedding_search_input_invalid")
        name = configuration.index_type
        if not await self.has_schema(name):
            return []
        total = self.rows(await self.graph.query(f"SELECT count(*) AS total FROM {name}"))[0][
            "total"
        ]
        if not total:
            return []
        candidates = min(total, max(limit * 4, 32))
        while True:
            rows = self.rows(
                await self.graph.query(
                    f"SELECT expand(vector.neighbors('{name}[vector]', :vector, :limit))",
                    {"vector": vector, "limit": candidates},
                )
            )
            documents = {}
            for row in rows:
                record = row.get("record") or row
                distance = float(row["distance"])
                if not isfinite(distance):
                    raise ValueError("embedding_search_distance_invalid")
                identifier = record["document_id"]
                section = MatchingSection(
                    text=record["text"],
                    start_char=record["start_char"],
                    end_char=record["end_char"],
                    distance=distance,
                )
                documents.setdefault(identifier, []).append(section)
            if len(documents) >= limit or candidates >= total:
                break
            candidates = min(total, candidates * 2)
        matches = [
            SimilarDocument(
                document_id=identifier,
                distance=min(s.distance for s in sections),
                sections=sorted(sections, key=lambda s: s.distance),
            )
            for identifier, sections in documents.items()
        ]
        return sorted(matches, key=lambda match: (match.distance, str(match.document_id)))[:limit]
