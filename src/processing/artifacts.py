"""Compatibility imports; use the canonical adapter for new code."""

from src.adapters.storage.filesystem.processing_artifacts import (
    ProcessingArtifacts as ProcessingArtifacts,
)
from src.core.extractors.artifacts import ArtifactCorrupted as ArtifactCorrupted
