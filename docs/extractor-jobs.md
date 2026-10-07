# Trabajos independientes por extractor

Las notas nuevas usan el workflow de documento v4. El coordinador guarda el
original en ArcadeDB y crea un hijo `extractor` v1 por cada especificación aceptada.
El audio sigue transcribiendo y creando el documento antes de entregar su
configuración al coordinador. Los trabajos v2 y v3 anteriores siguen registrados
con su comportamiento original; no se transforman al retomar.

## Responsabilidades y recuperación

`ProcessDocumentExtractors` coordina la persistencia del original, el fork y el
resultado conjunto. `ProcessExtractor` ejecuta y persiste una sola capa. El
extractor mantiene sus modelos, validación y escritura. Sus constructores se
registran por nombre en la composición de workflows; cada constructor decide
sus proveedores y dependencias.

El hijo guarda `extractor_name`, `parent_processing_id`, `extraction_run_id` y
la especificación aceptada. Los IDs de hijo y ejecución se derivan del coordinador
y nombre de capa. Un retry conserva ambos IDs, el profile y los artefactos. Una
solicitud nueva de reprocesamiento crea otro coordinador y nuevas ejecuciones.
No hay un gestor de versiones de resultados.

La revisión Alembic `20261007_07` agrega identidad, índice de padres y unicidad
por padre/capa. Hijos, eventos y outbox se publican en una transacción. Una
interrupción antes del commit no deja ramas parciales. La recuperación retoma el
checkpoint del original y crea los mismos hijos. Una entrega duplicada no vuelve
a crear ni ejecutar un hijo completado.

Cada hijo ejecuta `extraction → persistence → done`. Reanudar en persistencia
lee el artefacto sin construir un proveedor ni repetir extracción. Sus intentos,
leases, fencing y backoff reutilizan el runtime existente.

## Concurrencia y fallos parciales

Los hijos toman un advisory lock compartido del documento y otro exclusivo del
trabajo. Esto permite capas diferentes concurrentes, excluye duplicados y mantiene
bloqueadas las mutaciones exclusivas del original. El borrado también rechaza
trabajos pendientes antes de marcar sus registros como eliminados. Un worker
vencido conserva su exclusión hasta detenerse; su reemplazo no escribe en paralelo.

El coordinador espera hasta que todos sus hijos terminen. Si alguno falla,
responde `extractors_failed` y conserva las capas completadas. Puede ser retryable
cuando existen hijos fallidos recuperables. Reintentar el coordinador retoma sólo
esos hijos; reintentar un hijo permite que las demás ramas sigan trabajando.
Un error permanente no se vuelve automáticamente retryable.

Reintentar el padre de audio puede recuperar una rama del documento sin repetir
transcripción ni las capas exitosas. Un fallo parcial no detiene a sus hermanos.
La concurrencia sigue limitada por workers, conexiones y semáforos de proveedores.

## API y clientes

- `GET /processing/{coordinador}/extractors`: estados de hijos, sólo para su dueño.
- `POST /processing/{hijo}/retry`: retry de esa rama con `Idempotency-Key`.
- `POST /processing/{coordinador}/retry`: retry de hijos fallidos recuperables.
- SSE incluye `extractor_name` y el vínculo al padre; omite configuración y secretos.

Los snapshots de notas conservan el estado del coordinador aunque un hijo sea
más reciente. La PWA sigue mostrando el conjunto como “Procesando extracciones”
y no interpreta un hijo completado como una nota completada. El estado de cada
capa está disponible por API; los controles detallados de la PWA y selección de
extractores, dry run y persistencia diferida por API quedan para la siguiente etapa.
La CLI conserva sus operaciones existentes; las notas nuevas seleccionan emociones.

## Validación

Siete integraciones con PostgreSQL y ArcadeDB aislados cubren dos extractores con
payloads/algoritmos diferentes, concurrencia, exclusión de duplicados, protección
de borrado, errores parciales, retry mientras otra capa ejecuta, fallo permanente,
worker vencido, recuperación de audio, propiedad de la API y rollback de un fork
interrumpido. La segunda capa de conteo es un fixture, no un extractor de producto.
También pasaron las regresiones de ingestión, leases, outbox, eventos y limpieza.
Alembic confirmó que el esquema migrado coincide con los modelos.

Se usaron proveedores determinísticos; no se desplegó ni se evaluó un LLM real.
