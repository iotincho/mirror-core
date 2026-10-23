"""Compatibility CLI; schema implementation and environment composition are separate."""

import sys

from src.bootstrap import graph_schema as canonical

sys.modules[__name__] = canonical

if __name__ == "__main__":
    raise SystemExit(canonical.main())
