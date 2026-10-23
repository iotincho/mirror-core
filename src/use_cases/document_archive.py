"""Compatibility constructors and symbols for portable document archives."""

import sys

from src.bootstrap import archives as canonical

sys.modules[__name__] = canonical
