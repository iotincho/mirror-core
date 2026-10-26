# Mapa del backend

Estado contrastado con código al 2026-10-26. La migración del alcance acordado
está completada y validada con PostgreSQL, ArcadeDB, RabbitMQ e imagen de producción.
La [arquitectura](../../ARCHITECTURE.md) define responsabilidades y criterios de crecimiento.
El núcleo y extractor de ejes completaron la primera etapa de su
[migración](personal-axes-migration-plan.md); gestión, previews e histórico siguen
pendientes. Abajo se identifican sus puentes y los entrypoints externos necesarios.
Leer la fila del área afectada y sus pruebas, no todos los módulos.

| Tarea | Entrada y responsables | Pruebas / contrato |
| --- | --- | --- |
| HTTP público | `src/adapters/access/api/public/`; composición en `src/bootstrap/{public_api,public_router,public_dependencies}.py` | `tests/test_openapi_docs.py`, `test_documents_route.py`, `test_document_archive.py` |
| Ingestión y snapshots | `src/use_cases/processing/{submit_processing,public,request_processing}.py`; rutas `public/routes/processing.py`; composición `bootstrap/{acceptance,processing}.py` | `tests/test_processing_application.py`, `test_consolidated_boundaries.py`; [ingestión](../deferred-ingestion.md) |
| SSE / autorización renovable | `src/use_cases/auth/authorize_stream.py`, `src/core/auth/session.py`; `src/adapters/storage/postgres/{stream_sessions,events}.py`; acceso `public/routes/events.py` | `tests/test_event_stream_logging.py`, `tests/integration/test_processing_events.py`; [SSE](../processing-pwa-events.md) |
| Documentos / títulos | `src/core/{domain,documents,extractors}/`; `src/use_cases/{documents,extraction}/`; `src/bootstrap/documents.py` | `tests/test_document_pilot.py`, `test_lazy_document_titles.py`; [títulos](../document-title-extractor.md) |
| SQL durable / recibos / eventos | `src/adapters/storage/postgres/{models,repository,transactions,submissions,submission_port,state,reads,events}.py`; puertos en `src/core/processing/` | `tests/integration/test_processing_postgres.py`; [runtime](../processing-runtime.md) |
| Workers / dispatcher / registros | `src/bootstrap/{worker,dispatcher,messaging,processing,workflows,workflow_registry,extractor_registry}.py`; acceso Taskiq en `src/adapters/access/workers/`, RabbitMQ en `adapters/messaging/rabbitmq/` | `tests/test_processing_transport.py`; integraciones de jobs/transporte |
| Audio | `src/core/audio/`, `src/use_cases/audio/`; archivos en `adapters/storage/filesystem/`, transcripción en `adapters/providers/openai/`; `src/bootstrap/audio.py` | `tests/test_openai_transcription_provider.py`; [recuperación](../audio-transcription-recovery.md) |
| Emociones / embeddings | `src/core/extractors/`, `src/use_cases/extraction/`; proyecciones en `adapters/storage/arcadedb/`, proveedores en `adapters/providers/openai/`; `src/bootstrap/extraction.py` | `tests/test_emotion_extractor.py`, `test_document_embedding_extractor.py`; [emociones](../emotion-extractor.md), [embeddings](../document-embeddings.md) |
| Grafo | `src/core/graph/`, `src/use_cases/graph/read_graph.py`; `src/adapters/storage/arcadedb/{graph,emotion_projection,queries}.py` | `tests/test_graph_navigation.py`, `test_emotion_projection.py`; [contrato](../graph-navigation.md) |
| Respaldos / borrado | `src/use_cases/documents/{archive,delete_document,resolve_originals}.py`; `src/bootstrap/archives.py`; `adapters/storage/filesystem/owner_originals.py` | `tests/test_document_archive.py`, `test_consolidated_boundaries.py`; [respaldos](../document-archives.md) |
| Identidad / recuperación | `src/core/auth/`, `src/use_cases/auth/`; acceso `adapters/access/api/public/auth/`; SQL en `adapters/storage/postgres/`, cifrado y email en `adapters/providers/`; `src/bootstrap/{auth,recovery,oauth,database}.py` | `tests/test_identity_application.py`, `test_signup_flow.py`, `test_password_recovery.py`; [registro](../signup.md), [recuperación](../password-recovery.md) |
| Workspaces / aislamiento | `src/core/workspaces/`, `src/use_cases/workspaces/`; PostgreSQL y provisión ArcadeDB en storage; `src/bootstrap/workspaces.py` | `tests/test_workspaces.py`, `tests/integration/test_workspace_provisioning.py` |
| Invitaciones / bandeja | `src/core/{exteriorization,notifications}/`, `src/use_cases/{exteriorization,notifications}/`; SQL y Web Push en adaptadores; `src/bootstrap/{invitations,notifications,public_channels}.py` | `tests/test_channels_application.py`, `test_exteriorization.py`, `test_notifications.py`; [centro](../notification-center.md) |
| Administración | `src/core/administration/`, `src/use_cases/administration/`, `src/adapters/access/api/administration/`; SQL/filesystem en storage; `src/bootstrap/{administration,inventory_sync}.py` | `tests/test_administration_api.py`; [admin](../admin-lan.md) |
| Mantenimiento / migraciones | `src/core/maintenance/`, `src/use_cases/maintenance/`; CLI en `adapters/access/cli/`, implementaciones `adapters/storage/{postgres,arcadedb,filesystem}/*migration*.py`; `src/bootstrap/{data_migrations,cleanup_extractions,graph_schema}.py`; Alembic en `migrations/` | `tests/test_consolidated_boundaries.py`, integraciones de datos/cleanup; [operación](../data-migrations.md) |
| Comandos de extracción / backfill | `src/adapters/access/cli/{extraction,title_backfill}.py`, `src/use_cases/extraction/run_command.py`; `src/bootstrap/{extraction_cli,title_backfill}.py` | `tests/test_title_backfill_cli.py`; contratos de cada extractor |
| Settings / diagnóstico | `src/bootstrap/{settings,logging,observability}.py`; middleware HTTP en acceso; Sentry en `src/adapters/providers/telemetry/`; `.env.example` | `tests/test_config.py`, `test_request_logging.py`, `test_observability.py`; [Sentry](../sentry.md) |
| Extractor de ejes | `src/core/extractors/personal_axes/`, `src/use_cases/extraction/personal_axis.py`, `src/use_cases/personal_axes/build_specification.py`; adaptadores OpenAI/ArcadeDB `personal_axes.py`; `src/bootstrap/personal_axes.py` | `tests/test_personal_axis_application.py`, `test_personal_axis_extractor.py`; [contrato](../personal-axes-api.md) |
| Laboratorio / gestión de ejes pendiente | `src/extractors/personal_axes/`, casos `src/use_cases/*axis*.py`; puentes `src/bootstrap/{processing,failures}.py` | Suites de previews/histórico; [plan](personal-axes-migration-plan.md) |
| Imagen / arranque | `Dockerfile`, `Dockerfile.prod`, `docker-compose.yml`, `deploy.sh`, `.github/workflows/` | `tests/test_local_deploy.py`; [imágenes](../production-image-publishing.md) |

## Compatibilidad y dependencias

Las implementaciones migradas viven sólo en core, casos agrupados y adaptadores.
`src/domain/`, `src/services/`, la API anterior y los wrappers de extractores se
retiraron. Los casos reciben puertos; el adaptador traduce errores y devuelve datos
independientes del ORM. Bootstrap construye y cierra clientes por proceso.

Se conservan exclusivamente los entrypoints externos que todavía consume
`mirror-deploy`: `src.main`, `src.admin_main`, `src.processing.{broker,tasks,dispatcher}`,
`src.maintenance.data_migrations`, `src.graph.arcadedb.schema` y `src.administration.sync`.
Sus archivos sólo delegan a bootstrap. Retirarlos exige actualizar y validar esos
comandos externos. La política registra cada import exacto y su condición de retiro.

La gestión de ejes sigue heredada. `AxisHistoryRequests` adapta su reset SQL y los
hooks de procesamiento conservan el orden de escritura y errores privados.
`bootstrap/personal_axes.py` compone el extractor/proveedor canónicos. El binder
anterior traduce sus atributos a un contexto tipado hasta migrarse en etapa 4.

Generar el inventario bajo demanda con
`python3 scripts/check_architecture.py --inventory /tmp/mirror-architecture-inventory.json`;
ver [cobertura del chequeo](architecture-checks.md).

`prototypes/`, `build/`, caches, entornos y material personal no describen contratos.
Consultar [pendientes](../pending.md) sólo para tareas de ese alcance.
