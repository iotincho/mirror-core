"""Compatibility task module; registration and dependencies live in bootstrap."""

import sys

from src.bootstrap import worker as canonical

sys.modules[__name__] = canonical
