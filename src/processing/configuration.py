"""Select the durable document workflow from its accepted configuration."""


def document_workflow_version(config: dict) -> int:
    # Historic jobs without layers must not silently start invoking providers.
    return 3 if config.get("extractors") else 2
