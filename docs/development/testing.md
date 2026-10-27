# Pruebas y ejecución

Usar el virtualenv del backend para validar sus dependencias. El virtualenv de
análisis autorizado por el usuario puede servir para tareas auxiliares, pero no
reemplaza la instalación del proyecto.

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check src tests scripts
git diff --check
```

## Elegir el alcance

| Cambio | Primera verificación | Ampliar cuando corresponda |
| --- | --- | --- |
| Documentación / instrucciones | `python3 scripts/check_repo_docs.py` | Revisar ejemplos contra código/config; no ejecutar servicios |
| Fronteras / movimientos de módulos | `python3 scripts/check_architecture.py` y `tests/test_architecture_boundaries.py` | [Inventario y regresiones](architecture-checks.md) |
| Ruta / schema público | Test HTTP de la ruta + `tests/test_openapi_docs.py` | Autenticación, ownership y casos de error |
| Cuenta / workspace | `tests/test_identity_application.py`, `tests/test_signup_flow.py`, `tests/test_workspace_dependencies.py`, `tests/test_workspaces.py` | Recuperación PostgreSQL y `tests/integration/test_workspace_provisioning.py`; [comandos](architecture-checks.md#regresión-de-identidad-y-workspaces) |
| Extractor | Test de la capa y configuración | Persistir artefacto sin proveedor, reemplazo y aislamiento de capas |
| Runtime / locks / outbox | `tests/test_processing_transport.py`, `tests/test_processing_artifacts.py` | `tests/integration/test_processing_postgres.py` y jobs afectados |
| Aplicación durable / transacciones | `tests/test_processing_application.py` con puertos en memoria e imports de infraestructura bloqueados | Reprocess, jobs, backfill e histórico de ejes con PostgreSQL/ArcadeDB aislados |
| Audio / emociones / embeddings / respaldos | `tests/test_stage3_application.py` y suite de la capacidad | Replay sin proveedor, transacciones reales de capas y navegación; [comandos](architecture-checks.md#regresión-de-audio-extractores-grafo-y-respaldos) |
| Grafo | Test de proyección/navegación afectado | Integración ArcadeDB con esquema y transacciones reales |
| Invitaciones / bandeja / administración | `tests/test_channels_application.py`, `tests/test_exteriorization.py`, `tests/test_notifications.py`, `tests/test_administration_api.py` | SQL, revocación y sincronizador; [comandos](architecture-checks.md#regresión-de-invitaciones-bandeja-y-administración) |
| Migración | Revisión de head + integración de migración | Upgrade/recuperación con base aislada |
| Docker / publicación | `tests/test_local_deploy.py`, configuración Compose | Build o smoke aislado si cambia comportamiento del contenedor |

Buscar pruebas de la capacidad por nombre y consultar su contrato en el [índice](../README.md).
No escribir pruebas que sólo repitan la implementación. Un cambio de comportamiento
debe cubrir su resultado observable y el fallo que pretende resolver.

```bash
# Ejemplo de prueba focalizada.
.venv/bin/python -m pytest tests/test_emotion_extractor.py
# Suite sin el directorio de integraciones; puede contener checks de entorno opt-in.
.venv/bin/python -m pytest tests --ignore=tests/integration
# Suite completa cuando el alcance lo justifica; revisar skips.
.venv/bin/python -m pytest
```

## Integraciones opt-in

No apuntar a bases o brokers usados por personas. Los tests crean, modifican y
eliminan datos y algunos lanzan workers reales. La ausencia de variables produce
skips; no significa que la integración haya pasado.

- PostgreSQL migrado: `PROCESSING_TEST_DATABASE_URL`.
- Transporte real: `PROCESSING_TEST_RABBITMQ_URL`, broker/vhost separado.
- Grafo de capas: `EMOTIONS_TEST_ARCADEDB_URL` y `EMOTIONS_TEST_ARCADEDB_PASSWORD`.
- Embeddings: `EMBEDDINGS_TEST_ARCADEDB_URL` y `EMBEDDINGS_TEST_ARCADEDB_PASSWORD`.
- Recuperación: `RECOVERY_TEST_DATABASE_URL`, base desechable con prefijo `recovery_test`.
- Provisión real: `WORKSPACE_TEST_DATABASE_URL` con prefijo `workspace_test`,
  `WORKSPACE_TEST_ARCADEDB_URL` y `WORKSPACE_TEST_ARCADEDB_PASSWORD` desechables.
- Otras familias pueden requerir variables adicionales: leer el encabezado y
  fixtures del test seleccionado antes de ejecutarlo.

```bash
# Una vez exportadas las variables del entorno aislado:
.venv/bin/python -m pytest tests/integration/test_processing_postgres.py -rs
```

Las integraciones determinísticas no prueban calidad de un LLM real, entrega de
correo/push, dispositivos ni disponibilidad de producción. Evitar llamadas pagas
en la suite habitual; usar proveedores simulados y fixtures sintéticas.

## Chequeo de imagen de desarrollo

`entrypoint-check` es un servicio del perfil `tools`, construido con el `Dockerfile`
de desarrollo. Valida imports y revisiones empaquetadas sin red, volúmenes ni acceso
a datos. Para ejecutar sólo esa comprobación, usar los comandos del
[README](../../README.md). Un error detiene `deploy.sh` antes de parar servicios.
La comprobación no reemplaza las pruebas de arranque ni las migraciones de un entorno.

## Procesos fuera de Compose

`Settings` lee `.env` o variables exportadas. Configurar paths escribibles y URLs
alcanzables desde el host; los nombres `postgres`/`rabbitmq` de Compose no son URLs
del host. Usar los valores de [.env.example](../../.env.example) como referencia.

Con servicios de desarrollo preparados, aplicar esquema antes de consumir jobs:

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m src.bootstrap.graph_schema
.venv/bin/python -m uvicorn src.bootstrap.public_api:app --host 127.0.0.1 --port 8000
# En terminales separadas, con la misma configuración y volumen:
.venv/bin/python -m taskiq worker src.bootstrap.messaging:broker src.bootstrap.worker \
  --workers 1 --max-async-tasks 4 --max-prefetch 0 --ack-type manual
.venv/bin/python -m src.bootstrap.dispatcher
```

Estos comandos aplican a un entorno de desarrollo preparado. Un entorno con datos
previos también necesita las migraciones de datos descritas en
[implementación](implementation.md). No ejecutar migraciones para validar un cambio
de documentación.
