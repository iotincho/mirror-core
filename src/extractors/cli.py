"""Opt-in emotion extraction and deferred persistence for a bound workspace."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

from src.config import get_settings
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ExtractorProfile
from src.extractors.emotions import EMOTIONS_PROFILE, EmotionExtractor
from src.extractors.openai_emotions import OpenAIEmotionProvider
from src.extractors.registry import ExtractorRegistry
from src.processing.runtime import get_repository
from src.processing.workflows import worker_runtime
from src.user_management.database import close_database


async def execute(args):
    repository, settings = get_repository(), get_settings()
    async with repository.lock_resource(args.workspace, args.document) as acquired:
        if not acquired:
            raise ValueError("document_processing_active")
        await repository.assert_inactive(args.workspace, args.document)
        async with worker_runtime(args.workspace) as runtime:
            artifacts = LayerArtifacts(runtime.context.filesystem_root / "layers")
            provider = None
            profile = EMOTIONS_PROFILE
            if args.action == "extract":
                if args.profile:
                    profile = ExtractorProfile.model_validate_json(args.profile.read_text())
                if settings.llm_provider != "openai":
                    raise ValueError("emotion_provider_not_supported")
                provider = OpenAIEmotionProvider(settings.openai_api_key, settings.openai_model)
            registry = ExtractorRegistry()
            registry.register("emotions", EmotionExtractor)
            extractor = registry.create(
                "emotions",
                documents=runtime.document_store,
                artifacts=artifacts,
                graph=runtime.graph_store.database_client,
                provider=provider,
                profile=profile,
            )
            try:
                if args.action == "extract":
                    document = await runtime.document_store.get(args.document)
                    output = await extractor.extract(
                        document, dry_run=not args.persist, run_id=args.run or uuid4()
                    )
                else:
                    output = await artifacts.get(args.document, args.run)
                    if output is None:
                        raise ValueError("layer_artifact_missing")
                    await extractor.persist(output)
                # Do not print note content, quotes or credentials; inspect the local artifact.
                print(
                    json.dumps(
                        {
                            "run_id": str(output.run_id),
                            "document_id": str(output.document_id),
                            "extractor": output.extractor,
                            "profile": output.profile.id,
                            "occurrences": len(output.payload["occurrences"]),
                            "persisted": args.action == "persist" or args.persist,
                        },
                        indent=2,
                    )
                )
            finally:
                if provider is not None:
                    await provider.close()


async def run(args):
    try:
        await execute(args)
    finally:
        await close_database()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("extract", "persist"):
        sub = actions.add_parser(action)
        sub.add_argument("--workspace", type=UUID, required=True)
        sub.add_argument("--document", type=UUID, required=True)
        sub.add_argument("--run", type=UUID, required=action == "persist")
        if action == "extract":
            sub.add_argument("--persist", action="store_true")
            sub.add_argument("--profile", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
