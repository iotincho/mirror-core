"""Inventory by default; applying cleanup requires an explicit backup and stopped writers."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID


async def run(args, create, close):
    try:
        result = await create().execute(
            args.workspace, args.instance, apply=args.apply,
            services_stopped=args.services_stopped, backup=args.backup,
        )
        print(json.dumps(result, indent=2))
    finally:
        await close()


def main(create, close):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--backup", type=Path)
    asyncio.run(run(parser.parse_args(), create, close))
