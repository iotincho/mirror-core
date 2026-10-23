"""Select the durable document workflow from its accepted configuration."""


def document_workflow_version(config: dict) -> int:
    # Historic jobs without layers must not silently start invoking providers.
    if not config.get("extractors"):
        return 2
    return config.get("document_workflow_version", 3)
