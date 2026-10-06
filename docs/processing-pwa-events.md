# Etapa 5: PWA y eventos de procesamiento

La PWA utiliza uploads diferidos v2, conserva las claves de idempotencia en
IndexedDB y recibe estados por un único SSE mientras existe una sesión.
Captura, exploración y constelación comparten esa suscripción. No depende de
mantener una pantalla abierta ni de consultar el procesamiento cada cinco segundos.

## Contrato del stream

`GET /events` valida la cookie `el_espejo_session` en PostgreSQL: token vigente,
usuario activo y workspace activo de la instancia configurada. Resuelve y cierra
la sesión SQL antes de iniciar el stream; no abre una conexión a ArcadeDB.
Revalida cookie/workspace cada 15 segundos. Logout cierra inmediatamente la
suscripción en la PWA; una revocación externa termina el stream en el próximo
heartbeat, con `session.expired`.

- `event: processing.updated`: `data` es la misma proyección pública que
  `/processing/{id}`, congelada al producir la transición. `id` es un cursor
  de entrega durable. Configuración, credenciales y leases quedan fuera.
- `event: processing.resync`: requiere consultar snapshots, por ejemplo al
  conectar sin cursor o con un cursor fuera de la ventana de replay.
- `event: processing.unavailable`: workspace no disponible durante la conexión;
  termina el stream y EventSource reintenta, sin invalidar una sesión vigente.
- Comentario `: heartbeat` cada 15 segundos; no cambia estados ni versiones.
- `retry: 3000` solicita reconexión después de 3 segundos.

El servidor respeta `Last-Event-ID`. Para nuevas instancias de EventSource,
`?after=<cursor>` permite restaurar el cursor guardado por usuario en
sessionStorage; la cabecera tiene prioridad. Un cursor negativo o inválido
produce 422. Sólo se entregan eventos del usuario autenticado. La ventana de
replay es de siete días; un cursor viejo/futuro vuelve a snapshots.

La respuesta incluye `Cache-Control: no-cache, no-transform` y
`X-Accel-Buffering: no`. El proxy Nginx existente respeta esa cabecera y los
heartbeats mantienen actividad dentro de su timeout. No se cambiaron ni se
validaron instancias de proxy desplegadas. Un proxy que ignore esa cabecera
necesita desactivar buffering para `/api/events` en la etapa de despliegue.

## Orden durable

La migración `20261005_05` agrega `processing_events.payload` y
`processing_deliveries`. La proyección se escribe con estado/outbox en la misma
transacción de la transición.

Los IDs originales de eventos se asignan antes del commit: dos transacciones
pueden confirmar en orden inverso. Publicar directamente `id > cursor` perdería
el evento con ID menor que confirma tarde. Una transacción independiente,
serializada con advisory lock global y sin bloquear records, publica únicamente
eventos ya confirmados y les asigna un cursor de entrega. Esto funciona con
múltiples workers/API containers. La PWA aplica únicamente versiones mayores
por workflow y evita reemplazar un workflow nuevo con uno anterior.

El stream lee PostgreSQL cada segundo en sesiones cortas, publica hasta 500
eventos por lote y entrega hasta 100 por lote. Este polling ocurre en el servidor;
no requiere polling del frontend ni comunicación directa con RabbitMQ. La
publicación funciona incluso si la PWA se abre luego de terminar el procesamiento.
Los eventos anteriores a la migración no tenían payload: se recuperan por
snapshots. El replay filtra la ventana temporal; la purga física/optimización y
la medición con muchas conexiones quedan para operación en la etapa 6.

## PWA y recuperación

IndexedDB v5 agrega workflow/versión, índice de procesamiento y claves para
upload, reupload y acciones. No elimina originales ni transcripciones. Una
subida en `syncing` se vuelve pendiente al abrir la app, para repetir con la
misma clave. La clave se reserva transaccionalmente antes del HTTP; respuestas
perdidas y 503 conservan esa identidad. Un 409 no se toma como éxito.

La conexión se abre antes de conciliar snapshots. Cada conexión/reconexión y
`processing.resync` consulta documentos locales sincronizados, incluidos los
terminales. Los eventos se aplican en secuencia y el storage verifica la versión
transaccionalmente; un worker muy rápido se reconcilia después de aceptar el
upload. Terminar la transcripción o crear el documento no marca completo un
workflow de audio que espera a su hijo.

Una sesión distinta invalida respuestas pendientes de sincronización. La
reconciliación también verifica que la identidad remota/workflow siga siendo
la misma antes de guardar detalles. Las notas conservan títulos obtenidos al
finalizar; los audios conservan Blob, transcripción y opción de descargar backup.
Reintentar un fallo recuperable retoma el mismo workflow; reprocesar uno terminado
solicita una extracción nueva. Reupload es una acción deliberada independiente
y sólo reemplaza la identidad remota después de aceptar el nuevo envío.

Los endpoints legacy siguen disponibles para clientes anteriores. La PWA nueva
requiere el core con esta migración; publicar sólo la PWA antes que el backend
no permite utilizar este contrato.

## Validación

- Suite backend completa con PostgreSQL aislado: 154 passed, 5 skipped. Los skips
  son pruebas opt-in que requieren otros servicios/credenciales; las pruebas de
  eventos se ejecutaron todas.
- SSE con servidor Uvicorn y HTTP real: 401 sin cookie, replay de payload histórico,
  cursor inicial/vencido, revocación/expiración de cookie, aislamiento por usuario,
  publicación concurrente y commit tardío con cursor posterior.
- Migración nueva: upgrade, downgrade/upgrade y `alembic check` sin diferencias.
- PWA: build de producción, lint y 38 pruebas de recuperación, títulos,
  sincronización, fechas y constelación.
- Los tests de storage ejecutan funciones reales con un adaptador Dexie en memoria.
  El navegador integrado no estuvo disponible: no se verificaron visualmente la
  interfaz ni IndexedDB en navegador. Tampoco hubo despliegue ni llamadas OpenAI.

Para repetir backend:

```sh
DATABASE_URL=postgresql+asyncpg://... python -m alembic upgrade head
PROCESSING_TEST_DATABASE_URL=postgresql+asyncpg://... python -m pytest
```

Para repetir PWA, desde `mirror-pwa`:

```sh
npm run build
npm run lint
node --test tests/*.test.mjs src/features/constellation/model.test.mjs
```
