"""Compatibility constructor; workspace artifacts and extension hooks are composed externally."""

def ProcessExtractor(runtime_factory, extractor_factory):
    from src.bootstrap.processing import build_extractor_processor

    return build_extractor_processor(runtime_factory, extractor_factory)
