"""Compatibility entrypoint; state and implementation live in bootstrap."""

import sys

from src.bootstrap import processing as canonical

sys.modules[__name__] = canonical
