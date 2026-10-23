"""Compatibility constructor for resource-guarded deletion."""


def DeleteDocument(documents, graph, processing=None, user_id=None, layer_artifacts=None):
    from src.bootstrap.archives import build_delete_document

    return build_delete_document(documents, graph, processing, user_id, layer_artifacts)
