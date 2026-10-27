"""Inventory or apply registered migrations only on explicit invocation."""

import argparse
import asyncio
import json
from pathlib import Path


async def run_cli(args, create, close_database):
    try:
        migration = create(args.backup_root)
        print(
            json.dumps(
                await migration.run(apply=args.apply, services_stopped=args.services_stopped),
                indent=2,
            )
        )
    finally:
        await close_database()


def main(create, close_database):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    asyncio.run(run_cli(parser.parse_args(), create, close_database))
