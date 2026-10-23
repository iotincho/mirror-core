# Control de fronteras e inventario de migración

Herramientas de la etapa 0 del [plan](hexagonal-migration-plan.md). Las reglas
estables están en [ARCHITECTURE.md](../../ARCHITECTURE.md); este documento explica
qué se verifica hoy y cómo reproducir la línea de base del primer recorrido.

## Chequeo sin servicios

```bash
python3 scripts/check_architecture.py
.venv/bin/python -m pytest tests/test_architecture_boundaries.py
```

El script usa sólo la biblioteca estándar y analiza AST sin importar ni ejecutar
la aplicación. El workflow `.github/workflows/architecture-boundaries.yml` ejecuta
el chequeo y sus pruebas con Python 3.11, sin instalar dependencias del backend.

Cobertura actual:

- `src/core/` y el dominio heredado `src/domain/`: sólo dependencias internas
  admitidas, biblioteca estándar y Pydantic; sin infraestructura ni aplicación.
- `src/use_cases/`: core, colaboradores de aplicación, biblioteca estándar y
  Pydantic. Los imports existentes que aún incumplen requieren excepciones exactas.
- `src/adapters/access/`: aplicación/core, su propio código de acceso y frameworks
  de entrada; no imports de storage, proveedores ni SDKs de salida.
- Adaptadores de salida: core, su tecnología y su propia implementación; no
  aplicación ni persistencia privada de otro adaptador.
- Ningún módulo exterior a `src/bootstrap/` importa bootstrap sin una excepción
  puntual de transición. Las ubicaciones nuevas deben pertenecer al árbol objetivo.

Los demás archivos heredados aún no se declaran migrados. Su ubicación aparece
individualmente en `legacy_files`; esa lista no desactiva el veto a importar bootstrap
ni el control de imports dinámicos. No permite crear otra carpeta heredada o ampliar
un paquete completo por un patrón.

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

Puntos que el piloto debe conservar hasta adaptar consumidores:

| Frente | Entradas actuales que revisar |
| --- | --- |
| Composición HTTP/workspace | `src/dependencies.py`, `src/workspaces/dependencies.py`; overrides HTTP de las pruebas |
| Composición de ejecución | `src/processing/runtime.py`, `src/processing/workflows.py`, dependencias de cada familia, incluida compatibilidad con ejes |
| Contratos y stores | Modelos `src.domain`, `DocumentStore` y errores en `src.services.document_store`; stores de audio/grafo y artefactos |
| Títulos | `document_title.py`, `document_title_store.py`, `openai_document_title.py`, `ensure_document_titles.py`, `backfill_document_titles.py`; strings de monkeypatch de sus tests |
| Procesos | Dockerfiles: `src.main:app`; Compose: API pública/admin, Taskiq, dispatcher, sincronizador, esquema y migrador de datos |
| Migraciones SQL | `migrations/env.py` registra modelos de las familias y comparte `Base`; no reescribir revisiones aplicadas por mover imports |
| Empaquetado | `pyproject.toml` descubre `src*` y empaqueta `src.notifications/announcements.json`; actualizar si se mueve el recurso |
| Scripts/operación | Comandos de ingestión, reprocess, respaldo, limpieza y helpers; mantener el entrypoint usado o un puente acotado |

Los destinos específicos y su secuencia están en el plan. El inventario se vuelve
a generar al iniciar cada etapa; sus contadores no son una medida de deuda resuelta.

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
`src.graph.arcadedb.schema` con URL, nombre y credenciales de ese servidor explícitos.
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
corresponde al alcance de procesamiento durable de la etapa 2.

Eliminar después sólo los contenedores/volúmenes desechables de la ejecución. No
usar la configuración privada del Compose habitual ni un `down -v` sobre el proyecto.
Si el runner se bloquea dentro de un sandbox, detenerlo antes de repetir fuera del
aislamiento permitido; no presentar un bloqueo del entorno como regresión del producto.

## Regresión de procesamiento durable

La etapa 2 conserva los comandos/imports de procesos anteriores y mueve las
implementaciones según el [mapa](repository-map.md). Primero validar aplicación
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

Próximo alcance: etapa 3, audio, capas restantes, navegación y respaldos. Conservar
los bridges exactos de ejes, identidad/workspace e invitaciones indicados en el plan;
no copiar sus dependencias SQL a la aplicación nueva.
