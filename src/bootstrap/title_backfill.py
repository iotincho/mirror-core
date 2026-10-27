"""Preview or enqueue titles for existing documents in one explicit workspace."""


from src.adapters.access.cli.title_backfill import build_parser as build_parser
from src.bootstrap.database import close_database
from src.bootstrap.processing import build_title_backfill as BackfillDocumentTitles
from src.bootstrap.processing import get_repository
from src.bootstrap.settings import get_settings
from src.bootstrap.workflows import worker_runtime


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


def main():
    from src.adapters.access.cli.title_backfill import main as run
    run(execute, close_database)


if __name__ == "__main__":
    main()
