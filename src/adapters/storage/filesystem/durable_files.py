"""Flush published originals and metadata before acknowledging durable storage."""

import os
from pathlib import Path


def sync_published(path: Path):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
