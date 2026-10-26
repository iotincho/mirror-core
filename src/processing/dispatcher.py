"""External mirror-deploy entrypoint; remove after its commands migrate to bootstrap."""

import asyncio

from src.bootstrap.dispatcher import main as main

if __name__ == "__main__":
    asyncio.run(main())
