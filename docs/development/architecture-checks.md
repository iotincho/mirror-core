# Control de fronteras e inventario de migración

Las reglas estables están en [ARCHITECTURE.md](../../ARCHITECTURE.md); este
documento explica el control vigente y cómo validar cada recorrido.

## Chequeo sin servicios

```bash
python3 scripts/check_architecture.py
.venv/bin/python -m pytest tests/test_architecture_boundaries.py
```

El script usa sólo la biblioteca estándar y analiza AST sin importar ni ejecutar
la aplicación. El workflow `.github/workflows/architecture-boundaries.yml` ejecuta
el chequeo y sus pruebas con Python 3.11, sin instalar dependencias del backend.

Cobertura actual:

- `src/core/`: sólo dependencias internas
  admitidas, biblioteca estándar y Pydantic; sin infraestructura ni aplicación.
- `src/use_cases/`: core, colaboradores de aplicación, biblioteca estándar y
  Pydantic. Los imports de infraestructura o compatibilidad se rechazan.
- `src/adapters/access/`: aplicación/core, su propio código de acceso y frameworks
  de entrada; no imports de storage, proveedores ni SDKs de salida.
- Adaptadores de salida: core, su tecnología y su propia implementación; no
  aplicación ni persistencia privada de otro adaptador.
- Ningún módulo exterior a `src/bootstrap/` importa bootstrap sin una excepción
  puntual de transición. Las ubicaciones nuevas deben pertenecer al árbol objetivo.

No quedan ubicaciones heredadas ni excepciones. Los procesos externos también
usan bootstrap. `legacy_files` y `exceptions` están vacíos; cualquier ubicación
o import fuera de las reglas falla en el chequeo.

## Excepciones y alcance del análisis

La política vive en [architecture-exceptions.json](../../config/architecture-exceptions.json).
Cada excepción declara archivo, import exacto, motivo y etapa de retiro. Un import
nuevo falla aunque venga del mismo módulo que otro import ya admitido. Las entradas
sin uso también fallan: al eliminar una dependencia, retirar su excepción en la
misma entrega. Eliminar de `legacy_files` un archivo retirado o movido.

No hay un comando de actualización automática del baseline. Una nueva excepción
se revisa como decisión explícita y no sustituye a ubicar bien el código nuevo.
No se admiten globs, excepciones por paquete completo o motivos vacíos.

El análisis contempla imports absolutos, relativos, locales a funciones y aliases.
Revisa `importlib.import_module` y `__import__`, incluidos destinos literales y
`fromlist`; un destino que no puede resolverse estáticamente falla y requiere revisión.
En el inventario inicial no se encontraron llamadas de carga dinámica en `src/`.

Es un control de dependencias directas, no una prueba de pureza de toda la lógica.
No interpreta `getattr`, wrappers arbitrarios de import, `eval/exec`, I/O mediante
biblioteca estándar, atributos de un runtime ni ciclos dentro de una misma capa.
Revisar esos casos en el recorrido y probar aplicación con puertos falsos. Las
excepciones heredadas no acreditan independencia transitiva de infraestructura.

## Inventario reproducible

```bash
python3 scripts/check_architecture.py --inventory /tmp/mirror-architecture-inventory.json
```

El JSON ordenado contiene módulos e imports de `src/`, candidatos de composición,
carga dinámica, consumidores inspeccionados, referencias estáticas, comandos de
proceso y recursos de `package-data`. No lee `.env`, datos personales ni estado de
servicios. Se genera bajo demanda; no versionar una copia grande por cada ejecución.

Antes de mover una ruta, consultar tanto `imports` como `consumer_references`.
Las referencias textuales incluyen strings de monkeypatch/CLI; no son sólo imports
Python. Los comandos identifican líneas para revisar, no equivalen a un parser de
Shell/Compose ni garantizan encontrar toda referencia construida dinámicamente.

Puntos de composición y consumo que revisar al mover rutas:

| Frente | Responsables actuales |
| --- | --- |
| API pública | `src/bootstrap/{public_api,public_router,public_dependencies}.py`; acceso HTTP en `src/adapters/access/api/public/` |
| Procesamiento | `src/bootstrap/{processing,workflows,worker,dispatcher,messaging}.py`; puertos core, casos agrupados y adaptadores por tecnología |
| Settings/diagnóstico | `src/bootstrap/{settings,logging,observability}.py`; proveedor Sentry en `src/adapters/providers/telemetry/` |
| Mantenimiento | `src/bootstrap/{data_migrations,cleanup_extractions,graph_schema}.py`; aplicación sin SQL/paths, adaptadores separados |
| Procesos externos | `mirror-deploy` consume directamente `src/bootstrap/`; su preflight verifica la imagen antes de detener servicios |
| Alembic | `migrations/env.py` importa modelos canónicos, incluido `migration_models`; no reescribir revisiones aplicadas |
| Empaquetado | `pyproject.toml` descubre `src*` y empaqueta `src.adapters.access.cli/announcements.json`; comprobar wheel desde fuentes limpias |

El inventario se genera bajo demanda y sus contadores no representan porcentaje
de deuda resuelta. La política no admite actualmente excepciones ni archivos
heredados en ninguna capa.

## Regresión de ejes y procesamiento

Las pruebas consumen los casos canónicos, con definiciones tipadas y traducción
HTTP en acceso; no se admiten fachadas de compatibilidad para fixtures.
Verificar fingerprints/artefactos anteriores y recuperación sin proveedor con
`tests/test_personal_axis_application.py`. Los puertos en memoria se ejercitan en
`test_personal_axis_history.py`, `test_personal_axis_previews.py` y
`test_personal_axis_reads.py`.

Con PostgreSQL/ArcadeDB/RabbitMQ desechables preparados y sus variables de
[pruebas](testing.md), ejecutar la regresión conjunta:

```bash
.venv/bin/python -m pytest tests/integration/test_axis_history.py \
  tests/integration/test_personal_axis_processing.py tests/integration/test_axis_previews.py \
  tests/integration/test_personal_axis_layer.py tests/integration/test_extractor_jobs.py \
  tests/integration/test_reprocess_notes.py tests/integration/test_audio_invitation_processing.py \
  tests/integration/test_processing_postgres.py -ra
```

El último archivo incluye workers Taskiq reales, mensajes duplicados y recuperación
tras pérdida de un worker. No contar un skip por falta de RabbitMQ como validación.
Al retirar paquetes comprobar también wheel, recurso CLI, imports con Python 3.13
y arranque/cierre de API, worker y dispatcher sobre el entorno aislado. La tarea
sigue siendo `processing.execute`; las versiones de workflows no se cambian por
mover sus implementaciones. Validar salud/autorización HTTP y un job sintético por
outbox antes de apagar procesos; comprobar cierre de recursos sin llamadas LLM.

## Regresión de consolidación

```bash
.venv/bin/python -m pytest tests/test_consolidated_boundaries.py \
  tests/test_processing_application.py tests/test_event_stream_logging.py \
  tests/test_document_archive.py tests/test_observability.py
```

Luego, con motores desechables configurados según las fixtures:

```bash
.venv/bin/python -m pytest tests/integration/test_processing_events.py \
  tests/integration/test_data_migrations.py tests/integration/test_extraction_cleanup.py \
  tests/integration/test_deferred_ingestion.py tests/integration/test_reprocess_notes.py -rs
```

Esas familias requieren PostgreSQL/RabbitMQ y ArcadeDB según el test; cleanup usa
`CLEANUP_TEST_ARCADEDB_URL` y `CLEANUP_TEST_ARCADEDB_PASSWORD`. Completar también
regresión de jobs/capas/ejes y revocación al cambiar estas fronteras. Comprobar imagen
e inicio/cierre de procesos por separado; la colección de tests no valida servicios.

## Regresión de invitaciones, bandeja y administración

```bash
.venv/bin/python -m pytest tests/test_channels_application.py \
  tests/test_exteriorization.py tests/test_notifications.py \
  tests/test_administration_api.py tests/test_platform_activity.py \
  tests/test_processing_application.py
```

Para integración, preparar bases PostgreSQL desechables migradas a head y configurar
`INVITATIONS_TEST_DATABASE_URL`, `NOTIFICATIONS_TEST_DATABASE_URL`,
`ADMIN_TEST_DATABASE_URL` y `RECOVERY_TEST_DATABASE_URL`, con los prefijos exigidos
por cada fixture. Transporte real usa `INVITATIONS_TEST_RABBITMQ_URL`; la vinculación
de respuestas de audio y la regresión de procesamiento requieren además su entorno
aislado de procesamiento/grafo. No reutilizar bases ni volúmenes con datos personales.

```bash
.venv/bin/python -m pytest tests/integration/test_exteriorization_postgres.py \
  tests/integration/test_notifications_postgres.py \
  tests/integration/test_administration.py \
  tests/integration/test_password_recovery_postgres.py -rs
```

Cubrir horarios, bandeja sin push, revocación conjunta, cambio de cuenta,
distribución reanudable, inventario incompleto, permisos y confirmación de escrituras.
Web Push se valida con el SDK declarado y HTTP simulado, sin envío externo.
Al mover el catálogo, construir el wheel desde una copia limpia de fuentes y comprobar
`src/adapters/access/cli/announcements.json`; un `build/` anterior puede ocultar errores.

## Regresión base de documentos y títulos

Primero, pruebas sin servicios ni proveedores reales:

```bash
.venv/bin/python -m pytest \
  tests/test_ingest_document.py tests/test_documents_route.py \
  tests/test_document_title_extractor.py tests/test_lazy_document_titles.py \
  tests/test_title_backfill_cli.py tests/test_openapi_docs.py \
  tests/test_document_pilot.py tests/test_title_provider_resources.py -ra
```

Después preparar PostgreSQL y ArcadeDB **desechables**, con puertos sólo en loopback
y sin montar volúmenes existentes. Usar las imágenes actuales del Compose como
referencia (`postgres:17-alpine`, `arcadedata/arcadedb:26.9.1`). Aplicar `alembic
upgrade head` únicamente a la base SQL de prueba, con `DATABASE_URL` explícito.

Las fixtures de títulos crean/eliminan sus propias bases ArcadeDB. La prueba
`test_real_arcadedb_document_write_and_replay` requiere además una base llamada
`processing_test` ya creada con esquema base. En el servidor desechable, crearla
mediante `/api/v1/server` (`create database processing_test`) y aplicar
`src.bootstrap.graph_schema` con URL, nombre y credenciales de ese servidor explícitos.
Ese comando aplica esquema; no crea por sí mismo la base.

Exportar las variables del entorno aislado:

- `DATABASE_URL` y `PROCESSING_TEST_DATABASE_URL`: misma base SQL desechable migrada.
- `PROCESSING_TEST_ARCADEDB_URL` y `EMOTIONS_TEST_ARCADEDB_URL`: servidor desechable.
- `PROCESSING_TEST_ARCADEDB_PASSWORD` y `EMOTIONS_TEST_ARCADEDB_PASSWORD`: su contraseña.
- `SENTRY_DSN` vacío y `OPENAI_API_KEY` ficticia; se usan proveedores determinísticos.

```bash
.venv/bin/python -m pytest \
  tests/integration/test_deferred_ingestion.py \
  tests/integration/test_document_title_processing.py \
  tests/integration/test_document_titles_on_read.py -ra
```

El recorrido valida originales, aceptación idempotente, lectura inmediata de grafo,
títulos, retry sin repetir proveedor y generación acotada al leer. El caso opcional
de worker real necesita también `PROCESSING_TEST_RABBITMQ_URL` de un broker aislado;
si se omite, registrar el skip y no acreditar transporte real. Su validación completa
se comprueba en la regresión de procesamiento durable.

Eliminar después sólo los contenedores/volúmenes desechables de la ejecución. No
usar la configuración privada del Compose habitual ni un `down -v` sobre el proyecto.
Si el runner se bloquea dentro de un sandbox, detenerlo antes de repetir fuera del
aislamiento permitido; no presentar un bloqueo del entorno como regresión del producto.

## Regresión de procesamiento durable

Las implementaciones durables están separadas según el [mapa](repository-map.md),
con composición explícita de todos sus entrypoints. Primero validar aplicación
sin motores; la prueba de imports bloquea infraestructura explícitamente:

```bash
.venv/bin/python -m pytest tests/test_processing_application.py tests/test_processing_transport.py
```

Con las bases desechables anteriores, agregar `PROCESSING_TEST_RABBITMQ_URL` de un
broker exclusivo de prueba para acreditar workers reales, ACK y escalado. Los
subprocesos de esas pruebas toman también `DATABASE_URL`, las variables del grafo
y el `PYTHONPATH` de sus fixtures; no usar un Compose con datos de personas.

```bash
.venv/bin/python -m pytest \
  tests/integration/test_processing_postgres.py tests/integration/test_processing_events.py \
  tests/integration/test_extractor_jobs.py tests/integration/test_reprocess_notes.py \
  tests/integration/test_deferred_ingestion.py tests/integration/test_document_title_processing.py \
  tests/integration/test_document_titles_on_read.py tests/integration/test_title_backfill.py \
  tests/integration/test_personal_axis_processing.py tests/integration/test_axis_history.py \
  tests/integration/test_axis_previews.py tests/integration/test_document_embedding_processing.py \
  tests/integration/test_audio_invitation_processing.py -rs
# Sólo contra el SQL desechable migrado, para detectar diferencias de modelos:
.venv/bin/python -m alembic check
```

## Regresión de audio, extractores, grafo y respaldos

Los casos usan puertos de audio, persistencia de emociones,
embeddings, lectura/borrado y aceptación de respaldos. La prueba de imports incluye
esas aplicaciones y bloquea también tiktoken. Primero:

```bash
.venv/bin/python -m pytest tests/test_stage3_application.py tests/test_processing_application.py \
  tests/test_emotion_extractor.py tests/test_document_embedding_extractor.py \
  tests/test_openai_transcription_provider.py tests/test_document_archive.py \
  tests/test_graph_navigation.py tests/test_emotion_projection.py
```

Con los servicios desechables anteriores, configurar también
`EMBEDDINGS_TEST_ARCADEDB_URL` y `EMBEDDINGS_TEST_ARCADEDB_PASSWORD` al mismo
servidor de prueba. Agregar a la regresión durable:

```bash
.venv/bin/python -m pytest tests/integration/test_emotion_layer.py \
  tests/integration/test_document_embedding_layer.py tests/integration/test_emotion_processing.py \
  tests/integration/test_graph_navigation_live.py tests/integration/test_emotion_exploration.py -rs
```

La fixture de exploración inserta ejecuciones históricas duplicadas explícitamente;
las extracciones actuales reemplazan su capa. Así se prueba deduplicación de lectura
sin cambiar el reemplazo atómico para satisfacer una expectativa antigua.
No reintroducir puentes de ejes ni wrappers de entrypoints retirados.
## Regresión de identidad y workspaces

Política de contraseña, credenciales, sesión y recuperación en core;
login, recuperación, entrega de correo, acceso/provisión/reconciliación en aplicación.
Los casos se importan con FastAPI Users, cryptography y demás infraestructura bloqueados.

```bash
.venv/bin/python -m pytest tests/test_identity_application.py tests/test_processing_application.py \
  tests/test_signup_flow.py tests/test_password_recovery.py tests/test_workspaces.py \
  tests/test_workspace_dependencies.py tests/test_google_oauth.py tests/test_user_management.py
```

Usar bases PostgreSQL desechables migradas separadas, con nombres que comiencen
por `recovery_test` y `workspace_test`. Configurar `RECOVERY_TEST_DATABASE_URL` y
`WORKSPACE_TEST_DATABASE_URL`. Provisión real requiere además
`WORKSPACE_TEST_ARCADEDB_URL` y `WORKSPACE_TEST_ARCADEDB_PASSWORD` del servidor
ArcadeDB desechable; la fixture no carga `.env` y usa configuración explícita.
La prueba asigna principales por cuenta y comprueba sus permisos reales.

```bash
.venv/bin/python -m pytest tests/integration/test_password_recovery_postgres.py \
  tests/integration/test_password_recovery_migration.py \
  tests/integration/test_workspace_provisioning.py -rs
```

También ejecutar la regresión durable anterior: cambia la identidad de imports
usada por API, workers, scripts y Alembic. No reescribir
revisiones ya aplicadas. Alembic debe seguir informando que no hay cambios nuevos.
Las carpetas antiguas de identidad/workspace y sus entradas de excepciones se
retiraron; no restaurarlas para corregir un importador sin migrar.
Invitaciones, notificaciones y administración tienen capas separadas; los
consumidores externos y sus puntos de composición se describen en el mapa.
