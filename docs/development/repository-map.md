# Mapa del backend

Estado contrastado con el código del repositorio el 2026-10-23. Este mapa indica
dónde buscar; los contratos específicos describen el comportamiento detallado.
Los nombres de archivos son puntos de entrada, no una lista para cargar completa.

Este mapa describe la organización actual tras las etapas 0–3: documentos, audio,
extractores, grafo, respaldos y procesamiento durable migrados; el resto en transición. La estructura
objetivo está en [ARCHITECTURE.md](../../ARCHITECTURE.md) y las correspondencias/etapas en el
[plan de migración hexagonal](hexagonal-migration-plan.md). No inferir que una
dependencia actual cumple las fronteras objetivo sólo por aparecer en este mapa.

El inventario de imports, composición y consumidores se genera con
`python3 scripts/check_architecture.py --inventory /tmp/mirror-architecture-inventory.json`.
La [guía del chequeo](architecture-checks.md) describe cobertura, excepciones y
referencias de Docker, Alembic, empaquetado, scripts y pruebas a conservar al migrar.

| Tarea | Entrada y responsables | Pruebas / contrato |
| --- | --- | --- |
| Piloto documentos / títulos | `src/core/domain/`, `src/core/documents/`, `src/core/extractors/`; `src/use_cases/documents/`, `src/use_cases/extraction/`; `src/bootstrap/documents.py` | `tests/test_document_pilot.py`, `tests/test_document_title_extractor.py`, `tests/test_lazy_document_titles.py`; [títulos](../document-title-extractor.md) |
| Persistencia del piloto | `src/adapters/storage/filesystem/`, `src/adapters/storage/arcadedb/documents.py`, `document_titles.py` | `tests/test_processing_artifacts.py`, integraciones de ingestión/títulos/capas |
| Proveedor de títulos | `src/adapters/providers/openai/document_title.py`, `client.py`; configuración en bootstrap | `tests/test_title_provider_resources.py`, `tests/test_document_title_extractor.py` |
| Aplicación durable / backfill | `src/use_cases/processing/`, `src/use_cases/documents/backfill_document_titles.py`; contratos en `src/core/processing/` | `tests/test_processing_application.py`, integraciones de procesamiento/reprocess/títulos |
| SQL durable / feed de eventos | `src/adapters/storage/postgres/models.py`, `repository.py`, `transactions.py`, `submissions.py`, `submission_port.py`, `state.py`, `events.py` | `tests/integration/test_processing_postgres.py`, `test_processing_events.py`; [runtime](../processing-runtime.md) |
| Composición y transporte durable | `src/bootstrap/processing.py`, `acceptance.py`, `processing_configuration.py`, `workflows.py`, `dispatcher.py`, `worker.py`, `messaging.py`; adaptadores en `src/adapters/access/workers/`, `src/adapters/messaging/rabbitmq/` | `tests/test_processing_transport.py`; workers reales opt-in |
| HTTP público / composición | `src/main.py`, `src/api/router.py`, `src/api/routes/`, `src/dependencies.py` | `tests/test_openapi_docs.py`, `tests/test_documents_route.py` |
| HTTP de ingestión / aceptación idempotente | `src/api/routes/processing.py`; llama constructores de compatibilidad que delegan a bootstrap y aplicación durable | `tests/integration/test_deferred_ingestion.py`; [ingestión](../deferred-ingestion.md) |
| Entrypoints durables compatibles | `src/processing/runtime.py`, `workflows.py`, `execution.py`, `repository.py`, `dispatcher.py`, `tasks.py` delegan a las filas canónicas anteriores | `tests/test_processing_transport.py`, `tests/integration/test_processing_postgres.py`; [runtime](../processing-runtime.md) |
| Procesar documentos / audio / capas | `src/use_cases/processing/`, `src/use_cases/audio/`; composición en `src/bootstrap/audio.py`, `workflows.py` | `tests/integration/test_extractor_jobs.py`; [jobs](../extractor-jobs.md) |
| Emociones / embeddings / proveedores | `src/core/extractors/`, `src/use_cases/extraction/`, `src/adapters/storage/arcadedb/{emotions,document_embeddings}.py`, `src/adapters/providers/openai/`; composición en `src/bootstrap/extraction.py`, registro en `extractor_registry.py` | `tests/test_emotion_extractor.py`, `tests/test_document_embedding_extractor.py`, `tests/test_document_title_extractor.py` |
| Laboratorio / ejes | `src/extractors/personal_axes/`, `src/use_cases/axis_previews.py`, `process_axis_preview.py`, `process_axis_history.py` | `tests/test_personal_axis_extractor.py`, `tests/test_laboratory_access.py`, `tests/integration/test_axis_previews.py`; [API](../personal-axes-api.md) |
| Lecturas / proyecciones de grafo | `src/core/graph/`, `src/use_cases/graph/read_graph.py`, `src/adapters/storage/arcadedb/{graph,emotion_projection,queries}.py`; acceso en `src/api/routes/graph.py` | `tests/test_graph_navigation.py`, `tests/test_emotion_projection.py`; [grafo](../../src/graph/README.md) |
| Audio / transcripción | `src/core/audio/`, `src/use_cases/audio/`, `src/adapters/storage/filesystem/{audio_notes,audio_transcoding}.py`, `src/adapters/providers/openai/transcription.py` | `tests/test_openai_transcription_provider.py`, `tests/test_processing_artifacts.py`; [recuperación](../audio-transcription-recovery.md) |
| Respaldos | `src/core/documents/archive.py`, `src/use_cases/documents/archive.py`, `delete_document.py`, `src/bootstrap/archives.py`; HTTP en `src/api/routes/document_archive.py` y CLI en `scripts/export_document_archives.py` | `tests/test_document_archive.py`; [respaldos](../document-archives.md) |
| Cuenta / sesión / recuperación | `src/auth/session.py`, `src/user_management/`, `src/user_management/recovery/` | `tests/test_signup_flow.py`, `tests/test_password_recovery.py`, `tests/test_google_oauth.py`; [registro](../signup.md) |
| Workspace / aislamiento | `src/workspaces/context.py`, `dependencies.py`, `provisioning.py`, `secrets.py` | `tests/test_workspace_dependencies.py`, `tests/test_workspaces.py` |
| Invitaciones / notificaciones | `src/exteriorization/`, `src/notifications/`, `src/use_cases/schedule_invitations.py`, `generate_invitation.py`, `send_invitation.py` | `tests/test_exteriorization.py`, `tests/test_notifications.py`; [centro](../notification-center.md) |
| Administración | `src/admin_main.py`, `src/administration/` | `tests/test_administration_api.py`, `tests/integration/test_administration.py`; [admin](../admin-lan.md) |
| Configuración / observabilidad | `src/config.py`, `.env.example`, `src/observability.py`, `src/logging.py`, `src/api/request_logging.py` | `tests/test_config.py`, `tests/test_observability.py`, `tests/test_request_logging.py`; [Sentry](../sentry.md) |
| Esquemas / migraciones | `migrations/versions/`, `src/adapters/storage/arcadedb/schema.py`, `src/bootstrap/graph_schema.py`, `src/maintenance/`; comando anterior compatible | `tests/test_arcadedb_schema.py`, `tests/integration/test_data_migrations.py` |
| Entorno / publicación | `Dockerfile`, `Dockerfile.prod`, `docker-compose.yml`, `deploy.sh`, `.github/workflows/publish-production-image.yml` | `tests/test_local_deploy.py`; [imágenes](../production-image-publishing.md) |

## Fronteras de dependencia

`src/domain/`, los módulos migrados de `src/extractors/`, `src/graph/` y los
stores/proveedores anteriores reexportan implementaciones canónicas o adaptan sus
constructores mediante bootstrap. Para cambiar comportamiento empezar por core,
los casos agrupados y sus adaptadores. Los puentes conservan una sola implementación.

Los casos migrados reciben puertos y configuración explícita. SQLAlchemy, HTTPX,
OpenAI, tiktoken, rutas locales y ffmpeg quedan fuera de core/aplicación. La
preparación del audio devuelve bytes mediante un puerto; el adaptador controla
originales/temporales. Los respaldos y borrado usan puertos durables sin sesiones SQL.
La clasificación de fallos separa hechos técnicos del adaptador y política pura.

Bootstrap compone por capacidad: `documents.py`, `extraction.py`, `audio.py`,
`graph.py`, `archives.py` y `workflows.py`; evita un contenedor global de dependencias.
`src/dependencies.py`, `src/workspaces/dependencies.py`, las rutas públicas y otras
familias mantienen conexiones heredadas pendientes de etapas 4–6. Ejes conserva
sus internals y puentes explícitos para ejecución/orden de escritura/privacidad.

## Material fuera del recorrido normal

`prototypes/` conserva experiencias visuales. Los [pendientes](../pending.md) se
consultan sólo al planificar tareas de ese alcance. `data/` puede contener material
personal. `build/`, `*.egg-info`, caches y entornos son generados. No usarlos para
deducir el contrato actual.
