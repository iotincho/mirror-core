"""This family owns atomic replacement of its document-local ArcadeDB layer."""

import json
from uuid import uuid5

from src.extractors.contracts import content_hash, digest
from src.extractors.personal_axes.contracts import label_key


def rows(response):
    if not isinstance(response, dict) or not isinstance(response.get("result"), list):
        raise ValueError("axis_graph_response_invalid")
    if response.get("truncated"):
        raise ValueError("axis_graph_result_truncated")
    return response.get("result", [])


class ArcadeDBAxisStore:
    def __init__(self, client):
        self.client = client

    async def write(
        self, output, payload, axis_id, version_id, *, write_order=None, legacy_versions=None
    ):
        for kind, name in (
            ("VERTEX", "AxisExtraction"),
            ("VERTEX", "AxisFinding"),
            ("EDGE", "HAS_AXIS_EXTRACTION"),
            ("EDGE", "HAS_AXIS_FINDING"),
        ):
            await self.client.command(f"CREATE {kind} TYPE {name} IF NOT EXISTS")
            await self.client.command(f"CREATE PROPERTY {name}.id IF NOT EXISTS STRING")
            await self.client.command(f"CREATE INDEX IF NOT EXISTS ON {name} (id) UNIQUE")
        for name in ("AxisExtraction", "AxisFinding"):
            for property_name in ("axis_id", "document_id"):
                await self.client.command(
                    f"CREATE PROPERTY {name}.{property_name} IF NOT EXISTS STRING"
                )
            await self.client.command(
                f"CREATE INDEX IF NOT EXISTS ON {name} (axis_id, document_id) NOTUNIQUE"
            )
        params = {
            "document_id": str(output.document_id),
            "run_id": str(output.run_id),
            "axis_id": str(axis_id),
            "version_id": str(version_id),
            "artifact_hash": digest(output.model_dump(mode="json")),
            "artifact_json": output.model_dump_json(),
            "profile_hash": output.profile_hash,
            "profile_id": output.profile.id,
            "layer": f"axis:{axis_id}",
            "run_edge": str(uuid5(output.run_id, "document-edge")),
            "content_hash": output.content_hash,
            "created_at": output.created_at.isoformat(),
            "write_order": write_order or "",
        }
        async with self.client.transaction() as tx:
            current = rows(
                await tx.query(
                    "SELECT write_order, version_id FROM AxisExtraction "
                    "WHERE document_id=:document_id AND axis_id=:axis_id",
                    params,
                )
            )
            for previous in current:
                previous_order = previous.get("write_order") or (
                    f"{(legacy_versions or {}).get(previous.get('version_id'), 0):012d}:"
                )
                if write_order and previous_order > write_order:
                    return False
                if not write_order and previous.get("write_order"):
                    return False
            source = rows(
                await tx.query("SELECT content FROM Document WHERE id=:document_id", params)
            )
            if len(source) != 1 or content_hash(source[0]["content"]) != output.content_hash:
                raise ValueError("axis_graph_source_changed")
            existing = rows(
                await tx.query("SELECT artifact_hash FROM AxisExtraction WHERE id=:run_id", params)
            )
            if existing and existing != [{"artifact_hash": params["artifact_hash"]}]:
                raise ValueError("axis_run_conflict")
            await tx.command(
                "MATCH (n) WHERE n.document_id=$document_id AND n.axis_id=$axis_id "
                "AND (n:AxisExtraction OR n:AxisFinding) AND n.run_id<>$run_id DETACH DELETE n",
                params,
                language="cypher",
            )
            await tx.command(
                """
MATCH (d:Document {id:$document_id})
SET d.axis_write_guard=$run_id
MERGE (r:AxisExtraction {id:$run_id})
SET r.document_id=$document_id, r.axis_id=$axis_id, r.version_id=$version_id,
    r.run_id=$run_id, r.artifact_hash=$artifact_hash, r.artifact_json=$artifact_json,
    r.profile_hash=$profile_hash, r.profile_id=$profile_id, r.layer=$layer,
    r.content_hash=$content_hash, r.created_at=$created_at,
    r.visualizable=false, r.write_order=$write_order
MERGE (d)-[e:HAS_AXIS_EXTRACTION {id:$run_edge}]->(r)
SET e.document_id=$document_id, e.run_id=$run_id, e.layer=$layer, e.visualizable=false
""",
                params,
                language="cypher",
            )
            # Repair a replay of the early representation (one unquoted edge and
            # evidence_json on the finding), without keeping duplicate connections.
            await tx.command(
                "MATCH (r:AxisExtraction {id:$run_id})-[e:HAS_AXIS_FINDING]->() "
                "WHERE e.quote IS NULL DELETE e",
                params,
                language="cypher",
            )
            expected_nodes, expected_edges = [], []
            for index, finding in enumerate(payload.findings):
                values = {
                    **params,
                    "finding_id": str(uuid5(output.run_id, f"finding:{index}")),
                    "title": finding.title,
                    "content": finding.content,
                    "tags_json": json.dumps(finding.tags, ensure_ascii=False),
                    "tag_keys": [label_key(tag) for tag in finding.tags],
                }
                await tx.command(
                    """
MATCH (r:AxisExtraction {id:$run_id})
MERGE (n:AxisFinding {id:$finding_id})
SET n.document_id=$document_id, n.axis_id=$axis_id, n.version_id=$version_id,
    n.run_id=$run_id, n.title=$title, n.content=$content, n.layer=$layer,
    n.tags_json=$tags_json, n.tag_keys=$tag_keys, n.visualizable=false,
    n.content_hash=$content_hash, n.created_at=$created_at
REMOVE n.evidence_json, n.quote, n.start_char, n.end_char
""",
                    values,
                    language="cypher",
                )
                expected_nodes.append(
                    {
                        key: values[key]
                        for key in (
                            "finding_id",
                            "title",
                            "content",
                            "tags_json",
                        )
                    }
                )
                for item in finding.evidence:
                    start = source[0]["content"].index(item.quote)
                    end = start + len(item.quote)
                    evidence = {
                        **values,
                        "edge_id": str(uuid5(output.run_id, f"finding-edge:{index}:{start}:{end}")),
                        "quote": item.quote,
                        "start_char": start,
                        "end_char": end,
                    }
                    await tx.command(
                        """
MATCH (r:AxisExtraction {id:$run_id}), (n:AxisFinding {id:$finding_id})
MERGE (r)-[e:HAS_AXIS_FINDING {id:$edge_id}]->(n)
SET e.document_id=$document_id, e.axis_id=$axis_id, e.version_id=$version_id,
    e.run_id=$run_id, e.layer=$layer, e.visualizable=false,
    e.quote=$quote, e.start_char=$start_char, e.end_char=$end_char
""",
                        evidence,
                        language="cypher",
                    )
                    expected_edges.append(
                        {
                            key: evidence[key]
                            for key in ("finding_id", "edge_id", "quote", "start_char", "end_char")
                        }
                    )
            actual_run = rows(
                await tx.query(
                    """
MATCH (d:Document {id:$document_id})-[e:HAS_AXIS_EXTRACTION]->(r:AxisExtraction {id:$run_id})
RETURN e.id AS edge_id, r.artifact_hash AS artifact_hash
""",
                    params,
                    language="cypher",
                )
            )
            if actual_run != [
                {"edge_id": params["run_edge"], "artifact_hash": params["artifact_hash"]}
            ]:
                raise ValueError("axis_run_verification_failed")
            actual_nodes = rows(
                await tx.query(
                    "SELECT id AS finding_id, title, content, tags_json "
                    "FROM AxisFinding WHERE run_id=:run_id",
                    params,
                )
            )
            actual_edges = rows(
                await tx.query(
                    """
MATCH (r:AxisExtraction {id:$run_id})-[e:HAS_AXIS_FINDING]->(n:AxisFinding)
RETURN n.id AS finding_id, e.id AS edge_id, e.quote AS quote,
       e.start_char AS start_char, e.end_char AS end_char
""",
                    params,
                    language="cypher",
                )
            )
            if sorted(actual_nodes, key=lambda v: v["finding_id"]) != sorted(
                expected_nodes, key=lambda v: v["finding_id"]
            ):
                raise ValueError("axis_findings_verification_failed")
            if sorted(actual_edges, key=lambda v: v["edge_id"]) != sorted(
                expected_edges, key=lambda v: v["edge_id"]
            ):
                raise ValueError("axis_evidence_verification_failed")
        return True
