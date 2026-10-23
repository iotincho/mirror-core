"""Compatibility constructor; composition lives in bootstrap."""


def ProcessDocumentExtractors(runtime_factory, *, keyed=False):
    from src.bootstrap.processing import build_document_coordinator

    return build_document_coordinator(runtime_factory, keyed=keyed)
