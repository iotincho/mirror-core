"""Compatibility constructor for the historical document workflow."""


def ProcessDocument(runtime_factory):
    from src.bootstrap.processing import build_source_processor

    return build_source_processor(runtime_factory)
