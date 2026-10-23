# Mapa del backend

Estado contrastado con el código del repositorio el 2026-10-23. Este mapa indica
dónde buscar; los contratos específicos describen el comportamiento detallado.
Los nombres de archivos son puntos de entrada, no una lista para cargar completa.

| Tarea | Entrada y responsables | Pruebas / contrato |
| --- | --- | --- |
| HTTP público / composición | `src/main.py`, `src/api/router.py`, `src/api/routes/`, `src/dependencies.py` | `tests/test_openapi_docs.py`, `tests/test_documents_route.py` |
| Ingestión / aceptación idempotente | `src/use_cases/submit_processing.py`, `src/processing/submissions.py`, `src/api/routes/processing.py` | `tests/integration/test_deferred_ingestion.py`; [ingestión](../deferred-ingestion.md) |
| Orquestación durable | `src/processing/runtime.py`, `workflows.py`, `execution.py`, `repository.py`, `dispatcher.py`, `tasks.py` | `tests/test_processing_transport.py`, `tests/integration/test_processing_postgres.py`; [runtime](../processing-runtime.md) |
| Procesar documentos / audio / capas | `src/use_cases/process_audio_note.py`, `process_document_extractors.py`, `process_extractor.py`, `src/processing/configuration.py` | `tests/integration/test_extractor_jobs.py`; [jobs](../extractor-jobs.md) |
| Extractores / proveedores | `src/extractors/base.py`, `contracts.py`, `artifacts.py`, `registry.py`, módulos de cada capa | `tests/test_emotion_extractor.py`, `tests/test_document_embedding_extractor.py`, `tests/test_document_title_extractor.py` |
| Laboratorio / ejes | `src/extractors/personal_axes/`, `src/use_cases/axis_previews.py`, `process_axis_preview.py`, `process_axis_history.py` | `tests/test_personal_axis_extractor.py`, `tests/test_laboratory_access.py`, `tests/integration/test_axis_previews.py`; [API](../personal-axes-api.md) |
| Lecturas / proyecciones de grafo | `src/graph/contracts.py`, `src/graph/emotion_exploration.py`, `src/graph/arcadedb/`, `src/query/`, `src/api/routes/graph.py` | `tests/test_graph_navigation.py`, `tests/test_emotion_projection.py`; [grafo](../../src/graph/README.md) |
| Archivos / transcripción | `src/services/document_store.py`, `audio_note_store.py`, `durable_files.py`, `audio_transcoding.py`, `openai_transcription_provider.py` | `tests/test_openai_transcription_provider.py`, `tests/test_processing_artifacts.py`; [recuperación](../audio-transcription-recovery.md) |
| Respaldos | `src/use_cases/document_archive.py`, `src/api/routes/document_archive.py`, `scripts/export_document_archives.py` | `tests/test_document_archive.py`; [respaldos](../document-archives.md) |
| Cuenta / sesión / recuperación | `src/auth/session.py`, `src/user_management/`, `src/user_management/recovery/` | `tests/test_signup_flow.py`, `tests/test_password_recovery.py`, `tests/test_google_oauth.py`; [registro](../signup.md) |
| Workspace / aislamiento | `src/workspaces/context.py`, `dependencies.py`, `provisioning.py`, `secrets.py` | `tests/test_workspace_dependencies.py`, `tests/test_workspaces.py` |
| Invitaciones / notificaciones | `src/exteriorization/`, `src/notifications/`, `src/use_cases/schedule_invitations.py`, `generate_invitation.py`, `send_invitation.py` | `tests/test_exteriorization.py`, `tests/test_notifications.py`; [centro](../notification-center.md) |
| Administración | `src/admin_main.py`, `src/administration/` | `tests/test_administration_api.py`, `tests/integration/test_administration.py`; [admin](../admin-lan.md) |
| Configuración / observabilidad | `src/config.py`, `.env.example`, `src/observability.py`, `src/logging.py`, `src/api/request_logging.py` | `tests/test_config.py`, `tests/test_observability.py`, `tests/test_request_logging.py`; [Sentry](../sentry.md) |
| Esquemas / migraciones | `migrations/versions/`, `src/graph/arcadedb/schema.py`, `src/maintenance/` | `tests/test_arcadedb_schema.py`, `tests/integration/test_data_migrations.py` |
| Entorno / publicación | `Dockerfile`, `Dockerfile.prod`, `docker-compose.yml`, `deploy.sh`, `.github/workflows/publish-production-image.yml` | `tests/test_local_deploy.py`; [imágenes](../production-image-publishing.md) |

## Fronteras de dependencia

`src/domain/` contiene originales y modelos sin infraestructura. Los casos de uso
reciben puertos/colaboradores; `src/services/graph_store.py`, los contratos de
extractores y los contratos de grafo definen esas fronteras. Los adaptadores
concretos se ensamblan en `src/dependencies.py`, `src/workspaces/dependencies.py`,
`src/processing/workflows.py` y dependencias de cada familia.

No centralizar toda la composición en un único archivo: `workflows.py` compone
ejecución de workers y el runtime del workspace compone el acceso por usuario.
`src/graph/arcadedb/` contiene el adaptador base; las capas tienen persistencia
propia en `src/extractors/`.

## Material fuera del recorrido normal

`prototypes/` conserva experiencias visuales. Los [pendientes](../pending.md) se
consultan sólo al planificar tareas de ese alcance. `data/` puede contener material
personal. `build/`, `*.egg-info`, caches y entornos son generados. No usarlos para
deducir el contrato actual.
