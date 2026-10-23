"""Compatibility constructor for the historical document workflow."""


def ProcessDocumentLayers(runtime_factory, extractor_factory):
    from src.bootstrap.processing import build_legacy_layers_processor

    return build_legacy_layers_processor(runtime_factory, extractor_factory)
