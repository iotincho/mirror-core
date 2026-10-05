# Procesamiento diferido: contratos y diseño

Fecha: 2026-10-05. Etapa 1 del plan acordado. Este documento especifica el
comportamiento a implementar; no describe funcionalidades ya disponibles.

## Objetivo y decisiones

La API confirma la recepción durable del original sin esperar transcripción,
extracción, persistencia en el grafo ni embeddings. El procesamiento continúa
con la PWA cerrada y puede retomarse después de una caída.

- Taskiq ejecuta tasks async en containers independientes; RabbitMQ transporta
  las solicitudes. PostgreSQL conserva procesamientos, historial y outbox.
- Cada use case posee sus transiciones, checkpoints y clasificación de errores.
  La task es un adaptador que recibe `processing_id`, construye las dependencias
  y llama a `await use_case.execute(processing_id)`.
- Los casos de uso dependen de puertos propios, sin importar Taskiq, RabbitMQ,
  FastAPI ni modelos SQLAlchemy. No incorporamos un framework de state machines
  ni una clase base que fuerce todos los workflows a tener las mismas etapas.
- SSE comunica cambios a la PWA; no controla la ejecución ni sustituye la
  consulta de estado durable. La conexión puede interrumpirse sin perder trabajo.
- La entrega admite duplicados. No se promete ejecución exactamente una vez ni
  ausencia de llamadas repetidas a proveedores después de una caída ambigua.
- El despliegue inicial comparte el volumen de originales entre API y workers
  en un host. Distribuir workers entre hosts requiere almacenamiento compartido
  u object storage antes de habilitar ese despliegue.

## Punto de partida

`POST /documents` y `/documents/files` llaman a `IngestAndExtractDocument` y
esperan todo el pipeline. Audio responde `202` y usa `BackgroundTasks`; la
transcripción terminada se convierte en documento con el mismo UUID del audio.
Los originales y extracciones se almacenan en archivos por workspace.
PostgreSQL registra usuarios y workspaces; ArcadeDB almacena el grafo.

El orden obligatorio actual es extracción validada → grafo → embeddings de
claims y documento. `ExtractionRun.status=completed` significa que terminó la
extracción, no todo el procesamiento. `AudioNote.status=completed` actualmente
significa transcripción terminada; tampoco prueba que el documento sea buscable.
Constelación y descubrimiento de links quedan fuera del pipeline automático.

## Fronteras y contratos de aplicación

| Componente propuesto | Responsabilidad |
| --- | --- |
| `SubmitDocument`, `SubmitAudioNote` | Validar, almacenar original, registrar ejecución y outbox, devolver aceptación |
| `ProcessDocument` | Ejecutar y retomar extracción, grafo y embeddings; controlar sus transiciones |
| `ProcessAudioNote` | Ejecutar y retomar transcripción, creación del documento y coordinación con el procesamiento hijo |
| `RetryProcessing` | Resolver workflow propietario y solicitar la transición de reintento definida por él |
| `GetProcessing`, `ListProcessing` | Consultas limitadas al workspace autenticado |
| `ProcessingRepository` | Crear, consultar y guardar con versión esperada; adquirir/renovar/liberar lease |
| `ProcessingUnitOfWork` | Confirmar cambios, historial y outbox juntos en PostgreSQL |
| `ArtifactStore` | Almacenar/consultar originales y checkpoints con identidades estables y escritura atómica |
| Dispatcher | Reclamar outbox, publicar mensaje y registrar confirmación; sin decidir transiciones del workflow |
| Reconciliador | Detectar originales huérfanos y leases vencidos; invocar recuperación del workflow propietario |
| Adaptadores Taskiq/SSE | Invocar use cases o entregar eventos; sin reglas de negocio |

Los métodos de I/O de estos puertos serán async. Validación de evidencia y reglas
de transición pueden seguir siendo funciones puras síncronas. Los clientes de
proveedores y grafo deben migrar a async en etapa 2; archivos bloqueantes se
ejecutan fuera del event loop. Cada ejecución tiene su propia sesión de DB y
clientes con ciclo de vida definido; no comparte una transacción ArcadeDB entre
tareas concurrentes.

Agregar otro workflow exige registrar su use case y versión, definir sus etapas
y recuperación. Reutiliza persistencia, leases, outbox y eventos. Un mensaje con
workflow/versión desconocidos no se ejecuta con reglas de otro workflow.

## Registro durable

Contrato lógico de `ProcessingRecord` (las migraciones se implementan en etapa 3):

| Campo | Contrato |
| --- | --- |
| `id` | UUID del procesamiento; distinto del ID del documento y del task ID |
| `user_id` | Propietario y clave de workspace actual (`user_graphs.user_id`) |
| `workflow`, `workflow_version` | `document` o `audio`, versión inicial `1`; reglas fijadas al crear |
| `resource_kind`, `resource_id` | Original de texto o audio, identificado dentro del workspace |
| `status` | `queued`, `running`, `waiting`, `retrying`, `failed`, `completed` |
| `stage` | Etapa definida por el workflow; se conserva al fallar |
| `document_id`, `extraction_run_id` | Referencias a resultados persistidos, inicialmente opcionales |
| `parent_processing_id`, `child_processing_id` | Coordinación audio/documento; un hijo document por audio |
| `configuration` | Perfil, versiones de prompt/esquema y especificación de modelos/embeddings fijados; sin secretos |
| `checkpoints` | Referencias, hashes y resultados verificables por etapa; sin bytes de audio ni texto completo en SQL |
| `stage_attempt`, `total_attempts` | Contadores; un delivery duplicado descartado no consume intento |
| `error_code`, `retryable`, `next_attempt_at` | Error seguro y decisión de recuperación del use case |
| `version`, `lease_owner`, `lease_expires_at`, `fencing_token` | Control de concurrencia y recuperación |
| `created_at`, `updated_at`, `started_at`, `completed_at` | Fechas UTC; `authored_at` pertenece al original |

`waiting` se usa cuando el audio espera al hijo; no mantiene ocupado un worker.
`failed` significa intentos agotados o error que requiere intervención.
`completed` exige todos los checkpoints obligatorios; no se deduce de la
existencia de un archivo, un run ni un task result.

Cada cambio guarda un `ProcessingEvent` en la misma transacción: `event_id`,
`processing_id`, `version`, `user_id`, estado, etapa, error seguro y fecha.
La outbox contiene ID propio, tipo de mensaje, processing ID, generación de
ejecución, fecha de entrega, intentos y confirmación. Los mensajes de RabbitMQ
no contienen contenido, paths arbitrarios, cookies ni credenciales.

## Máquinas de estados

Se separa `status` operativo de `stage` para expresar espera/reintento sin perder
la etapa pendiente. Cada use case valida las combinaciones permitidas y realiza
las transiciones mediante la unidad de trabajo.

### ProcessDocument v1

| Estado/etapa | Condición para avanzar | Destino |
| --- | --- | --- |
| `queued / extraction` | Lease adquirido y original disponible | `running / extraction` |
| `running / extraction` | Resultado validado y run persistido | `running / graph` |
| `running / graph` | Commit del grafo confirmado o reconciliado | `running / claim_embeddings` |
| `running / claim_embeddings` | Embeddings de todos los claims persistidos; cero claims es checkpoint válido | `running / document_embedding` |
| `running / document_embedding` | Embedding del documento persistido | `completed / done` |

Cada transición persiste el checkpoint antes de ejecutar la siguiente etapa.
El título generado se aplica idempotentemente desde el run validado; una caída
al actualizar el título no exige otra extracción.

### ProcessAudioNote v1

| Estado/etapa | Condición para avanzar | Destino |
| --- | --- | --- |
| `queued / transcription` | Lease adquirido y audio disponible | `running / transcription` |
| `running / transcription` | Transcripción literal y procedencia persistidas | `running / document_creation` |
| `running / document_creation` | Documento con UUID del audio almacenado y vinculado | `waiting / document_processing` |
| `waiting / document_processing` | Hijo `ProcessDocument` completado | `completed / done` |
| `waiting / document_processing` | Hijo falló definitivamente | `failed / document_processing` |

Al pasar a `waiting`, crear/vincular hijo y outbox es una transacción SQL. Si ya
existe el hijo se reutiliza. `ProcessAudioNote` no llama inline a `ProcessDocument`
ni espera su resultado dentro del worker: el cambio del hijo genera una solicitud
de continuación al padre mediante outbox. El reconciliador cubre continuaciones
perdidas. Un evento antiguo no hace retroceder al padre.

El padre puede reintentarse delegando al hijo fallido, sin retranscribir ni crear
otro documento. Si el hijo está activo, se devuelve el estado actual sin otra
ejecución. Si el hijo ya terminó, el padre reconcilia y completa.

### Fallos y transiciones comunes, aplicadas por cada use case

- Fallo temporal en etapa ejecutable: `running → retrying`, misma etapa, con
  `next_attempt_at`; al llegar la fecha, el nuevo intento adquiere lease y corre.
- Fallo permanente o agotamiento: `running → failed`, misma etapa/checkpoints.
- Reintento manual elegible: `failed → queued`, primera etapa sin checkpoint;
  reinicia el presupuesto de esa etapa y conserva historial e intentos totales.
- Lease vencido: reconciliar efectos guardados antes de reprogramar la etapa;
  jamás marcar completo sólo por el vencimiento ni mantener `running` indefinido.
- Reentrega en ejecución activa o estado terminal: no ejecutar efectos duplicados.
- `completed` es terminal. Reextraer crea otro procesamiento, no modifica éste.
- Para el MVP, borrar un documento con procesamiento propio o padre/hijo activo
  devuelve `409 processing_active`. Cancelación y borrado concurrente quedan fuera
  del alcance; un borrado posterior debe impedir reintentar procesamientos fallidos.

## Checkpoints, concurrencia y efectos externos

Una transacción PostgreSQL adquiere lease y aumenta fencing token. Heartbeat
renueva el lease; la transacción no permanece abierta durante llamadas a modelos.
Cada actualización exige versión y token vigentes. Si se pierde el lease, el
worker deja de iniciar etapas y sus escrituras de estado se rechazan.

Los efectos externos también requieren protección: IDs deterministas para run,
grafo y embeddings, creación exclusiva de artefactos y upserts idempotentes.
No se considera que el fencing SQL por sí solo proteja archivos o ArcadeDB.
El adaptador debe serializar o rechazar efectos obsoletos cuando compitan con
otro intento. La etapa 3 debe probar específicamente ese escenario.

Antes de una llamada se registra identidad del intento/run. Después se almacena
el resultado con su hash/configuración. Si la caída ocurrió después de guardar
el artefacto pero antes del checkpoint SQL, se descubre y valida ese artefacto
antes de repetir. Si el proveedor respondió pero nada se guardó, puede repetirse
la llamada y su costo; registrar esa incertidumbre en el historial.

Grafo y embeddings no comparten transacción con PostgreSQL. Una respuesta de
commit ambigua se reconcilia por identidades y resultados esperados; reintentar
grafo usa el mismo run. Embeddings de claims y documento tienen checkpoints
separados y reutilizan vectores guardados cuando sea posible.

## Política de errores y entrega

El use case clasifica errores; los adaptadores conservan la causa técnica sin
exponer contenido privado o tracebacks al cliente.

| Categoría | Decisión inicial |
| --- | --- |
| Timeout, desconexión, proveedor 429/5xx, DB/grafo temporalmente caídos | Reintentar etapa con backoff y respetar `Retry-After` |
| Evidencia/esquema del modelo inválidos | Un nuevo intento del modelo; luego fallo visible |
| Archivo/formato/tamaño inválido | Rechazar antes de aceptación |
| Original ausente, configuración inválida o permisos del proveedor | Fallo visible; corregir causa antes de retry |
| Workspace suspendido | No ejecutar efectos; fallo `workspace_unavailable`, retry sólo tras reactivación |

Presupuesto inicial: tres reintentos automáticos por etapa temporal (cuatro
intentos totales), esperas de 10, 30 y 120 segundos con jitter. Valores configurables;
validación empírica de timeouts y concurrencia en etapas 2/6.

Los reintentos se programan mediante outbox con fecha disponible; Taskiq no agrega
otro retry middleware independiente. Fallos de infraestructura anteriores a la
invocación deben recuperarse mediante redelivery/reconciliación.

RabbitMQ: cola durable, mensajes persistentes, confirmación de publicación y
acknowledgement después de confirmar estado/checkpoint o reintento durable.
Error al persistir deja el mensaje sin ack para recuperación. Crash antes del ack
puede producir duplicado. Publicar y marcar la outbox tampoco es atómico: el
dispatcher tolera republicación. Mensajes inválidos o workflow desconocido se
aislan para inspección sin entrar en un bucle infinito de reentrega.

## Aceptación e idempotencia del upload

Todos los POST mutantes nuevos exigen `Idempotency-Key` (UUID generado y guardado
por la PWA antes del primer envío). Scope: propietario + operación + clave.
Hash de request: bytes originales, tipo, campos semánticos, IDs explícitos y
metadatos; no depende del boundary multipart. Misma clave y mismo hash devuelve
los mismos IDs y el estado actual; misma clave con otro contenido devuelve `409`.
Nueva clave con un ID de original existente sólo puede asociarse a su ejecución
original si hash y metadatos coinciden. No deduplicar notas distintas sólo por texto.

Para cerrar la brecha filesystem/SQL, `Submit*` reserva primero un registro de
recepción idempotente en SQL (sin hacerlo visible como procesamiento aceptado),
guarda el original atómicamente y confirma `ProcessingRecord + outbox + recepción`
en una transacción. El manifiesto del artefacto conserva propietario, clave,
hash y referencias suficientes para reconciliar. Un registro incompleto no
dispara procesamiento. Subidas simultáneas de la misma clave tienen un único
propietario de recepción; la otra recibe `409 upload_in_progress` y puede reintentar.

Respuesta `202` sólo tras original durable y transacción confirmada. Si falla SQL,
devolver `503`, conservar el original y permitir retry con la misma clave. El
reconciliador completa recepciones cuyo artefacto ya está íntegro; nunca publica
artefactos temporales/incompletos. Si RabbitMQ cae después del commit, mantener
`202 queued`: la outbox ya garantiza una intención recuperable.

## Contratos HTTP propuestos (rutas bajo /api en despliegue)

| Endpoint | Respuesta y semántica |
| --- | --- |
| `POST /documents` | JSON actual + Idempotency-Key; `202 AcceptedDocument` |
| `POST /documents/files` | Multipart actual + Idempotency-Key; `202 AcceptedDocument` |
| `POST /audio-notes` | Multipart actual + Idempotency-Key; `202 AcceptedAudio` |
| `GET /processing/{id}` | `200 ProcessingResponse`, limitado al propietario |
| `GET /processing?active=true` | Paginado por cursor; queued/running/waiting/retrying, orden estable por fecha e ID |
| `POST /processing/{id}/retry` | Idempotency-Key; `202` si solicita retry, `200` si ya activo/completo; `409` si no elegible |
| `POST /documents/{id}/extractions` | Perfil + Idempotency-Key; `202`, nueva ejecución deliberada; `409` si otra ejecución del documento está activa |
| `POST /audio-notes/{id}/documents` | Compatibilidad: delega recuperación al workflow; no usa BackgroundTasks |
| `GET /events` | SSE autenticado, eventos sólo del workspace actual |

`AcceptedDocument`: `document: DocumentResponse`, `processing: ProcessingResponse`.
`AcceptedAudio`: `audio_note: AudioNoteResponse`, `processing: ProcessingResponse`.
Respuesta incluye header `Location: /api/processing/{id}`. El título puede ser
`null` inicialmente. Repetir un upload completado devuelve `200` con los mismos
IDs; pendiente devuelve `202`. Ningún `409` se interpreta como procesamiento completo.

`ProcessingResponse` ejemplo:

```json
{
  "id": "a84d8001-0286-4ab9-b98e-e7c964065724",
  "workflow": "document",
  "workflow_version": 1,
  "resource_kind": "document",
  "resource_id": "e3c0c6e6-35f9-48a4-a9a3-d06c0b639289",
  "document_id": "e3c0c6e6-35f9-48a4-a9a3-d06c0b639289",
  "extraction_run_id": null,
  "parent_processing_id": null,
  "child_processing_id": null,
  "status": "queued",
  "stage": "extraction",
  "version": 1,
  "stage_attempt": 0,
  "error": null,
  "next_attempt_at": null,
  "created_at": "2026-10-05T15:00:00Z",
  "updated_at": "2026-10-05T15:00:00Z",
  "completed_at": null
}
```

`error`, si existe: `{code, message, retryable}`; sin traceback ni secretos.
No exponer lease ni configuración privada. Recursos ajenos devuelven `404`.
`AudioNote.status` sigue describiendo transcripción durante la transición;
`processing.status` es la autoridad del flujo completo. `document_id` se publica
al guardar el documento, aunque su procesamiento no haya terminado.
Listados/detalles de originales incorporarán el procesamiento actual para que
failed/completed también se recuperen al abrir la app, no sólo la lista activa.

Estos cambios rompen la respuesta síncrona actual y requieren coordinación con
PWA en etapas 4/5. No activar el contrato nuevo para clientes antiguos hasta
desplegar la adaptación o proveer una ruta versionada temporal.

## Eventos y recuperación de interfaz

SSE emite `event: processing.updated`, `id: <event_id>` y `data` con la misma
proyección `ProcessingResponse`. Un evento actualiza sólo si su versión supera
la versión local. Se conserva el historial por un plazo configurable (inicial:
7 días); `Last-Event-ID` permite replay. Cursor vencido genera `processing.resync`
y obliga a consultar snapshot. Heartbeats no representan progreso.

Al abrir/reconectar, establecer stream y recuperar snapshots aplicando versiones
para cerrar carreras entre ambos. Sin SSE, el servidor sigue trabajando y la
próxima apertura recupera el resultado. La interfaz distingue sincronización del
original de procesamiento. Conserva Blob/transcripción locales y ofrece retry;
no exige reupload cuando el original remoto existe.

## Escenarios de aceptación para las etapas siguientes

| Escenario | Resultado exigido |
| --- | --- |
| Nota válida | 202 tras guardar; worker termina extracción/grafo/ambos embeddings |
| Audio válido | 202; transcripción preservada, documento vinculado, hijo completado y padre completado |
| PWA cerrada o SSE desconectado | Procesamiento continúa; snapshot devuelve resultado al volver |
| Respuesta de upload perdida | Misma clave devuelve original/procesamiento existentes |
| Misma clave con otros bytes | 409 sin sobrescribir material |
| Dos uploads/retries simultáneos | Una recepción/ejecución efectiva; IDs estables |
| Caída tras guardar original antes de commit SQL | Recepción reconciliada o retry reutiliza artefacto; ninguna pérdida |
| RabbitMQ caído al aceptar | 202 queued; outbox entrega al recuperarse |
| Publicación confirmada y crash del dispatcher | Republicación tolerada sin efectos duplicados |
| Worker cae en cualquier etapa | Lease/reentrega recuperan primera etapa sin checkpoint válido |
| Lease vence con worker viejo aún vivo | Worker obsoleto no pisa estado ni resultados del nuevo intento |
| Transcripción persistida antes de crash | Se reutiliza literal; no retranscribe |
| Extracción válida y grafo falla | Reintenta el mismo run; no vuelve al LLM |
| Commit de grafo ambiguo | Reconcilia identidades antes de repetir; sin duplicados |
| Claims embebidos y embedding de documento falla | Retoma sólo embedding pendiente |
| Hijo finaliza y padre no recibe continuación | Reconciliador completa padre; no mantiene worker esperando |
| Error permanente o intentos agotados | Failed visible con causa segura; original conservado |
| Usuario consulta/reintenta ID ajeno | 404; sin acceso a estado, archivo ni grafo |
| Workspace suspendido después de enqueue | Worker no procesa; recuperación exige workspace activo |
| Borrado mientras procesa | 409; no reaparece material después del borrado |
| Reextracción deliberada | Nueva ejecución/run, historial previo conservado |
| Evento duplicado/antiguo o cursor vencido | Sin retroceso de estado; resync cuando corresponde |

## Secuencia de implementación y cierre de etapa 1

1. Contratos y máquinas de estados: este diseño, sin modificaciones de runtime.
2. Migración async del pipeline existente y pruebas de equivalencia.
3. Persistencia, outbox, Taskiq/RabbitMQ, leases y recuperación.
4. Uploads diferidos y workflows de nota/audio con contratos HTTP nuevos.
5. PWA, SSE, snapshots y recuperación de originales locales.
6. Compose, operación, validación desplegada y ajuste de concurrencia.

Etapa 1 deja definidos estados/transiciones, contratos HTTP/aplicación,
idempotencia, checkpoints, errores y criterios de aceptación. Las etapas 2/3
deben concretar librerías/configuración de ack, publicación y fencing, y medir
timeouts y límites. No incluye migraciones, endpoints, tasks ni infraestructura
ejecutable; no se afirma validación de runtime o despliegue.
