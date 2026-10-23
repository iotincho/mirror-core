"""Compatibility module; projection queries and pagination live in the graph adapter."""

import sys

from src.adapters.storage.arcadedb import emotion_projection as canonical

sys.modules[__name__] = canonical
