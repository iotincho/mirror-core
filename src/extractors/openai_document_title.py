"""Compatibility constructor; environment defaults are supplied by bootstrap."""

from src.adapters.providers.openai.document_title import (
    DocumentTitleProviderError as DocumentTitleProviderError,
)
from src.bootstrap.documents import build_title_provider

OpenAIDocumentTitleProvider = build_title_provider
