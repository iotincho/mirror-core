"""Purpose-owned extraction and deferred persistence for one explicit workspace."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from src.core.extractors.contracts import ExtractorProfile


async def run(args, execute, close):
    try:
        args.profile = (ExtractorProfile.model_validate_json(args.profile.read_text()).model_dump()
                        if getattr(args, "profile", None) else None)
        args.force = getattr(args, "force", False)
        args.persist = getattr(args, "persist", False)
        print(json.dumps(await execute(args), indent=2))
    finally:
        await close()


def main(execute, close):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("extract", "persist"):
        sub = actions.add_parser(action)
        sub.add_argument(
            "--extractor", choices=["emotions", "document_embeddings"], default="emotions"
        )
        sub.add_argument("--workspace", type=UUID, required=True)
        sub.add_argument("--document", type=UUID, required=True)
        sub.add_argument("--run", type=UUID, required=action == "persist")
        if action == "extract":
            sub.add_argument("--force", action="store_true")
            sub.add_argument("--persist", action="store_true")
            sub.add_argument("--profile", type=Path)
    asyncio.run(run(parser.parse_args(), execute, close))
