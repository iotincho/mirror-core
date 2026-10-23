"""Compatibility constructors and configuration hooks; canonical cases are grouped by area."""

import sys

from src.bootstrap import acceptance as canonical

sys.modules[__name__] = canonical
