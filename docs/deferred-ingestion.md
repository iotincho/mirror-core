# Ingestión y workflows diferidos

> Contrato de aceptación durable. Para las capas y versiones de workflow actuales
> consultar [trabajos por extractor](extractor-jobs.md).

La API acepta una nota de texto/archivo después de guardar su original, confirmar
su vértice `Document` en ArcadeDB y confirmar el procesamiento y su outbox en
PostgreSQL. No ejecuta modelos durante esos requests. El dispatcher y los workers
del Compose habitual completan las extracciones,
aunque el cliente cierre la app y nunca consulte el estado.

## Transición de clientes

Los uploads nuevos usan `/v2/documents`, `/v2/documents/files` y `/v2/audio-notes`.
Las rutas legacy de upload y extracción retiradas responden `410`; no mantienen
un camino síncrono alternativo. La integración `/v2` y SSE está documentada en
[eventos PWA](processing-pwa-events.md). Los endpoints no usan `BackgroundTasks`.
El borrado participa en la exclusión por recurso y rechaza conflictos con
trabajos diferidos activos.

| Operación | Contrato |
| --- | --- |
| `POST /v2/documents` | JSON de documento + `Idempotency-Key`; original y procesamiento |
| `POST /v2/documents/files` | Multipart `.md`/`.txt` UTF-8 + clave; original y procesamiento |
| `POST /v2/audio-notes` | Multipart de audio + clave; audio y procesamiento |
| `GET /processing/{id}` | Estado completo del workflow; sólo del propietario |
| `GET /processing?active=true&limit=50&cursor=…` | Página con `items` y `next_cursor`; orden por fecha/UUID |
| `POST /processing/{id}/retry` | Clave nueva para otro retry manual; `202` al reprogramar, `200` si ya activo/completo o misma solicitud |
| `POST /v2/documents/{id}/processing` | Nueva ejecución deliberada; `409` si el recurso está activo |
| `POST /v2/documents/reprocess` | Reprocesamiento por lote; ver [contrato](reprocess-notes.md) |
| `POST /v2/audio-notes/{id}/documents` | Recuperar su workflow o un audio legado ya transcrito, sin retranscribir |
| `GET /v2/documents` y `GET /v2/documents/{id}` | Original con su último procesamiento, incluso failed/completed |
| `GET /v2/audio-notes/{id}` | Audio con su último procesamiento completo |
| `DELETE /documents/{id}` | `409 processing_active` si existe trabajo activo, incluidos padre/hijo |

`Idempotency-Key` es un UUID obligatorio en esos POST. El cliente debe guardar
la clave antes del envío y reutilizarla si no sabe si la respuesta llegó.
Los uploads devuelven `202` mientras el procesamiento no esté completo y `200`
para una repetición ya completa. Devuelven `Location: /processing/{id}`, con el
`root_path` del despliegue incluido (`/api/processing/{id}` detrás del proxy).

Ejemplo:

```bash
curl -X POST http://localhost:8080/api/v2/documents \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 452370a3-317c-4b29-bb34-9b8b69d80974' \
  -b 'cookie-de-sesion' \
  -d '{"content":"Quiero más autonomía.","source":"manual"}'
```

```json
{
  "document": {"id": "…", "title": null, "content": "Quiero más autonomía.", "source": "manual"},
  "processing": {"id": "…", "workflow": "document", "status": "queued", "stage": "document_persistence"}
}
```

La respuesta real incluye todos los campos de `DocumentResponse` y
`ProcessingResponse`. La proyección pública omite configuración, credenciales,
lease y tokens internos. `processing.status` describe el flujo completo;
`audio_note.status` sigue describiendo transcripción. `document_id` del audio se
publica después de guardar el derivado y confirmar su `Document` en ArcadeDB,
antes de que terminen las extracciones. El upload de audio sigue aceptándose
sin esperar transcripción; la persistencia del documento ocurre en el worker
cuando ya existe la transcripción.

## Aceptación durable

`SubmitDocument` y `SubmitAudioNote` reservan un recibo SQL por propietario,
operación y clave antes de escribir. El recibo contiene IDs, configuración y
hash/manifiesto, sin texto completo ni audio. La reserva vence a los 90 segundos;
una petición simultánea recibe `409 upload_in_progress` y puede repetir la clave.

El original se publica de forma exclusiva y se sincroniza el archivo y su
directorio. Para documentos, bajo el lock del recurso se confirma también el
`MERGE` transaccional del vértice base en ArcadeDB antes de aceptar la recepción.
Se conserva `GRAPH_TIMEOUT_SECONDS` (30 segundos por defecto), sin un timeout
total adicional más corto. Emociones, embeddings y título siguen diferidos.
Una transacción posterior acepta el recibo y crea registro, evento
y outbox juntos. Un fallo de ArcadeDB o SQL después de escribir devuelve `503`: el original
permanece guardado. Repetir la clave recupera la aceptación; el dispatcher puede
completar reservas vencidas cuyo original íntegro coincide con el hash. También
repara metadatos de audio si sobrevivió el raw antes de escribir el JSON.

La recuperación de documentos pendientes valida el original bajo el mismo lock
que el borrado y confirma el vértice antes de aceptar la recepción. Un fallo de
grafo conserva el recibo para otro intento y se reporta como
`submission_graph_persistence_failed`. Los workers conservan su paso idempotente
de persistencia para recuperación. Un replay de una recepción ya aceptada no
reescribe el vértice ni los títulos que pudieron generar los extractores.

Esta garantía se aplica a nuevas aceptaciones. No espera resultados de extracción
ni repara automáticamente documentos históricos con una proyección faltante.
Un listado concurrente aún puede ver el archivo mientras el alta está en curso;
la confirmación HTTP ocurre después del commit del documento base.

La misma clave con contenido/metadatos/ID distintos devuelve `409`. Una clave
nueva con ID explícito de un documento ya aceptado puede devolver su ejecución
original si coincide la identidad; esa clave queda vinculada también y no puede
crear otra nota después. Documentos distintos con el mismo texto no se fusionan.
Un documento legado ya existente no se reemplaza a través de un upload nuevo:
para procesarlo se usa la operación explícita de extracción.

RabbitMQ no participa en la aceptación HTTP. Si cae después del commit, el job
queda queued y su intención de entrega en SQL. Los uploads de texto tienen un
límite `DOCUMENT_MAX_UPLOAD_BYTES` de 5 MiB por defecto; el audio conserva su
límite configurado. Los multipart se leen por bloques y se rechaza el exceso
antes de crear un recibo.

## Casos de uso y checkpoints

El coordinador de documento actual usa estas transiciones:

```text
document_persistence → extractor_processing → done
```

Cada hijo ejecuta extracción y persistencia con checkpoints propios. La capa valida
su resultado y, cuando contiene citas, la evidencia contra el original. Conserva
el resultado en un artefacto con identidad del original y configuración. Un retry
reutiliza el artefacto y no llama nuevamente al proveedor; ver [jobs](extractor-jobs.md).

Las escrituras en el grafo usan IDs deterministas y MERGE. La extracción verifica
documento/run, items y relaciones dentro de su transacción; los embeddings
verifican los IDs escritos y sus enlaces antes de commit. Un commit ambiguo se
repite con los mismos IDs y vectores, conservando una sola representación.

`ProcessAudioNote` posee transcripción, creación del documento y espera del hijo:

```text
transcription → document_creation → document_processing (waiting) → completed
```

La transcripción se guarda como artefacto y en el audio antes de avanzar. Audio
y documento comparten UUID y el derivado conserva su procedencia. La creación
del hijo, la transición del padre a waiting, sus eventos y la outbox del hijo
son atómicas en SQL. El padre libera el worker mientras espera. El resultado del
hijo encola la continuación del padre; el reconciliador recupera una continuación
perdida. Fallar el hijo falla el padre y mantiene disponible la transcripción.
El retry del padre reanuda ese hijo, sin crear otro documento ni retranscribir.
La recuperación de un audio legado transcrito comienza en `document_creation`.

Los casos de uso definen sus transiciones y clasificación de fallos. El runner
compartido sigue gestionando leases, heartbeat y presupuesto. Timeouts,
desconexiones, 429 y errores 5xx permiten hasta tres retries por etapa, con demora
10/30/120 segundos, jitter y respeto de `Retry-After`. Evidencia inválida permite
un intento adicional. Fallos permanentes no se reintentan automáticamente;
configuración/credenciales recuperables admiten retry manual. Los adapters de
OpenAI de estos workflows desactivan los retries internos del SDK para no
multiplicar el presupuesto. Los clientes antiguos conservan su configuración.

La configuración semántica queda fijada al aceptar el job: perfil/versión/hash
del prompt y modelos/dimensiones. Los workers resuelven credenciales actuales y
paths desde el workspace registrado, nunca desde un mensaje Rabbit. Cambiar
modelo/perfil requiere otra extracción, y cambiar el modelo de embeddings exige
preparar su esquema en los workspaces antes de procesar esos jobs.

El advisory lock ahora comparte clave por usuario/UUID entre audio y su derivado.
Un token SQL protege progreso y las llamadas revisan el lease antes de iniciar
sus efectos. Una petición remota que continúa después de perder la conexión de
exclusión puede repetirse: se reconcilia mediante IDs y artefactos, sin prometer
una única llamada facturada al proveedor. Si su respuesta nunca se guardó,
el retry puede repetir esa llamada.

Borrar rechaza trabajos activos y deja una marca SQL que impide resucitarlos con
retry. La marca se registra antes del borrado externo: si ese borrado falla, se
puede repetir la operación de borrado, pero no reactivar el procesamiento sobre
un grafo posiblemente eliminado en parte. Los originales no se borran por fallos
de extracción, embeddings, transcripción o entrega.

## Arranque y validación

Rebuild del Compose instala las dependencias y aplica la migración `20261005_04`
antes de arrancar API/workers. Worker y dispatcher esperan RabbitMQ, PostgreSQL
migrado y ArcadeDB con su esquema:

```bash
docker compose --env-file .env.local up -d --build
```

La validación histórica de esta funcionalidad se hizo con servicios aislados;
no acredita el estado de un entorno desplegado.

Pruebas de integración opt-in, siempre con servicios aislados:

```bash
PROCESSING_TEST_DATABASE_URL='postgresql+asyncpg://.../processing_test' \
PROCESSING_TEST_RABBITMQ_URL='amqp://.../processing_test' \
PROCESSING_TEST_ARCADEDB_URL='http://127.0.0.1:55480' \
python -m pytest tests/integration/test_deferred_ingestion.py
```

La suite ejercita aceptación rápida y repetición de requests, conflicto de hash,
claves alias, uploads concurrentes, recuperación de la brecha filesystem/SQL y
raw/metadatos, progreso y checkpoints, commit ambiguo de grafo/vectores,
evidencia inválida, padre/hijo y recuperación de audio legado, retry y borrado,
HTTP 202/200/409/413/503, snapshots, owner y límites de upload.
También corre el dispatcher real con dos workers Taskiq y RabbitMQ/PostgreSQL/
ArcadeDB reales, usando proveedores de IA simulados para no generar costo.
La integración PWA y el stream SSE se describen en [eventos](processing-pwa-events.md).
Los uploads y endpoints de extracción retirados responden `410`.
