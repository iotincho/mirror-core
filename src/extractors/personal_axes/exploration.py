"""Bounded, axis-scoped reads. Evidence is read exclusively from relationships."""

import json
from contextlib import asynccontextmanager
from uuid import UUID

from src.extractors.contracts import content_hash
from src.extractors.personal_axes.contracts import AxisError, label_key
from src.extractors.personal_axes.pagination import decode, encode, next_cursor, page, position
from src.extractors.personal_axes.store import rows
from src.services.document_store import DocumentNotFoundError

TYPES = {"AxisExtraction", "AxisFinding", "HAS_AXIS_EXTRACTION", "HAS_AXIS_FINDING"}
FIELDS = "id, document_id, axis_id, version_id, run_id, title, content, tags_json, content_hash"


class AxisExploration:
    def __init__(self, previews):
        self.previews = previews
        self.axes, self.runtime, self.owner = previews.axes, previews.runtime, previews.owner
        self.client = self.runtime.graph_store.database_client

    @asynccontextmanager
    async def read(self, axis_id, version_id):
        await self.axes.get(self.owner, axis_id)
        if version_id:
            await self.axes.version(self.owner, axis_id, version_id)
        try:
            async with self.client.transaction() as tx:
                names = {r["name"] for r in rows(await tx.query("SELECT name FROM schema:types"))}
                present = TYPES & names
                if present and present != TYPES:
                    raise AxisError("axis_graph_incomplete", 503)
                yield tx if present else None
        except AxisError:
            raise
        except Exception:
            # Driver errors can contain parameters and material from private notes.
            raise AxisError("axis_graph_unavailable", 503) from None

    def scope(self, axis_id, version_id, root):
        return [str(self.owner), str(axis_id), str(version_id or ""), root]

    @staticmethod
    def where(axis_id, version_id):
        condition = "axis_id=:axis_id"
        params = {"axis_id": str(axis_id)}
        if version_id:
            condition += " AND version_id=:version_id"
            params["version_id"] = str(version_id)
        return condition, params

    async def document(self, identifier):
        try:
            return await self.runtime.document_store.get(UUID(str(identifier)))
        except DocumentNotFoundError:
            raise AxisError("axis_source_unavailable", 409) from None

    async def finding_views(self, tx, findings):
        if not findings:
            return []
        ids = [row["id"] for row in findings]
        evidence = rows(
            await tx.query(
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
        )
        if len(evidence) > 3000:
            raise AxisError("axis_graph_limit", 422)
        documents, result = {}, []
        for row in findings:
            identifier = row["document_id"]
            if identifier not in documents:
                documents[identifier] = await self.document(identifier)
            document = documents[identifier]
            if content_hash(document.content) != row["content_hash"]:
                raise AxisError("axis_source_changed")
            quotes = [edge for edge in evidence if edge["finding_id"] == row["id"]]
            if not quotes or len(quotes) > 30:
                raise AxisError("axis_evidence_invalid", 503)
            for edge in quotes:
                if any(
                    edge[key] != row[key]
                    for key in ("axis_id", "version_id", "document_id", "run_id")
                ) or (
                    edge["extraction_id"],
                    edge["extraction_axis"],
                    edge["extraction_version"],
                    edge["extraction_document"],
                ) != (row["run_id"], row["axis_id"], row["version_id"], identifier):
                    raise AxisError("axis_evidence_invalid", 503)
                start, end = edge["start_char"], edge["end_char"]
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or not 0 <= start < end <= len(document.content)
                    or document.content[start:end] != edge["quote"]
                ):
                    raise AxisError("axis_evidence_invalid", 503)
            result.append(
                {
                    key: row[key]
                    for key in (
                        "id",
                        "document_id",
                        "axis_id",
                        "version_id",
                        "run_id",
                        "title",
                        "content",
                    )
                }
                | {
                    "tags": json.loads(row["tags_json"]),
                    "evidence": [
                        {key: edge[key] for key in ("id", "quote", "start_char", "end_char")}
                        for edge in quotes
                    ],
                    "document_title": document.title or "Nota",
                }
            )
        return result

    async def finding(self, axis_id, finding_id, version_id=None):
        async with self.read(axis_id, version_id) as tx:
            condition, params = self.where(axis_id, version_id)
            params["id"] = str(finding_id)
            selected = (
                rows(
                    await tx.query(
                        f"SELECT {FIELDS} FROM AxisFinding WHERE {condition} AND id=:id LIMIT 2",
                        params,
                    )
                )
                if tx
                else []
            )
            if not selected:
                raise AxisError("axis_finding_not_found", 404)
            if len(selected) != 1:
                raise AxisError("axis_graph_incomplete", 503)
            return (await self.finding_views(tx, selected))[0]

    async def findings(self, axis_id, version_id=None, document_id=None, cursor=None, limit=30):
        scope = self.scope(axis_id, version_id, f"findings:{document_id or ''}")
        after = position(cursor, scope)
        async with self.read(axis_id, version_id) as tx:
            condition, params = self.where(axis_id, version_id)
            if document_id:
                await self.document(document_id)
                condition += " AND document_id=:document_id"
                params["document_id"] = str(document_id)
            params.update(after_key=after, page_size=limit + 1)
            selected = (
                rows(
                    await tx.query(
                        f"SELECT {FIELDS} FROM AxisFinding WHERE {condition} "
                        "AND id>:after_key ORDER BY id LIMIT :page_size",
                        params,
                    )
                )
                if tx
                else []
            )
            following = (
                next_cursor(selected[limit - 1]["id"], scope) if len(selected) > limit else None
            )
            return {
                "axis_id": str(axis_id),
                "version_id": version_id,
                "next_cursor": following,
                "items": await self.finding_views(tx, selected[:limit]),
                "limit": limit,
            }

    async def tags(self, axis_id, version_id=None, cursor=None, limit=50):
        scope = self.scope(axis_id, version_id, "tags")
        position(cursor, scope)
        async with self.read(axis_id, version_id) as tx:
            condition, params = self.where(axis_id, version_id)
            # Only tag metadata is scanned. Refuse overflow rather than return wrong counts.
            selected = (
                rows(
                    await tx.query(
                        f"SELECT id, document_id, tags_json FROM AxisFinding WHERE {condition} "
                        "ORDER BY id LIMIT 10001",
                        params,
                    )
                )
                if tx
                else []
            )
            if len(selected) > 10000:
                raise AxisError("axis_catalogue_limit", 422)
            catalogue = {}
            for finding in selected:
                for tag in json.loads(finding["tags_json"]):
                    key = label_key(tag)
                    item = catalogue.setdefault(key, {"key": key, "label": tag, "documents": set()})
                    item["documents"].add(finding["document_id"])
            selected, following = page(
                list(catalogue.values()), scope, cursor, limit, lambda item: item["key"]
            )
            return {
                "axis_id": str(axis_id),
                "version_id": version_id,
                "next_cursor": following,
                "items": [
                    {
                        "id": self.tag_id(axis_id, item["key"]),
                        "key": item["key"],
                        "label": item["label"],
                        "document_count": len(item["documents"]),
                    }
                    for item in selected
                ],
            }

    @staticmethod
    def tag_id(axis_id, key):
        return f"AxisTag:{axis_id}:{encode(key)}"

    async def neighbors(self, axis_id, node_id=None, version_id=None, cursor=None, limit=30):
        root = node_id or f"Axis:{axis_id}"
        scope = self.scope(axis_id, version_id, root)
        after = position(cursor, scope)
        async with self.read(axis_id, version_id) as tx:
            condition, params = self.where(axis_id, version_id)
            params.update(after_key=after, page_size=limit + 1)
            nodes, edges, following = {}, [], None
            if root == f"Axis:{axis_id}":
                axis = (
                    await self.axes.version(self.owner, axis_id, version_id)
                    if version_id
                    else await self.axes.get(self.owner, axis_id)
                )
                nodes[root] = {"id": root, "type": "Axis", "label": axis["version"]["title"]}
                selected = (
                    rows(
                        await tx.query(
                            "SELECT DISTINCT document_id FROM AxisExtraction WHERE "
                            + condition
                            + " AND document_id>:after_key ORDER BY document_id LIMIT :page_size",
                            params,
                        )
                    )
                    if tx
                    else []
                )
                if len(selected) > limit:
                    following = next_cursor(selected[limit - 1]["document_id"], scope)
                for row in selected[:limit]:
                    document = await self.document(row["document_id"])
                    identifier = f"Document:{document.id}"
                    nodes[identifier] = self.note_node(document)
                    edges.append(
                        {
                            "id": root + ":" + identifier,
                            "source": root,
                            "target": identifier,
                            "type": "AXIS_NOTE",
                        }
                    )
            elif root.startswith("AxisFinding:"):
                finding_id = self.uuid_suffix(root, "AxisFinding:")
                selected = (
                    rows(
                        await tx.query(
                            f"SELECT {FIELDS} FROM AxisFinding WHERE {condition} "
                            "AND id=:id LIMIT 2",
                            params | {"id": str(finding_id)},
                        )
                    )
                    if tx
                    else []
                )
                if not selected:
                    raise AxisError("axis_finding_not_found", 404)
                finding = (await self.finding_views(tx, selected))[0]
                self.add_finding(nodes, edges, finding, axis_id)
                candidates = [n for n in nodes.values() if n["id"] != root]
                chosen, following = page(candidates, scope, cursor, limit, lambda n: n["id"])
                nodes = {n["id"]: n for n in chosen} | {root: nodes[root]}
                edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
            else:
                tag = None
                if root.startswith("Document:"):
                    identifier = self.uuid_suffix(root, "Document:")
                    document = await self.document(identifier)
                    nodes[root] = self.note_node(document)
                    condition += " AND document_id=:document_id"
                    params["document_id"] = str(identifier)
                elif root.startswith(f"AxisTag:{axis_id}:"):
                    try:
                        tag = decode(root.split(":", 2)[2])
                        if (
                            not tag
                            or len(tag) > 640
                            or label_key(tag) != tag
                            or self.tag_id(axis_id, tag) != root
                        ):
                            raise ValueError()
                    except (ValueError, UnicodeError):
                        raise AxisError("axis_node_invalid", 422) from None
                    nodes[root] = {"id": root, "type": "AxisTagGroup", "label": tag}
                    condition += " AND :tag IN tag_keys"
                    params["tag"] = tag
                else:
                    raise AxisError("axis_node_invalid", 422)
                selected = (
                    rows(
                        await tx.query(
                            f"SELECT {FIELDS} FROM AxisFinding WHERE {condition} "
                            "AND id>:after_key ORDER BY id LIMIT :page_size",
                            params,
                        )
                    )
                    if tx
                    else []
                )
                if len(selected) > limit:
                    following = next_cursor(selected[limit - 1]["id"], scope)
                views = await self.finding_views(tx, selected[:limit])
                for finding in views:
                    self.add_finding(nodes, edges, finding, axis_id, tag=tag, include_tags=False)
            return {
                "axis_id": str(axis_id),
                "version_id": version_id,
                "root_id": root,
                "nodes": list(nodes.values()),
                "edges": edges,
                "next_cursor": following,
                "limit": limit,
            }

    @staticmethod
    def uuid_suffix(value, prefix):
        try:
            identifier = UUID(value.removeprefix(prefix))
            if value != f"{prefix}{identifier}":
                raise ValueError()
            return identifier
        except ValueError:
            raise AxisError("axis_node_invalid", 422) from None

    @staticmethod
    def note_node(document):
        return {
            "id": f"Document:{document.id}",
            "type": "Document",
            "label": document.title or "Nota",
            "document_id": str(document.id),
        }

    def add_finding(self, nodes, edges, finding, axis_id, *, tag=None, include_tags=True):
        node = f"AxisFinding:{finding['id']}"
        document = f"Document:{finding['document_id']}"
        origin = {key: finding[key] for key in ("document_id", "axis_id", "version_id", "run_id")}
        nodes[node] = {"id": node, "type": "AxisFinding", "label": finding["title"], **origin}
        nodes[document] = {
            "id": document,
            "type": "Document",
            "label": finding["document_title"],
            "document_id": finding["document_id"],
        }
        for evidence in finding["evidence"]:
            edges.append(
                {
                    "id": f"AxisEvidence:{evidence['id']}",
                    "source": document,
                    "target": node,
                    "type": "HAS_FINDING",
                    **origin,
                    **{key: evidence[key] for key in ("quote", "start_char", "end_char")},
                }
            )
        for label in finding["tags"]:
            key = label_key(label)
            if not include_tags and key != tag:
                continue
            identifier = self.tag_id(axis_id, key)
            nodes.setdefault(identifier, {"id": identifier, "type": "AxisTagGroup", "label": label})
            edges.append(
                {
                    "id": node + ":" + identifier,
                    "source": node,
                    "target": identifier,
                    "type": "HAS_TAG",
                }
            )


async def preview_neighbors(service, preview_id, node_id=None, cursor=None, limit=30):
    results = await service.results(preview_id)
    graph = results["graph"]
    root = node_id or graph["root_id"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    if root not in nodes:
        raise AxisError("axis_node_not_found", 404)
    revision = results["preview"]["revision_hash"]
    scope = [str(service.owner), str(preview_id), revision, root]
    edges = [e for e in graph["edges"] if root in (e["source"], e["target"])]
    neighbors = {e["target"] if e["source"] == root else e["source"] for e in edges}
    chosen, following = page(list(neighbors), scope, cursor, limit, lambda item: item)
    visible = set(chosen) | {root}
    return {
        "preview_id": str(preview_id),
        "revision_hash": revision,
        "root_id": root,
        "nodes": [nodes[n] for n in sorted(visible)],
        "edges": [e for e in edges if e["source"] in visible and e["target"] in visible],
        "next_cursor": following,
        "limit": limit,
    }
