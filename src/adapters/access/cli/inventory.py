"""Reconcile original metadata once or at an explicit repeat interval."""

import argparse
import asyncio
import json


async def run(interval, create_sync, close_database):
    try:
        sync = create_sync()
        while True:
            result = await sync.run()
            print(json.dumps(result), flush=True)
            if not interval:
                return 1 if result["failed"] else 0
            await asyncio.sleep(interval)
    finally:
        await close_database()


def main(create_sync, close_database):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="repeat interval in seconds (>=5)")
    args = parser.parse_args()
    if args.interval and args.interval < 5:
        parser.error("--interval must be at least 5 seconds")
    try:
        raise SystemExit(asyncio.run(run(args.interval, create_sync, close_database)))
    except KeyboardInterrupt:
        pass
