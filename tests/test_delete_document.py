from uuid import UUID, uuid4

from src.services.graph_store import GraphStore
from src.use_cases.delete_document import DeleteDocument


class RecordingDocumentStore:
    def __init__(self) -> None:
        self.loaded: list[UUID] = []
        self.deleted: list[UUID] = []

    def get(self, document_id: UUID) -> object:
        self.loaded.append(document_id)
        return object()

    def delete(self, document_id: UUID) -> None:
        self.deleted.append(document_id)


class RecordingExtractionStore:
    def __init__(self) -> None:
        self.deleted: list[UUID] = []

    def delete_for_document(self, document_id: UUID) -> None:
        self.deleted.append(document_id)


class RecordingGraphStore(GraphStore):
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def persist(self, document: object, extraction: object) -> None:
        raise AssertionError("persist should not be called while deleting a document")

    def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


def test_delete_document_depends_on_graph_contract() -> None:
    document_id = uuid4()
    documents = RecordingDocumentStore()
    extractions = RecordingExtractionStore()
    graph = RecordingGraphStore()

    DeleteDocument(documents, extractions, graph).execute(document_id)

    assert documents.loaded == [document_id]
    assert graph.deleted == [str(document_id)]
    assert extractions.deleted == [document_id]
    assert documents.deleted == [document_id]
