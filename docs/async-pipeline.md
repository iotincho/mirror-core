# Pipeline async — etapa 2

> Documento histórico: el extractor exploratorio y el análisis anterior de
> Constelación se retiraron. El estado actual está en
> [Retiro de la extracción](extraction-retirement.md).

La etapa 2 del [plan de procesamiento diferido](deferred-processing.md) convierte
los contratos de I/O y sus consumidores a async. Las notas siguen esperando el
pipeline en su request, con las mismas respuestas HTTP; el audio sigue usando
`BackgroundTasks`. Taskiq, RabbitMQ y estados durables se incorporan después.

## Implementación

- Extracción, transcripción, embeddings, reflexión y análisis de Constelación
  usan `AsyncOpenAI` y `await`. El camino compartido de búsqueda/grafo también
  es async; conserva perfiles, evidencia literal y formatos de respuesta.
- `ArcadeDBGraphStore` usa `AsyncArcadeDBHTTPClient` con HTTPX. Cada transacción
  conserva su propio session ID; no modifica headers globales del cliente.
  Ante fallo o cancelación intenta rollback y propaga el error original.
- El cliente síncrono de ArcadeDB se conserva para schema y administración,
  cuyos callers async existentes ya ejecutan esas operaciones en threads.
- Los ports de originales, audio, extracciones y reflexiones son async. Sus
  adaptadores de archivos ejecutan operaciones completas con `asyncio.to_thread`.
  Se preserva la publicación atómica y se usan temporales únicos. Crear un
  original usa publicación exclusiva mediante hard link para evitar sobrescritura
  cuando dos threads reciben el mismo UUID; destino y temporal están en el mismo
  filesystem. Es compatible con los volúmenes Linux locales previstos.
- Los clientes de proveedores se reutilizan por proceso y se cierran en el
  lifespan de FastAPI. Los clientes inyectados son prestados y los cierra su
  propietario. Un futuro worker debe cerrar los mismos adaptadores antes de
  terminar su event loop.
- El grafo pertenece al runtime de cada workspace/request y se cierra al finalizar
  la respuesta y sus BackgroundTasks. La dependencia de sesión PostgreSQL sigue
  siendo por request. FastAPI requiere al menos `0.118`, por el orden de limpieza
  de dependencias con yield después de la respuesta.

Uso desde otro caller Python:

```python
document = await ingest.execute(new_document)
processed = await pipeline.process_existing(document.id)
```

Las factories de dependencias son síncronas cuando sólo construyen objetos;
las operaciones de red y de filesystem se esperan desde los casos de uso.

## Límites iniciales configurables

| Variable | Default | Alcance |
| --- | --- | --- |
| `PROVIDER_MAX_CONCURRENCY` | 4 | Solicitudes simultáneas por adaptador/proceso |
| `PROVIDER_TIMEOUT_SECONDS` | 120 | Timeout HTTP del SDK por operación de red |
| `GRAPH_MAX_CONNECTIONS` | 20 | Pool HTTP de cada runtime de workspace |
| `GRAPH_TIMEOUT_SECONDS` | 30 | Timeout HTTP del grafo |

Réplicas y adaptadores distintos multiplican la concurrencia total. Estos valores
no constituyen un rate limit global por cuenta. Se mantienen los reintentos por
defecto del SDK durante esta etapa; la política de reintentos durables del workflow
deberá coordinarlos explícitamente en etapa 3. Los timeouts HTTP no son un límite
total del procesamiento ni incluyen espera por un slot de concurrencia.

## Validación y límites

La suite adapta los mocks a los nuevos puertos y conserva las verificaciones de
contenido, títulos, errores, recuperación de audio, grafo y contratos HTTP.
`tests/test_async_pipeline.py` verifica además el SDK async real con transporte
simulado, límites de concurrencia, dos pipelines simultáneos, aislamiento de
sesiones de grafo, rollback por cancelación, I/O de archivos fuera del loop,
publicación concurrente del mismo UUID y limpieza del runtime tras BackgroundTasks.

Los tests optativos de ArcadeDB real se adaptaron al cliente async; requieren
`ARCADEDB_INTEGRATION=1` y una instancia configurada. Las pruebas con transportes
simulados no demuestran funcionamiento contra proveedores o bases desplegados.

Cancelar una coroutine no detiene un thread de filesystem que ya comenzó.
Checkpoints, leases, fencing, outbox y recuperación durable siguen perteneciendo
a etapa 3. Esta migración no incorpora esas garantías ni mide throughput de
producción.

Referencias: [SDK Python oficial de OpenAI](https://developers.openai.com/api/reference/python)
y [lifecycle de dependencias de FastAPI](https://fastapi.tiangolo.com/advanced/advanced-dependencies/).
