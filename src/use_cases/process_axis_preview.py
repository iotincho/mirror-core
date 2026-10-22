"""Generate a profile, then evaluate up to five sources through Extractor.dry_run."""

import asyncio

from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.extractors.personal_axes.contracts import AxisError, AxisSpecification, PreviewRequest
from src.extractors.personal_axes.extractor import PersonalAxisExtractor
from src.extractors.personal_axes.prompt_builder import build_specification
from src.processing.execution import LeaseLost, WorkflowDefinition, WorkflowFailure
from src.processing.failures import failure_for
from src.use_cases.axis_previews import AxisPreviews


class ProcessAxisPreview:
    transitions = frozenset(
        {
            ("prompt_generation", "sample_extraction"),
            ("sample_extraction", "preview_projection"),
            ("preview_projection", "done"),
        }
    )

    def __init__(self, runtime_factory, provider_factory, settings=None):
        self.runtime_factory, self.provider_factory = runtime_factory, provider_factory
        self.settings = settings

    @property
    def definition(self):
        return WorkflowDefinition(self.execute, self.transitions)

    async def execute(self, context):
        try:
            settings = self.settings or get_settings()
            async with self.runtime_factory(context.record.user_id) as runtime:
                previews = AxisPreviews(context.repository, runtime, settings)
                _, value = await previews.live(context.record.resource_id)
                request = PreviewRequest.model_validate(value["request"])
                store = previews.store(context.record.resource_id)
                if context.record.stage == "prompt_generation":
                    saved = await store.read("specification")
                    if saved is None:
                        if request.mode == "repeat":
                            spec = AxisSpecification.model_validate(value["previous_specification"])
                            metadata = None
                        else:
                            previous = (
                                AxisSpecification.model_validate(value["previous_specification"])
                                if value["previous_specification"]
                                else None
                            )
                            provider = self.provider_factory(value["configuration"])
                            spec, metadata = await build_specification(
                                provider, request, value["configuration"], previous
                            )
                        await context.assert_lease()
                        await previews.live(store.id)
                        await store.write(
                            "specification",
                            {
                                "specification": spec.model_dump(mode="json"),
                                "provider": metadata.model_dump(mode="json") if metadata else None,
                            },
                        )
                    await context.advance("sample_extraction")
                if context.record.stage == "sample_extraction":
                    saved = await store.read("specification")
                    spec = AxisSpecification.model_validate(saved["specification"])
                    provider = self.provider_factory(spec.model_dump(exclude={"profile"}))
                    extractor = PersonalAxisExtractor(
                        runtime.document_store, store.layers, spec, provider=provider
                    )
                    semaphore = asyncio.Semaphore(settings.personal_axes_preview_concurrency)

                    async def extract_note(identifier):
                        async with semaphore:
                            try:
                                await context.assert_lease()
                                await previews.live(store.id)
                                sample = {"sources": {identifier: value["sources"][identifier]}}
                                async with previews.source_guard(sample, store.id) as sources:
                                    await extractor.extract(
                                        sources[0], dry_run=True, run_id=store.run_id(identifier)
                                    )
                                await context.assert_lease()
                                return None
                            except (LeaseLost, SQLAlchemyError, asyncio.CancelledError):
                                raise
                            except Exception as error:
                                failure = (
                                    WorkflowFailure(error.code)
                                    if isinstance(error, AxisError)
                                    else failure_for(
                                        error, context.record.stage_attempts, "axis_extraction"
                                    )
                                )
                                if "axis_correction_interrupted" in str(error):
                                    failure = WorkflowFailure("axis_correction_interrupted")
                                await context.assert_lease()
                                await store.write(
                                    f"error-{store.run_id(identifier)}-{context.record.attempts}",
                                    {"code": failure.code, "retryable": failure.retryable},
                                )
                                return failure

                    tasks = [
                        asyncio.create_task(extract_note(identifier))
                        for identifier in value["sources"]
                    ]
                    try:
                        results = await asyncio.gather(*tasks)
                    finally:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    failures = [result for result in results if result is not None]
                    if failures:
                        raise next(
                            (error for error in failures if not error.retryable), failures[0]
                        )
                    await previews.live(store.id)
                    await context.advance("preview_projection")
                if context.record.stage == "preview_projection":
                    await previews.live(store.id)
                    result = await previews.results(store.id)
                    await context.assert_lease()
                    await store.write(
                        "projection", {"documents": result["documents"], "graph": result["graph"]}
                    )
                    await context.advance("done")
                await previews.live(store.id)
                if context.record.stage != "done":
                    raise WorkflowFailure("invalid_workflow_stage")
        except (WorkflowFailure, LeaseLost, SQLAlchemyError):
            raise
        except AxisError as error:
            raise WorkflowFailure(error.code) from None
        except Exception as error:
            # Provider/schema errors can include note text or the generated criterion.
            # Classify them, but do not attach their payload-bearing exception chains.
            raise failure_for(error, context.record.stage_attempts, "axis_generation") from None
