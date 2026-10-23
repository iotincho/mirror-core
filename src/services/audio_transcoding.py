"""Compatibility module; conversion and temporary-file ownership live in filesystem."""

import sys

from src.adapters.storage.filesystem import audio_transcoding as canonical

sys.modules[__name__] = canonical
