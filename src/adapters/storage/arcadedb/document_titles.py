"""Title-only projection into the workspace's existing Document vertex."""

from src.core.documents.ports import GraphPersistenceError
from src.core.extractors.contracts import content_hash


class ArcadeDBDocumentTitleStore:
    def __init__(self, client):
        self.client = client

    @staticmethod
    def rows(response):
        rows = response.get("result")
        if response.get("truncated") or not isinstance(rows, list):
            raise ValueError("title_graph_result_incomplete")
        return rows

    async def update_title(self, document):
        params = {"document_id": str(document.id), "title": document.title}
        try:
            async with self.client.transaction() as tx:
                sources = self.rows(
                    await tx.query("SELECT content FROM Document WHERE id=:document_id", params)
                )
                if len(sources) != 1 or sources[0].get("content") is None:
                    raise ValueError("title_source_missing_in_graph")
                if content_hash(sources[0]["content"]) != content_hash(document.content):
                    raise ValueError("title_graph_source_changed")
                # MATCH never recreates a deleted original; patch only the display attribute.
                await tx.command(
                    "MATCH (d:Document {id:$document_id}) SET d.title=$title",
                    params,
                    language="cypher",
                )
                actual = self.rows(
                    await tx.query("SELECT title FROM Document WHERE id=:document_id", params)
                )
                if actual != [{"title": document.title}]:
                    raise ValueError("title_graph_verification_failed")
        except ValueError:
            raise
        except Exception as error:
            raise GraphPersistenceError("Document title projection failed") from error
