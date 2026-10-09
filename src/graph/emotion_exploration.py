"""Read-only, document/emotion projection grouped by normalized labels."""

import hashlib
import json
import unicodedata
from collections import defaultdict

from src.graph.contracts import (
    EmotionCatalog,
    EmotionCatalogItem,
    EmotionExploration,
    GraphEdge,
    GraphEvidence,
    GraphEvidenceSource,
    GraphNode,
)
from src.services.graph_store import EmotionNotFoundError, GraphPersistenceError

MEMBERSHIPS = """
MATCH (d:Document)-[:HAS_EMOTION_EXTRACTION]->(r:EmotionExtraction)-[:HAS_EMOTION]->(n:Emotion)
RETURN DISTINCT d.id AS document_id, n.label AS label
ORDER BY document_id, label SKIP $offset LIMIT $limit
"""
EVIDENCE = """
MATCH (d:Document)-[:HAS_EMOTION_EXTRACTION]->(r:EmotionExtraction)-[e:HAS_EMOTION]->(n:Emotion)
WHERE d.id IN $document_ids
RETURN d.id AS document_id, n.label AS label, r.id AS run_id,
       n.id AS emotion_id, e.id AS edge_id, e.quote AS quote,
       e.start_char AS start_char, e.end_char AS end_char
ORDER BY document_id, edge_id SKIP $offset LIMIT $limit
"""
DOCUMENTS = """
MATCH (d:Document) WHERE d.id IN $document_ids
RETURN d.id AS id, d.title AS title, d.metadata_json AS metadata_json, d.content AS content
"""
REQUIRED_TYPES = {
    "Document",
    "Emotion",
    "EmotionExtraction",
    "HAS_EMOTION",
    "HAS_EMOTION_EXTRACTION",
}
PAGE_SIZE = 1000
MAX_ROWS = 50000


def label_key(label):
    return " ".join(unicodedata.normalize("NFC", label).casefold().split())


def group_id(key):
    return "EmotionGroup:" + hashlib.sha256(key.encode()).hexdigest()


def connection_id(document_id, key):
    value = json.dumps([document_id, key], ensure_ascii=False)
    return "EmotionConnection:" + hashlib.sha256(value.encode()).hexdigest()


class EmotionProjection:
    def __init__(self, client, rows):
        self.client, self.rows = client, rows

    async def pages(self, tx, query, params=None):
        result = []
        while True:
            batch = self.rows(
                await tx.query(
                    query,
                    {**(params or {}), "offset": len(result), "limit": PAGE_SIZE},
                    language="cypher",
                )
            )
            if len(result) + len(batch) > MAX_ROWS:
                raise GraphPersistenceError("Emotion exploration scan limit exceeded")
            result.extend(batch)
            if len(batch) < PAGE_SIZE:
                return result

    async def memberships(self, tx):
        types = self.rows(await tx.query("SELECT name FROM schema:types"))
        if not REQUIRED_TYPES.issubset({item["name"] for item in types}):
            return {}
        groups = defaultdict(set)
        for row in await self.pages(tx, MEMBERSHIPS):
            if not row.get("document_id") or not isinstance(row.get("label"), str):
                raise GraphPersistenceError("Emotion membership has no stable identity")
            key = label_key(row["label"])
            if not key:
                raise GraphPersistenceError("Emotion membership has an empty label")
            groups[key].add(row["document_id"])
        return dict(groups)

    async def catalog(self, offset, limit):
        async with self.client.transaction() as tx:
            groups = await self.memberships(tx)
        items = sorted(
            [
                EmotionCatalogItem(key=key, id=group_id(key), label=key, document_count=len(ids))
                for key, ids in groups.items()
            ],
            key=lambda item: (-item.document_count, item.key),
        )
        end = offset + limit
        return EmotionCatalog(
            emotions=items[offset:end],
            total=len(items),
            next_offset=end if end < len(items) else None,
        )

    async def explore(self, emotion, depth, limit):
        key = label_key(emotion)
        async with self.client.transaction() as tx:
            groups = await self.memberships(tx)
            if key not in groups:
                raise EmotionNotFoundError("Emotion not found")
            by_document = defaultdict(set)
            for label, documents in groups.items():
                for document_id in documents:
                    by_document[document_id].add(label)
            # A level is one hop in the projected bipartite graph, not the storage graph.
            included = {("emotion", key)}
            frontier = set(included)
            truncated = False
            for _ in range(depth):
                neighbors = set()
                for kind, identifier in frontier:
                    if kind == "emotion":
                        neighbors.update(("document", doc) for doc in groups[identifier])
                    else:
                        neighbors.update(("emotion", label) for label in by_document[identifier])
                candidates = sorted(neighbors - included)
                available = max(limit - len(included), 0)
                if len(candidates) > available:
                    truncated = True
                frontier = set(candidates[:available])
                included.update(frontier)
                if truncated or not frontier:
                    break
            document_ids = sorted(identifier for kind, identifier in included if kind == "document")
            keys = {identifier for kind, identifier in included if kind == "emotion"}
            nodes = [
                GraphNode(
                    id=group_id(label),
                    type="EmotionGroup",
                    label=label,
                    layer="emotions",
                    document_count=len(groups[label]),
                )
                for label in sorted(keys)
            ]
            edges = []
            if document_ids:
                documents = self.rows(
                    await tx.query(DOCUMENTS, {"document_ids": document_ids}, language="cypher")
                )
                if {d["id"] for d in documents} != set(document_ids) or len(documents) != len(
                    document_ids
                ):
                    raise GraphPersistenceError("Emotion exploration document missing")
                for doc in documents:
                    metadata = json.loads(doc.get("metadata_json") or "{}")
                    title = doc.get("title") or metadata.get("title") or metadata.get("filename")
                    title = (
                        title
                        or next(
                            (
                                line.strip()
                                for line in (doc.get("content") or "").splitlines()
                                if line.strip()
                            ),
                            "Nota",
                        )[:80]
                    )
                    nodes.append(
                        GraphNode(
                            id=f"Document:{doc['id']}",
                            type="Document",
                            label=title,
                            document_id=doc["id"],
                        )
                    )
                document_content = {doc["id"]: doc.get("content") or "" for doc in documents}
                evidence = defaultdict(dict)
                for row in await self.pages(tx, EVIDENCE, {"document_ids": document_ids}):
                    label = label_key(row["label"])
                    if label not in keys:
                        continue
                    doc_id = row["document_id"]
                    quote, start, end = row.get("quote"), row.get("start_char"), row.get("end_char")
                    if (
                        not isinstance(quote, str)
                        or not quote.strip()
                        or type(start) is not int
                        or type(end) is not int
                        or start < 0
                        or end <= start
                        or end > len(document_content[doc_id])
                        or document_content[doc_id][start:end] != quote
                    ):
                        raise GraphPersistenceError("Emotion exploration evidence is incomplete")
                    identity = (quote, start, end)
                    bucket = evidence[(doc_id, label)]
                    if identity not in bucket:
                        bucket[identity] = GraphEvidence(
                            document_id=doc_id,
                            quote=quote,
                            start_char=start,
                            end_char=end,
                            sources=[],
                        )
                    source = GraphEvidenceSource(
                        run_id=row["run_id"], emotion_id=row["emotion_id"], edge_id=row["edge_id"]
                    )
                    if source not in bucket[identity].sources:
                        bucket[identity].sources.append(source)
                expected = {
                    (doc, label)
                    for doc in document_ids
                    for label in by_document[doc]
                    if label in keys
                }
                if set(evidence) != expected:
                    raise GraphPersistenceError("Emotion exploration connections missing")
                for (doc, label), bucket in sorted(evidence.items()):
                    citations = sorted(
                        bucket.values(),
                        key=lambda item: (item.start_char, item.end_char, item.quote),
                    )
                    for citation in citations:
                        citation.sources.sort(key=lambda source: (source.run_id, source.edge_id))
                    edges.append(
                        GraphEdge(
                            id=connection_id(doc, label),
                            source=f"Document:{doc}",
                            target=group_id(label),
                            type="REPORTS_EMOTION",
                            layer="emotions",
                            evidence=citations,
                        )
                    )
        return EmotionExploration(
            root_id=group_id(key),
            depth=depth,
            limit=limit,
            nodes=sorted(nodes, key=lambda node: node.id),
            edges=edges,
            truncated=truncated,
            next_limit=min(limit * 2, 500) if truncated and limit < 500 else None,
        )
