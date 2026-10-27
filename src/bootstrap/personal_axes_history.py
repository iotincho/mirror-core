"""Compose historical analysis independently of previews or SQL context bridges."""

from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.adapters.storage.postgres.personal_axes.definitions import PostgresAxisDefinitions
from src.adapters.storage.postgres.personal_axes.history import PostgresHistory
from src.adapters.storage.postgres.personal_axes.write_contexts import PostgresAxisWriteContexts
from src.bootstrap.failures import failure_for
from src.bootstrap.personal_axes_reads import build_axis_exploration
from src.bootstrap.settings import get_settings
from src.use_cases.personal_axes.history import AxisHistory
from src.use_cases.personal_axes.process_history import ProcessAxisHistory


def build_axis_history(repository, runtime):
    return AxisHistory(
        runtime.context.user_id,
        runtime.document_store,
        PostgresAxisDefinitions(repository.sessions),
        build_axis_exploration(repository.sessions, runtime),
        PostgresHistory(repository, enabled=get_settings().personal_axes_enabled),
    )


def build_history_workflow(runtime_factory, extractor_factory, *, repository=None):
    from src.bootstrap.processing import get_repository, protected_runtime

    repo = repository or get_repository()
    return ProcessAxisHistory(
        protected_runtime(runtime_factory),
        extractor_factory,
        history_factory=lambda runtime: build_axis_history(repo, runtime),
        artifacts_factory=lambda runtime: LayerArtifacts(
            runtime.context.filesystem_root / "layers"
        ),
        execution=PostgresHistory(repo, enabled=get_settings().personal_axes_enabled),
        write_contexts=PostgresAxisWriteContexts(repo.sessions),
        failure_for=failure_for,
    )
