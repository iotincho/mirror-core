# El Espejo · backend

Instrumento de introspección personal asistido por IA. Conserva las notas y el
audio originales y permite explorar extracciones con evidencia del propio material.
Las interpretaciones deben distinguirse de los hechos y conservar su procedencia.

Este repositorio contiene la API pública, la API administrativa y el procesamiento
durable. Las interfaces viven en `mirror-pwa` y `mirror-admin`; el despliegue de
producción se configura en `mirror-deploy`.

## Empezar aquí

- **Implementar con un agente:** [AGENTS.md](AGENTS.md).
- **Organización y responsabilidades:** [arquitectura](ARCHITECTURE.md).
- **Encontrar código y pruebas:** consultar el contrato en el [índice](docs/README.md) y buscar el área en `src/` y `tests/`.
- **Agregar o modificar comportamiento:** [guía de implementación](docs/development/implementation.md).
- **Ejecutar verificaciones:** [guía de pruebas](docs/development/testing.md).
- **Buscar un contrato o procedimiento:** [índice de documentación](docs/README.md).
- **Configurar agentes y reducir contexto:** [guía de agentes](docs/development/agents.md).

## Capacidades implementadas

| Área | Comportamiento | Referencia |
| --- | --- | --- |
| Acceso | Email/contraseña, Google OAuth, sesiones revocables y recuperación | [Registro](docs/signup.md), [recuperación](docs/password-recovery.md) |
| Aislamiento | Workspace por usuario con archivos y credenciales de grafo propios | [Registro y workspace](docs/signup.md) |
| Notas y audio | Ingestión `/v2`, transcripción, reintentos, SSE y originales recuperables | [Ingestión](docs/deferred-ingestion.md), [respaldos](docs/document-archives.md) |
| Extractores | Emociones, embeddings, títulos y ejes personales como trabajos independientes | [Coordinación](docs/extractor-jobs.md), [ejes](docs/personal-axes-api.md) |
| Exploración | Lectura del grafo y navegación por emociones con citas | [Grafo](docs/graph-navigation.md) |
| Laboratorio | Ejes personales, pruebas temporales y versiones aceptadas | [Contrato](docs/personal-axes-api.md) |
| Invitaciones | Preguntas diarias voluntarias, centro de notificaciones y respuestas de voz | [Notificaciones](docs/notification-center.md), [audio](docs/audio-invitation-replies.md) |
| Administración | Proceso separado para inventario, métricas y permisos | [Administración](docs/admin-lan.md) |

Laboratorio requiere `PERSONAL_AXES_ENABLED` y permiso por cuenta. Email y Web Push
requieren configurar sus proveedores. Una capacidad implementada no acredita
que esté habilitada o validada en producción.

La extracción genérica anterior, búsqueda/reflexión HTTP y Constelación exploratoria
se retiraron; no confundirlas con los embeddings actuales ni el visor de emociones.
Consultar [migraciones de datos](docs/data-migrations.md) antes de tocar compatibilidad.

## Arquitectura en breve

```text
PWA → API pública → sesión y workspace → casos de uso
                       ├─ originales en archivos + Document en ArcadeDB
                       └─ aceptación PostgreSQL: recibo + job + evento + outbox
                                                ↓
                                    dispatcher → RabbitMQ → worker
                                                ↓
                                 checkpoints + artefactos + proyecciones

Panel admin → API administrativa separada → inventario / métricas / permisos
```

PostgreSQL conserva identidad y estado durable; RabbitMQ transporta entregas;
ArcadeDB conserva documentos y proyecciones. Los volúmenes de archivos contienen
originales y artefactos. Ninguno reemplaza el respaldo de los otros.

Stack: Python ≥3.11 (Docker de desarrollo: 3.14; producción: 3.13), FastAPI/Pydantic,
SQLAlchemy/Alembic,
PostgreSQL, Taskiq/RabbitMQ, ArcadeDB y proveedores OpenAI. WebM requiere `ffmpeg`
con `libmp3lame`, incluido en ambos Dockerfiles.

## Desarrollo local

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env.local
```

Editar `.env.local` antes de iniciar: configurar `AUTH_SESSION_SECRET`, proveedores
y las variables requeridas por Compose. Para HTTP local, `AUTH_COOKIE_SECURE=false`;
mantenerlo en `true` cuando se expone por HTTPS. Las rutas locales y credenciales
del ejemplo son para desarrollo.

Compose lee `.env.local` para los contenedores; `--env-file` también lo usa para
interpolar el YAML. La PWA requiere el checkout hermano y su propio `.env`.

```bash
docker compose --env-file .env.local config --quiet
docker compose --env-file .env.local up -d --build
```

Para comprobar los entrypoints de la imagen de desarrollo sin iniciar servicios
ni acceder a datos, usar el perfil `tools`:

```bash
docker compose --env-file .env.local --profile tools build entrypoint-check
docker compose --env-file .env.local --profile tools run --rm --no-deps entrypoint-check
```

El chequeo importa API pública/admin, worker, dispatcher, inventario y migraciones;
verifica revisiones Alembic y el nombre `processing.execute`. No monta originales,
no carga `.env.local` dentro del contenedor y se ejecuta sin red. `deploy.sh` lo
incluye automáticamente después del build y antes de detener procesos.

El stack incluye API, PWA, proxy, PostgreSQL, ArcadeDB, RabbitMQ, migraciones,
worker y dispatcher. Por defecto el proxy publica `http://localhost:8080` y
Swagger `http://localhost:8080/api/docs`. La API usa `root_path=/api`;
las rutas internas no duplican ese prefijo. El perfil administrativo y el túnel
tienen configuración adicional: ver [LAN](docs/admin-lan.md).

Si se ejecuta Python directamente, `Settings` lee `.env` o el entorno del proceso,
no `.env.local`. Usar [pruebas y ejecución por proceso](docs/development/testing.md).

Para actualizar un entorno con datos existentes, seguir el orden de migraciones de
[implementación](docs/development/implementation.md); `deploy.sh` detiene procesos
y aplica migraciones. No usarlo como comprobación de documentación.

## Verificación y contribución

```bash
.venv/bin/python scripts/check_repo_docs.py
.venv/bin/python scripts/check_architecture.py
.venv/bin/python -m ruff check src tests scripts
# Ejemplo acotado; elegir la suite según el cambio.
.venv/bin/python -m pytest tests/test_health.py tests/test_config.py tests/test_openapi_docs.py
```

La [matriz de pruebas](docs/development/testing.md) indica cuándo ampliar a
integraciones con servicios aislados. Actualizar código, prueba de comportamiento
y contrato en la misma entrega. Publicar imágenes usa
[el workflow de este repositorio](docs/production-image-publishing.md).

Los [pendientes consolidados](docs/pending.md) reúnen funciones diferidas y
validaciones abiertas; no definen capacidades activas ni autorizan implementación.
