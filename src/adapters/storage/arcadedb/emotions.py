"""Atomic, verified replacement of the emotion projection only."""

from uuid import uuid5

from src.core.extractors.contracts import content_hash, digest
from src.core.extractors.emotions import label_key


class ArcadeDBEmotionStore:
    name = "emotions"
    label_key = staticmethod(label_key)

    def __init__(self, graph):
        self.graph = graph

    async def initialize_schema(self):
        for kind, name in (
            ("VERTEX", "EmotionExtraction"),
            ("VERTEX", "Emotion"),
            ("EDGE", "HAS_EMOTION_EXTRACTION"),
            ("EDGE", "HAS_EMOTION"),
        ):
            await self.graph.command(f"CREATE {kind} TYPE {name} IF NOT EXISTS")
            await self.graph.command(f"CREATE PROPERTY {name}.id IF NOT EXISTS STRING")
            await self.graph.command(f"CREATE INDEX IF NOT EXISTS ON {name} (id) UNIQUE")

    @staticmethod
    def rows(response):
        if response.get("truncated"):
            raise ValueError("emotion_graph_result_truncated")
        return response.get("result", [])

    async def persist(self, output, payload):
        await self.initialize_schema()
        params = {
            "document_id": str(output.document_id),
            "run_id": str(output.run_id),
            "layer": self.name,
            "content_hash": output.content_hash,
            "created_at": output.created_at.isoformat(),
            "profile_id": output.profile.id,
            "profile_hash": output.profile_hash,
            "artifact_hash": digest(output.model_dump(mode="json")),
            "artifact_json": output.model_dump_json(),
            "run_edge_id": str(uuid5(output.run_id, "document-edge")),
        }
        expected_nodes, expected_edges = [], []
        async with self.graph.transaction() as tx:
            sources = self.rows(
                await tx.query("SELECT content FROM Document WHERE id=:document_id", params)
            )
            if len(sources) != 1 or sources[0].get("content") is None:
                raise ValueError("emotion_source_missing_in_graph")

            if content_hash(sources[0]["content"]) != output.content_hash:
                raise ValueError("emotion_graph_source_changed")
            existing = self.rows(
                await tx.query(
                    "SELECT artifact_hash FROM EmotionExtraction WHERE id=:run_id", params
                )
            )
            if existing and existing != [{"artifact_hash": params["artifact_hash"]}]:
                raise ValueError("emotion_run_conflict")
            # This layer owns replacement of its vertices and incident relations.
            # Generation and validation already succeeded; rollback retains the old layer.
            await tx.command(
                "MATCH (n) WHERE n.document_id=$document_id AND "
                "(n:EmotionExtraction OR n:Emotion) AND (n.run_id IS NULL OR n.run_id<>$run_id) "
                "DETACH DELETE n",
                params,
                language="cypher",
            )
            await tx.command(
                """
MATCH (document:Document {id:$document_id})
MERGE (run:EmotionExtraction {id:$run_id})
SET run.document_id=$document_id, run.run_id=$run_id, run.layer=$layer,
    run.profile_id=$profile_id, run.profile_hash=$profile_hash,
    run.content_hash=$content_hash, run.created_at=$created_at,
    run.artifact_hash=$artifact_hash, run.artifact_json=$artifact_json
MERGE (document)-[edge:HAS_EMOTION_EXTRACTION {id:$run_edge_id}]->(run)
SET edge.document_id=$document_id, edge.run_id=$run_id, edge.layer=$layer,
    edge.profile_id=$profile_id, edge.profile_hash=$profile_hash
""",
                params,
                language="cypher",
            )
            for emotion in payload.emotions:
                key = self.label_key(emotion.label)
                values = {
                    **params,
                    "emotion_id": str(uuid5(output.run_id, f"emotion:{key}")),
                    "label": emotion.label,
                }
                await tx.command(
                    """
MATCH (run:EmotionExtraction {id:$run_id})
MERGE (emotion:Emotion {id:$emotion_id})
SET emotion.document_id=$document_id, emotion.run_id=$run_id, emotion.layer=$layer,
    emotion.profile_id=$profile_id, emotion.profile_hash=$profile_hash,
    emotion.label=$label
""",
                    values,
                    language="cypher",
                )
                expected_nodes.append({"id": values["emotion_id"], "label": emotion.label})
                for quote in emotion.quotes:
                    start = sources[0]["content"].index(quote)
                    end = start + len(quote)
                    evidence = {
                        **values,
                        "edge_id": str(uuid5(output.run_id, f"emotion-edge:{key}:{start}:{end}")),
                        "quote": quote,
                        "start_char": start,
                        "end_char": end,
                    }
                    await tx.command(
                        """
MATCH (run:EmotionExtraction {id:$run_id}), (emotion:Emotion {id:$emotion_id})
MERGE (run)-[edge:HAS_EMOTION {id:$edge_id}]->(emotion)
SET edge.document_id=$document_id, edge.run_id=$run_id, edge.layer=$layer,
    edge.profile_id=$profile_id, edge.profile_hash=$profile_hash,
    edge.quote=$quote, edge.start_char=$start_char, edge.end_char=$end_char
""",
                        evidence,
                        language="cypher",
                    )
                    expected_edges.append(
                        {
                            "id": evidence["edge_id"],
                            "emotion_id": evidence["emotion_id"],
                            "quote": quote,
                            "start_char": start,
                            "end_char": end,
                        }
                    )
            # Verify both endpoints and the full result in the transaction; no false success
            # when MATCH finds no source, a partial write occurs, or a retry adds duplicates.
            actual_run = self.rows(
                await tx.query(
                    """
MATCH (d:Document {id:$document_id})-[e:HAS_EMOTION_EXTRACTION]->
      (r:EmotionExtraction {id:$run_id})
RETURN e.id AS id, r.artifact_hash AS artifact_hash
""",
                    params,
                    language="cypher",
                )
            )
            if actual_run != [
                {"id": params["run_edge_id"], "artifact_hash": params["artifact_hash"]}
            ]:
                raise ValueError("emotion_run_verification_failed")
            actual_nodes = self.rows(
                await tx.query(
                    "SELECT id, label FROM Emotion WHERE run_id=:run_id",
                    params,
                )
            )
            actual_edges = self.rows(
                await tx.query(
                    """
MATCH (r:EmotionExtraction {id:$run_id})-[e:HAS_EMOTION]->(n:Emotion)
RETURN e.id AS id, n.id AS emotion_id, e.quote AS quote,
       e.start_char AS start_char, e.end_char AS end_char
""",
                    params,
                    language="cypher",
                )
            )
            if sorted(actual_nodes, key=lambda n: n["id"]) != sorted(
                expected_nodes, key=lambda n: n["id"]
            ):
                raise ValueError("emotion_nodes_verification_failed")
            if sorted(actual_edges, key=lambda n: n["id"]) != sorted(
                expected_edges, key=lambda n: n["id"]
            ):
                raise ValueError("emotion_edges_verification_failed")
