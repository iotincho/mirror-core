"""Build a version-scoped preview without persisting any graph vertices."""

from uuid import UUID, uuid5

from src.core.extractors.personal_axes.policies import label_key


def project_preview(preview_id, documents):
    root = f"AxisPreview:{preview_id}"
    nodes = {root: {"id": root, "type": "AxisPreview", "label": "Prueba del eje"}}
    edges = []
    for document in documents:
        note_id = f"Document:{document['document_id']}"
        nodes[note_id] = {
            "id": note_id,
            "type": "Document",
            "document_id": document["document_id"],
            "label": document["title"],
        }
        edges.append(
            {"id": f"{root}:{note_id}", "source": root, "target": note_id, "type": "SAMPLE_NOTE"}
        )
        for finding in document["findings"]:
            finding_id = finding["id"]
            nodes[finding_id] = {
                "id": finding_id,
                "type": "AxisFinding",
                "label": finding["title"],
                "document_id": document["document_id"],
                "finding_id": str(UUID(finding_id.removeprefix("AxisFinding:"))),
                "tags_complete": True,
                "source_hash": document.get("source_hash"),
            }
            for evidence in finding["evidence"]:
                edge_key = (
                    f"evidence:{note_id}:{finding_id}:"
                    f"{evidence['start_char']}:{evidence['end_char']}"
                )
                edges.append(
                    {
                        "id": f"AxisEvidence:{uuid5(preview_id, edge_key)}",
                        "source": note_id,
                        "target": finding_id,
                        "type": "HAS_FINDING",
                        "quote": evidence["quote"],
                        "start_char": evidence["start_char"],
                        "end_char": evidence["end_char"],
                    }
                )
            for tag in finding["tags"]:
                tag_id = f"AxisTag:{uuid5(preview_id, label_key(tag))}"
                nodes.setdefault(tag_id, {"id": tag_id, "type": "AxisTagGroup", "label": tag})
                edges.append(
                    {
                        "id": f"{finding_id}:{tag_id}",
                        "source": finding_id,
                        "target": tag_id,
                        "type": "HAS_TAG",
                    }
                )
    return {"root_id": root, "nodes": list(nodes.values()), "edges": edges}
