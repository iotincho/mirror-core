# Reprocesar notas desde Ajustes

Flujo: **Ajustes → Reprocesar notas → selección con casillas → confirmación**.
El listado muestra las notas guardadas en el servidor, ordenadas por fecha, permite
seleccionar todas y deshabilita las que tienen procesamiento activo. La solicitud
admite entre 1 y 1000 notas. Las notas locales pendientes de envío se sincronizan
antes desde Material.

`POST /v2/documents/reprocess` recibe `{"document_ids": ["<UUID>", "..."]}` y
`Idempotency-Key: <UUID>`. Devuelve HTTP 202 con `items`, los coordinadores de las
notas. Valida toda la selección dentro de los bloqueos de recurso y acepta todos
los trabajos, eventos, outbox y recibo en una única transacción PostgreSQL. Si una
nota no pertenece al workspace, no existe o tiene trabajo activo, no encola ninguna.
Repetir la selección con la misma clave devuelve los mismos trabajos, incluso si
la respuesta original se perdió. La selección se normaliza por UUID; cambiarla
con la misma clave produce conflicto. Los bloqueos del lote usan una sola conexión.

Cada nota usa el workflow y todos los extractores configurados al aceptar la
solicitud. Se omite `document_title` cuando el título ya existe; también el extractor
conserva cualquier título asignado mientras ejecuta. Para notas de audio se usa el
documento derivado de la transcripción existente, sin volver a transcribir.

## Reemplazo y recuperación

Cada extractor es responsable de sus entidades y relaciones. Emociones y embeddings
generan y validan el resultado antes de reemplazar el previo en una transacción de
ArcadeDB propia de la capa. Un fallo conserva el resultado anterior; una extracción
de emociones vacía elimina las emociones anteriores. Se conservan los originales,
metadatos, transcripciones y artefactos durables de ejecución para trazabilidad.
La transacción no abarca diferentes extractores: un fallo parcial conserva las
capas exitosas y muestra el error en el coordinador.

**Reintentar procesamiento** recupera los hijos fallidos recuperables desde sus
checkpoints y no repite capas completadas. **Reprocesar notas** crea coordinadores
y ejecuciones nuevas con configuración actual. El endpoint individual existente
`POST /v2/documents/{id}/processing` conserva su contrato y comparte la política
de configuración del reprocesamiento por lote.

La PWA conserva la identidad de un envío pendiente y el último avance por usuario
en sessionStorage. Un reenvío tras una respuesta perdida conserva la clave y la
selección. Si el almacenamiento no está disponible, la identidad permanece en
memoria mientras esté abierta la pantalla. El avance se actualiza con eventos y
consultas periódicas; el trabajo aceptado continúa en backend aunque cierre la app.
Al cerrar y reabrir el diálogo en la misma sesión se recupera el último lote.

## Validación

Pruebas con PostgreSQL y ArcadeDB aislados cubren lotes mayores que el pool de
conexiones, aceptación atómica, reenvío, cambio de selección, propiedad, exclusión
concurrente, títulos existentes, reemplazo vacío y rollback de emociones pobladas.
Las pruebas React cubren el acceso desde Ajustes, selección de notas antiguas,
confirmación, avance, reintento y recuperación del envío al reabrir. Los proveedores
son determinísticos; no se invoca un LLM real.
