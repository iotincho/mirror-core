from uuid import uuid4

import pytest

from src.adapters.access.api.public.personal_axes.schemas import PreviewGraph
from src.extractors.personal_axes.preview_projection import project_preview


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_preview_has_one_relation_per_quote_and_no_evidence_on_finding_nodes():
    preview_id, document_id, finding_id = uuid4(), str(uuid4()), f"AxisFinding:{uuid4()}"
    content = "Más ideas. Una propuesta."
    evidence = [
        {
            "quote": quote,
            "start_char": content.index(quote),
            "end_char": content.index(quote) + len(quote),
        }
        for quote in ["Más ideas.", "Una propuesta."]
    ]
    documents = [
        {
            "document_id": document_id,
            "title": "Nota",
            "findings": [
                {
                    "id": finding_id,
                    "title": "Un proyecto",
                    "content": "Desarrollo de la idea",
                    "tags": ["creación"],
                    "evidence": evidence,
                }
            ],
        }
    ]
    raw = project_preview(preview_id, documents)
    # Exercise the API schema too: evidence must survive response serialization.
    graph = PreviewGraph.model_validate(raw).model_dump(mode="json")
    finding = next(node for node in graph["nodes"] if node["type"] == "AxisFinding")
    assert not {"evidence", "evidence_json", "quote", "start_char", "end_char"} & finding.keys()
    edges = [edge for edge in graph["edges"] if edge["type"] == "HAS_FINDING"]
    assert len(edges) == len({edge["id"] for edge in edges}) == 2
    assert {edge["source"] for edge in edges} == {f"Document:{document_id}"}
    assert {edge["target"] for edge in edges} == {finding_id}
    assert [
        {key: edge[key] for key in ("quote", "start_char", "end_char")} for edge in edges
    ] == evidence
    assert all(edge["quote"] is None for edge in graph["edges"] if edge["type"] != "HAS_FINDING")
    assert project_preview(preview_id, documents) == raw
    another = project_preview(uuid4(), documents)
    assert not {edge["id"] for edge in edges} & {
        edge["id"] for edge in another["edges"] if edge["type"] == "HAS_FINDING"
    }


@pytest.mark.anyio
async def test_neighbor_page_preserves_full_finding_context_and_cursor_scope():
    from types import SimpleNamespace

    from src.adapters.access.api.public.personal_axes.schemas import PreviewNeighbors
    from src.extractors.personal_axes.contracts import AxisError
    from src.extractors.personal_axes.exploration import preview_neighbors

    preview_id, owner = uuid4(), uuid4()
    documents = [
        {
            "document_id": str(uuid4()),
            "title": f"Nota {i}",
            "source_hash": "a" * 64,
            "findings": [
                {
                    "id": f"AxisFinding:{uuid4()}",
                    "title": "Encontrar",
                    "content": "Contenido",
                    "tags": ["Compartida", f"Propia {i}"],
                    "evidence": [
                        {"quote": quote, "start_char": start, "end_char": start + len(quote)}
                        for start, quote in [(0, "Uno"), (4, "Dos")]
                    ],
                }
            ],
        }
        for i in range(3)
    ]
    graph = project_preview(preview_id, documents)

    async def results(id):
        assert id == preview_id
        return {"graph": graph, "preview": {"revision_hash": "b" * 64}}

    service = SimpleNamespace(results=results, owner=owner)
    tag = next(n for n in graph["nodes"] if n["label"] == "Compartida")
    first = await preview_neighbors(service, preview_id, tag["id"], limit=1)
    serialized = PreviewNeighbors.model_validate(first).model_dump(mode="json")
    finding = next(n for n in serialized["nodes"] if n["type"] == "AxisFinding")
    assert finding["finding_id"] and finding["tags_complete"]
    assert finding["source_hash"] == "a" * 64
    assert len([e for e in serialized["edges"] if e["type"] == "HAS_FINDING"]) == 2
    assert len([e for e in serialized["edges"] if e["type"] == "HAS_TAG"]) == 2
    assert len([n for n in serialized["nodes"] if n["type"] == "AxisFinding"]) == 1
    second = await preview_neighbors(service, preview_id, tag["id"], first["next_cursor"], limit=1)
    assert finding["id"] not in {n["id"] for n in second["nodes"]}
    with pytest.raises(AxisError):
        await preview_neighbors(
            service, preview_id, graph["root_id"], first["next_cursor"], limit=1
        )
