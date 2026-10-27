"""Run one explicit extractor command without owning concrete clients or paths."""

from uuid import uuid4


class RunExtraction:
    def __init__(
        self,
        processing,
        runtime_factory,
        artifacts_factory,
        extractor_factory,
        configuration,
        profiles,
    ):
        self.processing, self.runtime_factory = processing, runtime_factory
        self.artifacts_factory, self.extractor_factory = artifacts_factory, extractor_factory
        self.configuration, self.profiles = configuration, profiles

    async def execute(self, command):
        async with self.processing.resource_guard(command.workspace, command.document) as acquired:
            if not acquired:
                raise ValueError("document_processing_active")
            await self.processing.assert_inactive(command.workspace, command.document)
            async with self.runtime_factory(command.workspace) as runtime:
                artifacts = self.artifacts_factory(runtime)
                if (
                    command.action == "extract"
                    and command.force
                    and command.extractor != "document_embeddings"
                ):
                    raise ValueError("extractor_does_not_support_force")
                output = None
                specification = {}
                if command.action == "persist":
                    output = await artifacts.get(command.document, command.run)
                    if output is None:
                        raise ValueError("layer_artifact_missing")
                    specification = {
                        "profile": output.profile.model_dump(),
                        **(
                            {
                                "configuration": output.payload["configuration"],
                                "force": output.payload["force"],
                            }
                            if command.extractor == "document_embeddings"
                            else {}
                        ),
                    }
                else:
                    specification = {
                        "profile": command.profile or self.profiles[command.extractor],
                        "configuration": self.configuration,
                        "force": command.force,
                    }
                async with self.extractor_factory(
                    runtime,
                    command.extractor,
                    specification,
                    extracting=command.action == "extract",
                ) as extractor:
                    if command.action == "extract":
                        document = await runtime.document_store.get(command.document)
                        output = await extractor.extract(
                            document, dry_run=not command.persist, run_id=command.run or uuid4()
                        )
                    else:
                        await extractor.persist(output)
                result = {
                    "run_id": str(output.run_id),
                    "document_id": str(output.document_id),
                    "extractor": output.extractor,
                    "persisted": command.action == "persist" or command.persist,
                }
                if command.extractor == "document_embeddings":
                    result["sections"] = len(output.payload["sections"])
                else:
                    result.update(
                        profile=output.profile.id,
                        emotions=len(output.payload["emotions"]),
                        quotes=sum(len(e["quotes"]) for e in output.payload["emotions"]),
                    )
                return result
