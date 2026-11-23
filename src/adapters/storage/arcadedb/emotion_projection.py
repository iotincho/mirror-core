"""Read-only, document/emotion projection grouped by normalized labels."""

import hashlib
import json
from collections import defaultdict
from uuid import UUID

from src.core.extractors.emotions import label_key
from src.core.graph.contracts import (
    EmotionCatalog,
    EmotionCatalogItem,
    EmotionExploration,
    GraphEdge,
    GraphEvidence,
    GraphEvidenceSource,
    GraphNode,
)
from src.core.graph.ports import EmotionNotFoundError, GraphPersistenceError

MEMBERSHIPS = """
MATCH (d:Document)-[:HAS_EMOTION_EXTRACTION]->(r:EmotionExtraction)-[:HAS_EMOTION]->(n:Emotion)
RETURN DISTINCT d.id AS document_id, n.label AS label{metadata}
ORDER BY document_id, label SKIP $offset LIMIT $limit
"""
LABELS = """
MATCH (d:Document)-[:HAS_EMOTION_EXTRACTION]->(r:EmotionExtraction)-[:HAS_EMOTION]->(n:Emotion)
RETURN DISTINCT n.label AS label
ORDER BY label SKIP $offset LIMIT $limit
"""
DOCUMENT_IDENTITY = """
MATCH (d:Document) WHERE d.id = $document_id
RETURN d.metadata_json AS metadata_json
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


def audio_id(metadata_json):
    metadata = json.loads(metadata_json or "{}")
    value = metadata.get("audio_note_id")
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def note_node_id(document_id, audio_by_document):
    if original := audio_by_document.get(document_id):
        return f"AudioNote:{original}"
    return f"Document:{document_id}"


def group_id(key):
    return "EmotionGroup:" + hashlib.sha256(key.encode()).hexdigest()


def connection_id(document_id, key):
    value = json.dumps([document_id, key], ensure_ascii=False)
    return "EmotionConnection:" + hashlib.sha256(value.encode()).hexdigest()


class EmotionProjection:
    def __init__(self, client, rows):
        self.client, self.rows = client, rows

    async def pages(self, tx, query, params=None):
        offset = 0
        while True:
            batch = self.rows(
                await tx.query(
                    query,
                    {**(params or {}), "offset": offset, "limit": PAGE_SIZE},
                    language="cypher",
                )
            )
            offset += len(batch)
            if offset > MAX_ROWS:
                raise GraphPersistenceError("Emotion exploration scan limit exceeded")
            yield batch
            if len(batch) < PAGE_SIZE:
                return

    async def has_emotion_types(self, tx):
        types = self.rows(await tx.query("SELECT name FROM schema:types"))
        return REQUIRED_TYPES.issubset({item["name"] for item in types})

    async def resolve_label(self, key):
        async with self.client.transaction() as tx:
            if await self.has_emotion_types(tx):
                async for page in self.pages(tx, LABELS):
                    if any(label_key(row["label"]) == key for row in page):
                        return key
        raise EmotionNotFoundError("Emotion not found")

    async def memberships(self, tx, group_audio):
        groups = defaultdict(set)
        audio_by_document = {}
        if await self.has_emotion_types(tx):
            metadata = ", d.metadata_json AS metadata_json" if group_audio else ""
            async for page in self.pages(tx, MEMBERSHIPS.format(metadata=metadata)):
                for row in page:
                    doc_id = row.get("document_id")
                    if not doc_id or not isinstance(row.get("label"), str):
                        raise GraphPersistenceError("Emotion membership has no stable identity")
                    key = label_key(row["label"])
                    if not key:
                        raise GraphPersistenceError("Emotion membership has an empty label")
                    groups[key].add(doc_id)
                    if group_audio and doc_id not in audio_by_document:
                        audio_by_document[doc_id] = audio_id(row.get("metadata_json"))
        return groups, audio_by_document

    async def catalog(self, offset, limit, *, group_audio=False):
        async with self.client.transaction() as tx:
            groups, audio_by_document = await self.memberships(tx, group_audio)
        items = sorted(
            [
                EmotionCatalogItem(
                    key=key,
                    id=group_id(key),
                    label=key,
                    document_count=len(ids),
                    entry_count=len({note_node_id(doc, audio_by_document) for doc in ids})
                    if group_audio
                    else None,
                )
                for key, ids in groups.items()
            ],
            key=lambda item: (-(item.entry_count or item.document_count), item.key),
        )
        end = offset + limit
        return EmotionCatalog(
            emotions=items[offset:end],
            total=len(items),
            next_offset=end if end < len(items) else None,
        )

    async def explore(self, emotion, depth, limit, *, group_audio=False):
        return await self.neighborhood("emotion", label_key(emotion), depth, limit, group_audio)

    async def document_neighborhood(self, document_id, limit, *, group_audio=False):
        return await self.neighborhood("document", document_id, 1, limit, group_audio)

    async def neighborhood(self, kind, key, depth, limit, group_audio):
        async with self.client.transaction() as tx:
            groups, audio_by_document = await self.memberships(tx, group_audio)
            if kind == "emotion" and key not in groups:
                raise EmotionNotFoundError("Emotion not found")
            if kind == "document" and group_audio and key not in audio_by_document:
                rows = self.rows(
                    await tx.query(DOCUMENT_IDENTITY, {"document_id": key}, language="cypher")
                )
                if len(rows) != 1:
                    raise GraphPersistenceError("Emotion exploration document missing")
                audio_by_document[key] = audio_id(rows[0].get("metadata_json"))

            by_entry = defaultdict(set)
            documents_by_entry = defaultdict(set)
            entries_by_label = defaultdict(set)
            for label, documents in groups.items():
                for doc_id in documents:
                    entry = note_node_id(doc_id, audio_by_document)
                    by_entry[entry].add(label)
                    documents_by_entry[entry].add(doc_id)
                    entries_by_label[label].add(entry)
            if kind == "document":
                root = note_node_id(key, audio_by_document)
                documents_by_entry[root].add(key)
            else:
                root = key
            # A level is one hop in the projected bipartite graph, not the storage graph.
            included = {(kind, root)}
            frontier = set(included)
            truncated = False
            for _ in range(depth):
                neighbors = set()
                for entity_kind, identifier in frontier:
                    if entity_kind == "emotion":
                        neighbors.update(
                            ("document", entry) for entry in entries_by_label[identifier]
                        )
                    else:
                        neighbors.update(("emotion", label) for label in by_entry[identifier])
                candidates = sorted(neighbors - included)
                available = max(limit - len(included), 0)
                if len(candidates) > available:
                    truncated = True
                frontier = set(candidates[:available])
                included.update(frontier)
                if truncated or not frontier:
                    break
            entries = sorted(identifier for kind, identifier in included if kind == "document")
            document_ids = sorted({doc for entry in entries for doc in documents_by_entry[entry]})
            keys = {identifier for kind, identifier in included if kind == "emotion"}
            nodes = [
                GraphNode(
                    id=group_id(label),
                    type="EmotionGroup",
                    label=label,
                    layer="emotions",
                    document_count=len(groups[label]),
                    entry_count=len(entries_by_label[label]) if group_audio else None,
                )
                for label in sorted(keys)
            ]
            edges = []
            if document_ids:
                documents, evidence = await self.read_documents_and_evidence(
                    tx, document_ids, groups, keys
                )
                for entry in entries:
                    entry_documents = sorted(documents_by_entry[entry])
                    first_document = entry_documents[0]
                    original = audio_by_document.get(first_document)
                    representative = original if original in entry_documents else first_document
                    nodes.append(
                        GraphNode(
                            id=entry,
                            type="Document",
                            label=documents[representative],
                            document_id=representative,
                            document_ids=entry_documents if group_audio else None,
                            audio_note_id=original,
                        )
                    )
                by_connection = defaultdict(list)
                for (doc, label), citations in sorted(evidence.items()):
                    by_connection[(note_node_id(doc, audio_by_document), label)].extend(citations)
                for (entry, label), citations in sorted(by_connection.items()):
                    identity = entry.removeprefix("Document:")
                    edges.append(
                        GraphEdge(
                            id=connection_id(identity, label),
                            source=entry,
                            target=group_id(label),
                            type="REPORTS_EMOTION",
                            layer="emotions",
                            evidence=citations,
                        )
                    )
        return EmotionExploration(
            document_id=key if kind == "document" else None,
            root_id=root if kind == "document" else group_id(key),
            depth=depth,
            limit=limit,
            nodes=sorted(nodes, key=lambda node: node.id),
            edges=edges,
            truncated=truncated,
            next_limit=min(limit * 2, 500) if truncated and limit < 500 else None,
        )

    async def read_documents_and_evidence(self, tx, document_ids, groups, keys):
        titles = {}
        evidence = {}
        scanned = 0
        # Keep at most one batch of original texts in memory, including audio aliases.
        for index in range(0, len(document_ids), 100):
            batch = document_ids[index : index + 100]
            documents = self.rows(
                await tx.query(DOCUMENTS, {"document_ids": batch}, language="cypher")
            )
            if {d["id"] for d in documents} != set(batch) or len(documents) != len(batch):
                raise GraphPersistenceError("Emotion exploration document missing")
            contents = {doc["id"]: doc.get("content") or "" for doc in documents}
            for doc in documents:
                metadata = json.loads(doc.get("metadata_json") or "{}")
                title = doc.get("title") or metadata.get("title") or metadata.get("filename")
                titles[doc["id"]] = (
                    title
                    or next(
                        (line.strip() for line in contents[doc["id"]].splitlines() if line.strip()),
                        "Nota",
                    )[:80]
                )
            if not keys:
                continue
            buckets = defaultdict(dict)
            async for page in self.pages(tx, EVIDENCE, {"document_ids": batch}):
                scanned += len(page)
                if scanned > MAX_ROWS:
                    raise GraphPersistenceError("Emotion exploration scan limit exceeded")
                for row in page:
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
                        or end > len(contents[doc_id])
                        or contents[doc_id][start:end] != quote
                    ):
                        raise GraphPersistenceError("Emotion exploration evidence is incomplete")
                    identity = (quote, start, end)
                    bucket = buckets[(doc_id, label)]
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
            expected = {(doc, label) for label in keys for doc in batch if doc in groups[label]}
            if set(buckets) != expected:
                raise GraphPersistenceError("Emotion exploration connections missing")
            for membership, bucket in buckets.items():
                citations = sorted(
                    bucket.values(), key=lambda item: (item.start_char, item.end_char, item.quote)
                )
                for citation in citations:
                    citation.sources.sort(key=lambda source: (source.run_id, source.edge_id))
                evidence[membership] = citations
        return titles, evidence
