from src.core.documents.ports import DocumentStore
from src.core.domain.documents import Document


class ListDocuments:
    def __init__(self, documents: DocumentStore, ensure_titles=None):
        self._documents = documents
        self._ensure_titles = ensure_titles

    async def execute(self) -> list[Document]:
        documents = await self._documents.list()
        if self._ensure_titles is not None:
            await self._ensure_titles.execute(documents)
        return documents
