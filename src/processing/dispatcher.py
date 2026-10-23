"""Compatibility entrypoint; state and implementation live in bootstrap."""

import sys

from src.bootstrap import dispatcher as canonical

sys.modules[__name__] = canonical

if __name__ == "__main__":
    canonical.asyncio.run(canonical.main())
