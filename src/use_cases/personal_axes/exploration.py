"""Bounded, axis-scoped reads. Evidence is read exclusively from relationships."""

from contextlib import asynccontextmanager
from uuid import UUID

from src.core.documents.ports import DocumentNotFoundError, DocumentStore
from src.core.extractors.contracts import content_hash
from src.core.extractors.personal_axes.models import AxisError
from src.core.extractors.personal_axes.pagination import decode, encode, next_cursor, page, position
from src.core.extractors.personal_axes.policies import label_key
from src.core.extractors.personal_axes.ports import AxisDefinitions, AxisGraphReads


class AxisExploration:
    def __init__(
        self, definitions: AxisDefinitions, graph: AxisGraphReads, documents: DocumentStore, owner
    ):
        self.axes, self.graph, self.documents, self.owner = definitions, graph, documents, owner

    @asynccontextmanager
    async def read(self, axis_id, version_id):
        await self.axes.get(self.owner, axis_id)
        if version_id:
            await self.axes.version(self.owner, axis_id, version_id)
        async with self.graph.read(axis_id, version_id) as reader:
            yield reader

    async def coverage(self, axis_id, document_id=None):
        async with self.read(axis_id, None) as reader:
            values = await reader.coverage(document_id)
            return {row.document_id: row.model_dump() for row in values}

    def scope(self, axis_id, version_id, root):
        return [str(self.owner), str(axis_id), str(version_id or ""), root]

    async def document(self, identifier):
        try:
            return await self.documents.get(UUID(str(identifier)))
        except DocumentNotFoundError:
            raise AxisError("axis_source_unavailable") from None

    async def finding_views(self, tx, findings):
        if not findings:
            return []
        findings = [row.model_dump() for row in findings]
        ids = [row["id"] for row in findings]
        evidence = [row.model_dump() for row in await tx.evidence(ids)]
        if len(evidence) > 3000:
            raise AxisError("axis_graph_limit")
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
                raise AxisError("axis_evidence_invalid")
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
                    raise AxisError("axis_evidence_invalid")
                start, end = edge["start_char"], edge["end_char"]
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or not 0 <= start < end <= len(document.content)
                    or document.content[start:end] != edge["quote"]
                ):
                    raise AxisError("axis_evidence_invalid")
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
                    "node_id": f"AxisFinding:{row['id']}",
                    "source_hash": row["content_hash"],
                    "tags": list(row["tags"]),
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
            selected = await tx.finding(finding_id)
            if not selected:
                raise AxisError("axis_finding_not_found")
            if len(selected) != 1:
                raise AxisError("axis_graph_incomplete")
            return (await self.finding_views(tx, selected))[0]

    async def findings(self, axis_id, version_id=None, document_id=None, cursor=None, limit=30):
        scope = self.scope(axis_id, version_id, f"findings:{document_id or ''}")
        after = position(cursor, scope)
        async with self.read(axis_id, version_id) as tx:
            if document_id:
                await self.document(document_id)
            selected = await tx.findings(after, limit + 1, document_id=document_id)
            following = (
                next_cursor(selected[limit - 1].id, scope) if len(selected) > limit else None
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
            selected = [row.model_dump() for row in await tx.tags()]
            if len(selected) > 10000:
                raise AxisError("axis_catalogue_limit")
            catalogue = {}
            for finding in selected:
                for tag in finding["tags"]:
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
            nodes, edges, following = {}, [], None
            if root == f"Axis:{axis_id}":
                axis = (
                    await self.axes.version(self.owner, axis_id, version_id)
                    if version_id
                    else await self.axes.get(self.owner, axis_id)
                )
                nodes[root] = {"id": root, "type": "Axis", "label": axis.version.title}
                selected = await tx.document_ids(after, limit + 1)
                if len(selected) > limit:
                    following = next_cursor(selected[limit - 1], scope)
                for identifier in selected[:limit]:
                    document = await self.document(identifier)
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
                selected = await tx.finding(finding_id)
                if not selected:
                    raise AxisError("axis_finding_not_found")
                finding = (await self.finding_views(tx, selected))[0]
                self.add_finding(nodes, edges, finding, axis_id)
                candidates = [n for n in nodes.values() if n["id"] != root]
                chosen, following = page(candidates, scope, cursor, limit, lambda n: n["id"])
                nodes = {n["id"]: n for n in chosen} | {root: nodes[root]}
                nodes[root]["tags_complete"] = all(
                    edge["target"] in nodes for edge in edges if edge["type"] == "HAS_TAG"
                )
                edges = [e for e in edges if e["source"] in nodes and e["target"] in nodes]
            else:
                tag, identifier = None, None
                if root.startswith("Document:"):
                    identifier = self.uuid_suffix(root, "Document:")
                    document = await self.document(identifier)
                    nodes[root] = self.note_node(document)
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
                        raise AxisError("axis_node_invalid") from None
                    nodes[root] = {"id": root, "type": "AxisTagGroup", "label": tag}
                else:
                    raise AxisError("axis_node_invalid")
                selected = await tx.findings(after, limit + 1, document_id=identifier, tag=tag)
                if len(selected) > limit:
                    following = next_cursor(selected[limit - 1].id, scope)
                views = await self.finding_views(tx, selected[:limit])
                for finding in views:
                    self.add_finding(nodes, edges, finding, axis_id, tag=tag, include_tags=True)
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
            raise AxisError("axis_node_invalid") from None

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
        nodes[node] = {
            "id": node,
            "type": "AxisFinding",
            "label": finding["title"],
            "finding_id": finding["id"],
            "tags_complete": include_tags,
            "source_hash": finding["source_hash"],
            **origin,
        }
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
