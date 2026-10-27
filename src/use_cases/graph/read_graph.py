"""Read a workspace projection after checking canonical originals where required."""

from src.core.documents.ports import DocumentStore
from src.core.graph.ports import GraphBackend


class ReadGraph:
    def __init__(self, graph: GraphBackend, documents: DocumentStore | None = None):
        self.graph, self.documents = graph, documents

    async def neighborhood(self, document_id, *, offset=0, limit=10, relation_type=None):
        await self.documents.get(document_id)
        return await self.graph.get_link_neighborhood(
            str(document_id), offset=offset, limit=limit, relation_type=relation_type
        )

    async def extraction_graph(self, document_id, *, layer=None):
        document = await self.documents.get(document_id)
        result = await self.graph.get_extraction_graph(str(document_id), layer=layer)
        label = (
            document.title or document.metadata.get("title") or document.metadata.get("filename")
        )
        label = (
            label
            or next(
                (line.strip() for line in document.content.splitlines() if line.strip()), "Nota"
            )[:80]
        )
        return result.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"label": label}) if node.id == result.root_id else node
                    for node in result.nodes
                ]
            }
        )

    async def emotion_catalog(self, *, offset=0, limit=100):
        return await self.graph.list_emotions(offset=offset, limit=limit)

    async def emotion_exploration(self, emotion, *, depth=1, limit=100):
        return await self.graph.explore_emotion(emotion, depth=depth, limit=limit)

    async def document_emotions(self, document_id, *, limit=100):
        await self.documents.get(document_id)
        return await self.graph.explore_document_emotions(str(document_id), limit=limit)
