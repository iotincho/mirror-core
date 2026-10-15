"""Preview or enqueue titles for existing documents in one explicit workspace."""

import argparse
import asyncio
import json
from uuid import UUID

from src.config import get_settings
from src.processing.execution import WorkflowFailure
from src.processing.runtime import get_repository
from src.processing.workflows import worker_runtime
from src.use_cases.backfill_document_titles import BackfillDocumentTitles
from src.user_management.database import close_database


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


async def execute(args):
    if args.apply:
        settings = get_settings()
        if (
            settings.llm_provider != "openai"
            or not settings.openai_model
            or not settings.openai_api_key
        ):
            raise ValueError("title_provider_configuration_required")
    async with worker_runtime(args.workspace) as runtime:
        return await BackfillDocumentTitles(get_repository(), runtime).run(
            apply=args.apply,
            limit=args.limit,
            document_ids=args.document,
        )


async def run(args):
    try:
        return await execute(args)
    finally:
        await close_database()


def main():
    parser = build_parser()
    try:
        result = asyncio.run(run(parser.parse_args()))
    except (ValueError, WorkflowFailure) as error:
        parser.exit(2, f"{error}\n")
    # IDs and job states only: no note text, titles, provider credentials or graph secrets.
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
