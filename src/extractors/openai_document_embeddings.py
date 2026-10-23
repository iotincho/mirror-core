"""Compatibility imports; use the canonical layers for new code."""


def OpenAIDocumentEmbeddingProvider(api_key, segmentation_model, client=None, *, max_retries=0):
    from src.bootstrap.extraction import build_document_embeddings_provider

    return build_document_embeddings_provider(
        api_key, segmentation_model, client, max_retries=max_retries
    )
