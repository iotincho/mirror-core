"""Consistent semantic reads of an axis layer; no client/transaction leaks through its port."""

import json
from contextlib import asynccontextmanager

from src.adapters.storage.arcadedb.personal_axes import rows
from src.core.extractors.personal_axes.models import AxisError
from src.core.extractors.personal_axes.read_models import (
    CoverageFacts,
    EvidenceFacts,
    FindingFacts,
    TagFacts,
)

TYPES = {"AxisExtraction", "AxisFinding", "HAS_AXIS_EXTRACTION", "HAS_AXIS_FINDING"}
FIELDS = "id, document_id, axis_id, version_id, run_id, title, content, tags_json, content_hash"


class ArcadeDBAxisReads:
    def __init__(self, client):
        self._client = client

    @asynccontextmanager
    async def read(self, axis_id, version_id=None):
        try:
            async with self._client.transaction() as tx:
                names = {r["name"] for r in rows(await tx.query("SELECT name FROM schema:types"))}
                present = TYPES & names
                if present and present != TYPES:
                    raise AxisError("axis_graph_incomplete")
                yield AxisRead(tx if present else None, axis_id, version_id)
        except AxisError:
            raise
        except Exception:
            raise AxisError("axis_graph_unavailable") from None


class AxisRead:
    def __init__(self, tx, axis_id, version_id):
        self._tx = tx
        self._condition = "axis_id=:axis_id"
        self._params = {"axis_id": str(axis_id)}
        if version_id:
            self._condition += " AND version_id=:version_id"
            self._params["version_id"] = str(version_id)

    async def _rows(self, query, params=None, *, language="sql"):
        if self._tx is None:
            return []
        return rows(await self._tx.query(query, self._params | (params or {}), language=language))

    def _finding(self, row):
        return FindingFacts(
            **{key: value for key, value in row.items() if key != "tags_json"},
            tags=tuple(json.loads(row["tags_json"])),
        )

    async def finding(self, finding_id):
        return [
            self._finding(row)
            for row in await self._rows(
                f"SELECT {FIELDS} FROM AxisFinding WHERE {self._condition} AND id=:id LIMIT 2",
                {"id": str(finding_id)},
            )
        ]

    async def findings(self, after, limit, *, document_id=None, tag=None):
        condition, params = self._condition, {"after_key": after, "page_size": limit}
        if document_id:
            condition += " AND document_id=:document_id"
            params["document_id"] = str(document_id)
        if tag is not None:
            condition += " AND :tag IN tag_keys"
            params["tag"] = tag
        return [
            self._finding(row)
            for row in await self._rows(
                f"SELECT {FIELDS} FROM AxisFinding WHERE {condition} "
                "AND id>:after_key ORDER BY id LIMIT :page_size",
                params,
            )
        ]

    async def evidence(self, ids):
        return [
            EvidenceFacts(**row)
            for row in await self._rows(
                """
MATCH (r:AxisExtraction)-[e:HAS_AXIS_FINDING]->(n:AxisFinding)
WHERE n.id IN $ids
RETURN n.id AS finding_id, r.id AS extraction_id, r.axis_id AS extraction_axis,
       r.version_id AS extraction_version, r.document_id AS extraction_document,
       e.id AS id, e.quote AS quote, e.start_char AS start_char, e.end_char AS end_char,
       e.axis_id AS axis_id, e.version_id AS version_id, e.run_id AS run_id,
       e.document_id AS document_id
ORDER BY e.id LIMIT 3001
""",
                {"ids": ids},
                language="cypher",
            )
        ]

    async def tags(self):
        return [
            TagFacts(
                id=row["id"],
                document_id=row["document_id"],
                tags=tuple(json.loads(row["tags_json"])),
            )
            for row in await self._rows(
                f"SELECT id, document_id, tags_json FROM AxisFinding WHERE {self._condition} "
                "ORDER BY id LIMIT 10001"
            )
        ]

    async def document_ids(self, after, limit):
        return [
            row["document_id"]
            for row in await self._rows(
                "SELECT DISTINCT document_id FROM AxisExtraction WHERE "
                + self._condition
                + " AND document_id>:after_key ORDER BY document_id LIMIT :page_size",
                {"after_key": after, "page_size": limit},
            )
        ]

    async def coverage(self, document_id=None):
        condition, params = self._condition, {}
        if document_id:
            condition += " AND document_id=:document_id"
            params["document_id"] = str(document_id)
        runs = await self._rows(
            "SELECT document_id, version_id, content_hash, profile_hash "
            f"FROM AxisExtraction WHERE {condition} LIMIT 100001",
            params,
        )
        counts = await self._rows(
            "SELECT document_id, count(*) AS total FROM AxisFinding "
            f"WHERE {condition} GROUP BY document_id LIMIT 100001",
            params,
        )
        if len(runs) > 100000 or len(counts) > 100000:
            raise AxisError("axis_catalogue_limit")
        totals = {row["document_id"]: row["total"] for row in counts}
        return [
            CoverageFacts(**row, findings_count=totals.get(row["document_id"], 0)) for row in runs
        ]
