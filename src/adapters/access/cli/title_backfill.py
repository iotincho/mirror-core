"""Preview or enqueue titles in one explicit workspace."""

import argparse
import asyncio
import json
from uuid import UUID

from src.core.processing.errors import WorkflowFailure


def positive_limit(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--document", type=UUID, action="append", help="Optional document IDs")
    parser.add_argument("--limit", type=positive_limit, default=100)
    parser.add_argument(
        "--apply", action="store_true", help="Enqueue the selected jobs; default is read-only"
    )
    return parser


async def run(args, execute, close_database):
    try:
        return await execute(args)
    finally:
        await close_database()


def main(execute, close_database):
    parser = build_parser()
    try:
        result = asyncio.run(run(parser.parse_args(), execute, close_database))
    except (ValueError, WorkflowFailure) as error:
        parser.exit(2, f"{error}\n")
    # IDs and job states only: no note text, titles, provider credentials or graph secrets.
    print(json.dumps(result, ensure_ascii=False, indent=2))
