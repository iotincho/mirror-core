# Journals · Contratos y persistencia

Estado al 3 de noviembre de 2026: etapas 1–4 implementadas localmente. Núcleo,
aplicación, persistencia PostgreSQL, reconciliación y pregunta diaria compuestos.
Requiere migración `20261103_25`; `JOURNALS_ENABLED=false` por defecto. Texto/audio
conservan pertenencia histórica. Sin endpoints de gestión de Journals ni interfaz.
No habilitado ni desplegado.
Ver [diseño de producto](journals-design.md) y
[plan de implementación](journals-implementation-plan.md).

## Responsabilidad y contratos ejecutables

Journals posee definiciones versionadas, recorridos, etapas y sus reglas temporales.
No crea notas, invitaciones o trabajos. Su núcleo depende sólo de biblioteca
estándar y Pydantic; no importa exteriorización, aplicación o infraestructura.

- [Modelos](../src/core/journals/models.py): `JournalTemplate`, `StageDefinition`,
  `ScheduledStage`, `JournalRun`, `StageCatalog` e `IntentionVersion` inmutables.
- [Reglas](../src/core/journals/rules.py): activación, resolución de etapa,
  ajustes, pausa, reanudación, avance explícito, cierre y edición de intención.
- [Calendario](../src/core/journals/calendar.py): fronteras locales e instantes UTC.
- [Contratos de aplicación](../src/core/journals/contracts.py): entradas tipadas,
  vistas públicas/administrativas, contexto de pregunta y referencias de captura.
- [Fixture JSON](../tests/fixtures/journals_contract_v1.json): template de cuatro
  etapas, activación, fronteras esperadas, vista pública y solicitudes de ejemplo.
- [Pruebas](../tests/test_journals_contracts.py): comportamiento e incompatibilidades
  sin servicios ni proveedores. Los modelos ofrecen `model_json_schema()`.
- [Puertos](../src/core/journals/ports.py),
  [casos de uso](../src/use_cases/journals/manage.py) y
  [consultas](../src/use_cases/journals/query.py): unidades de trabajo por propietario.
- [Persistencia](../src/adapters/storage/postgres/journals.py) y
  [migración](../migrations/versions/20261103_23_journals.py): revisiones y recibos atómicos.

Los contratos de aplicación no son schemas HTTP publicados automáticamente.
Los adaptadores de acceso traducen sus propios schemas; la referencia de captura
tiene representación HTTP propia, sin exponer directamente modelos internos.
`ActivateRun` no contiene propietario: la aplicación resolverá el usuario destino
desde acceso administrativo validado. Las operaciones públicas resolverán sesión
y workspace; este núcleo no autentica solicitudes.

## Definiciones y revisiones

El template identifica versión y etapas por una clave estable, con nombre,
objetivo, indicaciones y duración entera de uno a 365 días. Un template/recorrido
contiene entre una y 52 etapas, sin claves duplicadas.

Activar copia la definición. Los IDs de etapa se derivan de recorrido y clave;
dos instancias del mismo template tienen etapas con identidades distintas.
Modificar un template no modifica una instancia previa.

Cada mutación devuelve un `JournalRun` nuevo, con revisión incrementada, fecha,
tipo de cambio y origen `administration`, `user` o `calendar`. No se atribuye una
identidad ficticia a un operador LAN. El llamador debe conservar las revisiones
previas; el núcleo no mantiene una colección global ni escribe su historia.

Las mutaciones exigen `expected_revision` y rechazan reloj anterior a `updated_at`.
La escritura condicional en PostgreSQL comprueba la revisión y conserva la anterior.
Un índice parcial exige un único recorrido con estado persistido `active` por cuenta.
Si ese recorrido ya venció, la activación lo completa y libera el lugar dentro de
su misma transacción, sin esperar al próximo ciclo del dispatcher.

## Calendario adoptado para esta etapa

- El inicio es inmediato y exige fecha con zona. Se conserva una zona IANA por
  recorrido, independiente de futuros cambios de preferencias de notificación.
- La primera etapa comienza al activar y termina a medianoche local de la fecha
  de inicio más su duración. Un inicio a mitad del día deja un primer día parcial.
  Las siguientes etapas son contiguas y avanzan en días de calendario locales.
- Las fronteras incluyen inicio y excluyen fin. Una hora ambigua usa el primer
  instante; una hora inexistente avanza al primer minuto local válido. Los instantes
  se normalizan a UTC. No se equipara un día de calendario con veinticuatro horas.
- `stage_at` resuelve directamente la etapa para un instante, sin mutar el snapshot.
  Puede saltar varias etapas tras una caída del dispatcher. No depende de respuestas.
  El contexto de pregunta se resuelve para su horario programado, incluso si se
  prepara antes del inicio de esa etapa.
- Pausar congela el tiempo restante. Reanudar agrega el intervalo transcurrido
  en UTC al final de la etapa pausada y a las fronteras futuras; su inicio y las
  etapas ya completadas no cambian. Después de una pausa, las fronteras pueden
  dejar de ser medianoche. Esta política conserva el tiempo restante exacto,
  incluso si la pausa cruza un cambio estacional.
- Los ajustes se permiten en activo o pausado. En pausa, el instante de referencia
  es `paused_at`. La lista de etapas restantes comienza con la actual; se pueden
  reordenar, quitar o agregar futuras sin reintroducir una etapa completada.
- Cambiar sólo objetivos o indicaciones conserva las fechas. Cambiar duración
  agrega/resta días de calendario al final vigente y recalcula el tramo futuro
  afectado. Si el nuevo final alcanzaría o precedería el instante de referencia,
  se exige la acción explícita de avanzar.
- Avanzar termina la etapa actual en ese instante y comienza la siguiente allí;
  sus fronteras futuras se calculan por días de calendario desde ese nuevo inicio.
  No se admite avance en el instante exacto de inicio porque crearía un intervalo
  vacío. Las revisiones anteriores conservan sus fechas originales.
- Al finalizar la última etapa, `effective_status` y la vista pública muestran
  `completed` sin esperar al dispatcher. `reconcile` materializa esa finalización
  una sola vez, conservando como fin el instante programado y como `updated_at` el
  de reconciliación. Un avance explícito de la última etapa también completa.

Los estados son `active`, `paused`, `completed`, `closed`. Pausados y terminados no
conducen preguntas. Cerrar conserva todas las etapas en el snapshot. El modo libre
devuelto por el contrato es una selección de contexto, no la emisión de otra
invitación: el publicador conserva la unicidad diaria y las preferencias.
Completar preparación no activa integración ni afirma que ocurrió una experiencia.

## Contexto público, administrativo y de generación

| Contrato | Contenido | Excluye |
| --- | --- | --- |
| `PublicRunView` | Nombre, propósito, template/versiones, revisión, zona, estado efectivo, etapas visibles y referencia de captura actual. | Propietario, indicaciones internas e intención personal. |
| `AdministrativeRunView` | Vista del recorrido, configuración, catálogos y claves de etapas que requieren revisión del catálogo. | Entradas e intención personal. |
| `JournalQuestionContext` | Propietario ya resuelto, referencia, propósito, indicaciones, objetivo de etapa, intención versionada y catálogo compatible. | Agregado completo, notas o referencias de evidencia no verificadas. |
| `FreeQuestionContext` | Modo libre y propietario resuelto. | Pertenencia implícita a un journal. |

La intención se representa aparte en `IntentionVersion`, con texto opcional,
versión y fecha. Borrarla crea otra versión con `text: null`. Su edición también
incrementa la revisión del recorrido para invalidar preparaciones futuras. El
contexto interno anterior conserva la intención que conocía; la configuración
administrativa no empieza a recibirla por haberse editado.

`QueryJournals.resolve` implementa el puerto `QuestionContextResolver`, inyectado
al generador de invitaciones. Los campos sensibles se
excluyen de `repr` y los errores de validación ocultan inputs en su representación
textual. Eso no vuelve seguro registrar `model_dump()`, `.errors()` o payloads;
los adaptadores deberán emitir sólo códigos y correlación técnica.

## Persistencia y garantías transaccionales de etapa 2

| Tabla | Autoridad |
| --- | --- |
| `journal_templates` | Definición inmutable por ID y versión. Instalar la misma definición es idempotente; cambiarla con la misma versión devuelve conflicto. |
| `journal_runs` | Índice actual: dueño, template/versiones, revisión vigente, estado, fecha final y actualización. |
| `journal_run_revisions` | Snapshot completo e inmutable de cada revisión, con configuración, etapas e intención versionada. |
| `journal_stage_revisions` | Pertenencia relacional por dueño/recorrido/revisión/etapa, posición e intervalos. Los textos permanecen en el snapshot. |
| `journal_mutation_receipts` | Recibo por dueño y clave idempotente: operación, hash de solicitud, revisión resultante y fecha. No guarda textos de intención o notas. |

La intención no tiene otra tabla de historia: vive en los snapshots versionados.
Así la revisión fijada por una pregunta identifica también la intención que conocía.
Las claves foráneas compuestas impiden mezclar dueños al vincular etapas o recibos.
El puntero a la revisión actual es diferido hasta commit: no se puede confirmar
un recorrido sin su snapshot. Índices, revisión y recibo se escriben juntos.
La tabla de entradas y su integración de aceptación se agregan en etapa 3.

`ManageJournals` coordina activar, ajustar, pausar, reanudar, avanzar, cerrar y
editar intención. Devuelve un recibo técnico, que se confirma después de salir
exitosamente de la unidad transaccional. No devuelve texto privado como respuesta
administrativa. Las vistas se consultan por separado. Las lecturas de intención
son una operación específica para el propietario; no se agregan a la vista admin.

Antes de operar se verifica que la cuenta exista, esté habilitada y tenga workspace
activo. La identidad entregada al caso de uso debe provenir del acceso verificado:
estos métodos no son una API para elegir libremente dueño desde el cliente público.
SQL queda acotado al propietario y sólo devuelve modelos del núcleo o hechos tipados.

El orden de mutación es: comprobar acceso, tomar el lock de la fila de preferencias
de invitación, consultar el recibo, resolver el estado vigente y aplicar la regla,
guardar revisión/índices y recibo, confirmar. Se reutiliza el lock existente de
exteriorización sin cambiar `enabled`, horario, zona ni `updated_at`. Si faltaba
la fila se crea con preferencias deshabilitadas. No se adquieren locks de recursos
o de recorrido antes del lock compartido por cuenta.

La clave idempotente es global entre operaciones de Journals para ese propietario.
El hash `journal-mutation/1` incluye acción, recorrido y comando normalizado, sin
el reloj ni IDs generados durante el intento. Un replay idéntico devuelve el
recibo original, incluso si hubo cambios posteriores; otra solicitud con esa clave
devuelve `journal_idempotency_conflict`. Los recibos no vencen independientemente
de su historia. Un fallo antes de commit deja todo en rollback; un commit confirmado
con respuesta perdida se recupera repitiendo la clave.

Errores SQL o snapshots inválidos se traducen a `JournalStorageUnavailable`
con código `journal_storage_unavailable`, sin payloads ni mensajes de base de datos.
Una revisión obsoleta devuelve `journal_revision_conflict`. No se añaden retries
automáticos: el cliente futuro conservará su clave para recuperar una respuesta
ambigua. El adaptador verifica también que la identidad dentro del snapshot coincida
con las columnas de alcance, y rechaza representaciones corruptas.

El campo opcional `AdjustRun.catalogs` se omite del hash cuando vale `null`, para
conservar replays de comandos aceptados antes de etapa 4. Los snapshots antiguos
sin `catalogs` se interpretan como catálogo vacío; no se reescriben sus JSON.

## Composición, configuración y reconciliación

`src/bootstrap/journals.py` compone repositorio, acciones y consultas. Comparte el
pool del proceso que lo llama; administración usará sus sesiones independientes
al incorporar las rutas de etapa 5. No se agrega otro proceso, broker o proveedor.
El código del dispatcher invoca reconciliación con errores técnicos seguros y
continúa el resto de sus tareas si Journals no está disponible.

`JOURNALS_ENABLED` se define en settings públicos/worker/dispatcher y administrativos,
con default `false`. Debe mantenerse consistente entre procesos al habilitar la
funcionalidad completa. Deshabilitado, se omiten reconciliación e instalación de
templates y se rechazan las nuevas mutaciones. La pregunta diaria consulta el
contexto para impedir convertir un recorrido activo en libre. Los replays de recibos confirmados,
las vistas propias y las referencias históricas se conservan si cuenta/workspace
siguen disponibles. Si se intenta resolver una pregunta para un journal todavía
activo con el flag apagado, se devuelve `journals_disabled`: no se transforma su
contexto silenciosamente en libre. Pausados y terminados sí liberan la conducción.
El publicador omite esa ocurrencia y conserva la reserva diaria.

Al ejecutar reconciliación habilitada se instala de forma idempotente el
[template inicial versionado](../src/core/journals/templates.py) v1 y su
[versión 2 con catálogo](../src/core/journals/preparation_catalog.py), sin crear
recorridos para usuarios. Son contenido de producto independiente de las fixtures.
La v1 conserva su definición y no recibe un catálogo implícito. Activaciones de v2
copian sus catálogos; los recorridos v1 necesitan una revisión explícita para incorporarlos.

`ReconcileJournals` consulta como máximo cien propietarios con un activo vencido,
toma el lock de cada cuenta y aplica la regla pura. Dos dispatchers sólo materializan
una finalización. El reloj normal viene de PostgreSQL; pruebas inyectan reloj sin
reescribir reglas. El cambio ordinario entre etapas se resuelve por intervalos,
sin crear una revisión diaria ni generar preguntas atrasadas. Consultar contexto
o estado no requiere que el dispatcher ya haya materializado la finalización.

La migración es aditiva: no modifica cuentas, sesiones, preferencias, invitaciones
u originales anteriores, no activa recorridos ni hace backfill. Aplicar esquema
antes de iniciar una versión con Journals habilitado. Un downgrade a `20261029_22`
**elimina irreversiblemente templates, recorridos, intención histórica y recibos**;
no es una estrategia de recuperación de sus datos. Las notas y sesiones existentes
no se eliminan. Upgrade/downgrade se verifican sólo en bases desechables.

## Referencia de captura y compatibilidad

`EntryReference` contiene `schema_version: "1"`, `run_id`, `stage_id` y
`run_revision`. No acepta propietario ni campos arbitrarios. Se fija al comenzar
la captura y se valida contra la revisión histórica del mismo dueño y recorrido.
Una referencia no concede acceso por sí sola; la aplicación debe recuperar el
snapshot bajo el alcance autenticado antes de llamar al validador.

`ResponseJournalContext` expresa la asociación ya resuelta desde la invitación:

- Si existe, su referencia es la autoridad. Una referencia omitida se deriva de
  ella; una explícita contradictoria produce `journal_reference_conflict`.
- Una invitación libre tiene un contexto de respuesta con referencia nula; no
  permite convertir su respuesta en journal enviando una referencia distinta.
- Sin invitación, una referencia explícita representa escritura espontánea en
  journal. Si se omite, la escritura sigue siendo libre aunque haya un activo.

Un cierre, pausa, eliminación de etapa futura o ajuste posterior no invalida una
referencia válida de un snapshot archivado. El núcleo verifica dueño, recorrido,
revisión y existencia de etapa, sin sustituirlos por la etapa actual. No prueba
que el servidor hubiera emitido previamente una referencia: la resolución y
aceptación durable deberán fijar ese contexto según el contrato de captura.

Referencias ajenas, inexistentes o con otra revisión devuelven el mismo código
seguro `journal_reference_not_found`. La resolución verifica pertenencia a una
revisión existente, no demuestra el momento de captura declarado por el cliente.
No recalcula la etapa actual ni convierte una nota libre en journal por defecto.

## Pertenencia durable de originales, etapa 3

### Transporte e identidad

`POST /v2/documents` admite `journal_reference` opcional como objeto con los campos
de `EntryReference`. El adaptador lo traduce al contrato interno. También se valida
la referencia en `metadata.journal_reference` si está presente; contradicción con
el campo tipado devuelve `409 journal_reference_conflict`.

`POST /v2/audio-notes` admite un campo multipart `journal_reference` opcional, con
ese objeto serializado como JSON. Las lecturas y la aceptación del audio devuelven
el objeto tipado o `null`. Los documentos conservan la referencia como JSON
canónico dentro de `metadata.journal_reference`, que ya se devuelve en sus lecturas.
Los endpoints de archivo `.md`/`.txt` siguen siendo escritura libre.

La referencia se resuelve antes de reservar o escribir originales, por dueño e
historia. `ResolveJournalCapture` implementa el puerto `CaptureReferences`, inyectado
directamente a los casos de aceptación/importación por bootstrap. El adaptador
PostgreSQL de recibos no llama casos de uso para resolverla. No se necesita el lock
de preferencias al aceptar una captura: los snapshots referidos son inmutables,
por lo que un ajuste concurrente no altera lo que se validó.

Si hay invitación, su asociación histórica prevalece: `journal_invitation_contexts`
relaciona una invitación con dueño, recorrido, revisión y etapa, con FKs compuestas.
La ausencia de fila significa pregunta libre. El publicador de etapa 4 crea esa
asociación en la misma transacción de invitación, sin backfill de preguntas existentes.
El cliente no puede adjuntar otro journal a una invitación
libre ni sustituir su contexto. La pertenencia de pregunta/variante sigue validándose
por el camino existente de exteriorización.

El manifiesto de una nueva captura vinculada agrega `journal_identity: "entry/1"`
y `journal_reference` como JSON canónico. Ese marcador no se agrega al texto ni a
los metadatos del documento; el original sólo guarda su referencia. El hash del
texto incluye esos metadatos y el del audio su manifiesto. Omitir o cambiar la
asociación con la misma clave es conflicto. Campo tipado y representación canónica
en metadata equivalen a la misma solicitud de texto.

Sin journal no se agregan campos al manifiesto ni se cambian hashes. Los recibos
v1/v2 previos conservan su representación y compatibilidad de variante inicial.
Un recibo histórico sin marcador no puede adquirir ahora una asociación. Replays
y aliases por ID explícito conservan el original y la configuración aceptada.
No se reescriben originales ni recibos anteriores.

Referencias ajenas/inexistentes devuelven `404`, contradicciones de asociación
`409`, formas inválidas `422` y disponibilidad SQL `503`, con códigos seguros.
La aceptación de referencias históricas del propietario sigue disponible con el
flag apagado; no depende de que el recorrido siga activo. No se registra contenido.

### Atomicidad y recuperación

`journal_entries` es un índice de pertenencia por dueño, tipo (`audio`/`document`)
y UUID de original, con referencia compuesta a la revisión de etapa y fecha de
aceptación. Guarda IDs y fechas, sin copiar texto, audio, objetivos o intención.
Un recurso sólo tiene una asociación; repetir el enlace con otra referencia falla.

En texto, original y vértice base se guardan antes del commit SQL, según el contrato
de ingestión existente. Entrada de journal, recibo aceptado, job, evento y outbox
se confirman juntos. Un fallo SQL deja el original recuperable y toda esa transacción
sin confirmar; retry o reconciliación usan la referencia fijada en el manifiesto,
sin volver a resolver etapa ni llamar proveedores.

En audio, el upload acepta la entrada `audio` junto con su job/recibo/outbox. Los
metadatos JSON incluyen la referencia; si sobrevivió sólo el raw, se reconstruyen
desde el manifiesto. El worker propaga la referencia al documento derivado. Después
de persistir ese original y su base de grafo, el handoff SQL obtiene la asociación
del audio ya aceptado y confirma la entrada `document` junto con hijo, transición
del padre, eventos y outbox. No consulta la etapa actual ni añade reintentos del
broker. Fallos de handoff reutilizan la transcripción y sus artefactos.

El borrado bajo el lock de recurso elimina las entradas de ambos tipos para ese
UUID y mantiene el tombstone de procesamiento. Un replay de upload sobre un recurso
marcado como eliminado devuelve `resource_deleted`, aunque un archivo haya quedado
pendiente de limpieza; no vuelve a crear el índice. Reprocesar no reasigna el journal.
La futura consulta de entradas deberá comprobar disponibilidad del original, no
tratar el índice SQL como fuente de contenido.

El respaldo v1 conserva la referencia en metadata. Antes de importar el primer
documento se validan todas las referencias contra snapshots del dueño destino.
Si falta un recorrido/revisión o pertenece a otra cuenta, se rechaza sin escrituras;
no se descarta la pertenencia silenciosamente. Un import válido preserva el original
y confirma su entrada con la aceptación SQL. El respaldo no incluye templates ni
historia de recorridos: no permite por sí solo restaurar notas vinculadas después
de recrear esos datos o cambiar de propietario. Ver [respaldos](document-archives.md).

La migración `20261103_24` es aditiva, sin backfill ni cambios a originales. Debe
aplicarse antes de iniciar la nueva API, workers y dispatcher, aun con el flag
apagado, porque los caminos de aceptación, derivación y borrado conocen las tablas.
Su downgrade pierde índices de pertenencia y contexto de invitación; conserva
originales y jobs, pero no ofrece reconstrucción automática del índice al subir.

## Pregunta diaria contextualizada, etapa 4

### Catálogo y ajustes

Cada `StageCatalog` pertenece a una clave de etapa y contiene entre una y doce
propuestas con clave temática estable y variantes `gentle`, `middle`, `deep`.
La v2 inicial contiene tres temas por etapa. Los textos deben ser distintos,
de una línea, con una pregunta y hasta 240 caracteres por variante.

`goal_hash` fija la aprobación editorial al propósito, indicaciones generales,
objetivo e indicaciones de etapa. Cambiar alguno de esos campos deja el catálogo
anterior fuera de uso. `AdministrativeRunView.catalog_review_required` identifica
las etapas actuales/futuras sin catálogo compatible; no incluye intención privada.
Duración, calendario e intención no alteran ese hash; cualquier mutación conserva
su efecto de nueva revisión e invalida preparaciones anteriores.

`AdjustRun.catalogs=null` conserva los catálogos de las etapas retenidas. Una tupla
explícita reemplaza el conjunto: cada catálogo enviado debe aprobar la definición
resultante. Una tupla vacía los retira. Para un catálogo existente se conservan las
claves de los temas retenidos; no se permite renombrarlos para eludir un cierre.
Las etapas nuevas pueden incorporar catálogos propios. Las etapas completadas
conservan su definición y su historia.

Los IDs de temas curados se derivan de propietario y clave temática, sin recorrido,
etapa o revisión. Repetir el template conserva los límites y descansos anteriores.
Los IDs de preguntas y grupos pertenecen a cada invitación. La rotación del catálogo
usa el historial del recorrido y aplica la política existente de elegibilidad.

### Preparación e inventario

Exteriorización consume el contexto antes de construir candidatos, para el instante
programado de la pregunta. `PrepareJournalQuestions` extiende los hooks de
`PrepareQuestions`; `question_preparation/2` comparte runner, transiciones, leases,
artefactos, cuotas y outbox con `/1`. La versión anterior permanece registrada
y conserva configuración, identidad libre y prompt anteriores.

La migración `20261103_25` agrega `question_preparations.context_key`, con backfill
`free`, y amplía la unicidad por cuenta/horario/versión de preferencias/contexto.
Un contexto de journal incluye recorrido, etapa y revisión. Reservar otra revisión
vuelve obsoleta la anterior; nunca transforma su trabajo en libre.
La configuración v2 guarda `journal_reference`; el snapshot añade esa referencia
y el hash del contexto. Los textos de propósito, objetivo e intención se reconstruyen
desde la revisión inmutable, sin copiarlos a jobs ni logs. La caché del proveedor
usa sólo modelo, versión de prompt y límites técnicos, sin referencias personales.

El inventario SQL incluye como máximo veinte documentos del mismo propietario y
recorrido, vinculados a la etapa objetivo o a etapas anteriores presentes en esa
revisión. Excluye notas libres, otros recorridos, etapas futuras y etapas quitadas;
prioriza etapa actual y luego recencia. No aplica el corte de treinta días del
modo libre. Conserva los presupuestos de entrada, excerpts de hasta 2400 bytes,
fechas autorales y límites de historial de catorce invitaciones del recorrido.
Audio aporta su documento derivado, sin otra transcripción.

Los descriptores personales abiertos requieren evidencia en ese inventario.
Los descriptores de temas restringidos del propietario se conservan como límites,
incluso si provienen de otra práctica; no incorporan sus notas o historial al
contexto. Más de 64 descriptores impide generar con restricciones incompletas.
El prompt `journal-proposals-v1` acota propósito, indicaciones e intención como datos
del recorrido y exige evidencia de sus fuentes; no amplía la autoridad de esos textos.

Sin fuentes no se llama al proveedor. En modo `curated` tampoco se reservan ni
ejecutan nuevas generaciones. La validación sintética del proveedor usa un cliente
doble; no acredita calidad semántica con un modelo real.

### Vigencia, publicación y recuperación

Antes de generar se comprueban cuenta/workspace, preferencias y contexto. Antes
de aceptar se reconstruyen hashes, fuentes y contexto histórico; la transacción
revalida contexto actual y pertenencia SQL. El finalizador vuelve a comprobar
evidencia, límites y revisión bajo los locks existentes de cuenta y recurso.
Un archivo pendiente de limpieza sin su pertenencia SQL ya no sostiene una propuesta.
No se toman locks de recursos antes del lock compartido de preferencias.

La selección mantiene las tres profundidades y una alternativa curada del journal;
la cadencia de pregunta inicial curada se cuenta dentro del recorrido (cada cuatro
por defecto). Un fallo del proveedor o una preparación ausente/obsoleta usa el
catálogo elegible actual. Sin catálogo compatible o si todos sus temas están
restringidos, se omite con `no_eligible_questions` y se avanza la reserva diaria.
No se usa el catálogo libre ni se levanta un límite para llenar esa ocurrencia.

La invitación, sus grupos/procedencia, `journal_invitation_contexts`, bandeja, jobs
de push y outbox se confirman juntos. La procedencia conserva referencia y hash
del contexto, además de evidencia personal cuando corresponde. Las respuestas
heredan esa asociación histórica por el camino de etapa 3. Un retry posterior a
un artefacto durable lo reutiliza sin otra llamada al proveedor.

Pausar, cerrar o completar libera la siguiente ocurrencia disponible al contexto
libre; éste no consume preparaciones del journal. Apagar el flag con un recorrido
activo omite la ocurrencia. Se conserva una sola publicación por día; resultados
tardíos no reemplazan invitaciones ni generan otro push.

Aplicar `20261103_25` antes de iniciar API/dispatcher/workers nuevos, también con
el flag apagado. Detener escritores antes de migrar y mantener versiones de procesos
consistentes. Su downgrade a `20261103_24` elimina las preparaciones temporales de
journal y restaura la unicidad anterior; sus jobs internos vencen por el runtime.
Conserva originales, recorridos e invitaciones publicadas. No es una recuperación
de preparaciones eliminadas. No se ha aplicado sobre datos reales.

## Validación y próximo paso

```sh
.venv/bin/python -m pytest tests/test_journals_contracts.py tests/test_architecture_boundaries.py
.venv/bin/python -m pytest tests/test_journals_application.py
.venv/bin/python -m pytest tests/test_journal_entries.py
.venv/bin/python -m pytest tests/test_journal_questions.py
.venv/bin/python -m ruff check src/core/journals tests/test_journals_contracts.py
python3 scripts/check_architecture.py
python3 scripts/check_repo_docs.py
git diff --check
```

Las pruebas de núcleo/aplicación incluyen fronteras exactas, días sin actividad, horarios estacionales,
pausa/reanudación, preservación de fechas tras ajustes, conflictos de revisión,
aislamiento de propietarios, referencias antiguas, proyecciones privadas/públicas
y carga del núcleo con imports de infraestructura bloqueados.

Para SQL, usar `JOURNALS_TEST_DATABASE_URL` con una base cuyo nombre comience por
`journals_test`, migrada al head. La prueba de migración crea otra base con ese
prefijo y la elimina al finalizar; necesita permiso de crear/borrar bases sólo en
esa instancia de pruebas. No apuntar estas suites a un entorno con usuarios.

```sh
.venv/bin/python -m pytest tests/integration/test_journals_postgres.py \
  tests/integration/test_journals_migration.py
```

Las integraciones cubren activaciones y replays concurrentes, índice único incluso
sin reglas de aplicación, revisiones simultáneas, rollback antes del recibo y fallo
al confirmar un FK diferido, aislamiento por dueño, snapshots corruptos, lock
compartido con preferencias, catch-up concurrente y preservación de historia.
La migración se compara con los modelos SQL y conserva cuentas/sesiones/preferencias
sintéticas anteriores. Un skip no valida estas garantías.

La aceptación usa también `PROCESSING_TEST_DATABASE_URL`, con una base desechable
`journals_test*` para `tests/integration/test_journal_ingestion.py`. Cubre texto y
audio espontáneos/respuestas, replays, capturas después de cierre/ajuste, fallos SQL
y handoff, restauración de metadata, borrado, importación y HTTP. Las regresiones
de pregunta diaria y audio conservan v1/v2. Grafo y transcripción son dobles; no se
acredita ArcadeDB, broker, dispositivo ni proveedor real por esas pruebas.

`tests/integration/test_journal_question_preparation.py` usa
`INVITATIONS_TEST_DATABASE_URL` en una base `journals_test*`, migrada al head.
Cubre aislamiento, primer día sin notas, cambio de etapa durante anticipación,
ajuste durante generación, revisión editorial, cadencia, límites entre recorridos,
borrado de evidencia, cuenta inactiva, rollback completo de publicación,
concurrencia y recuperación sin otra llamada. La prueba de migración cubre JSON
legado sin catálogos, backfill libre y downgrade con dos contextos de una ocurrencia.

El próximo paso es la etapa 5, comenzando por el prototipo del panel administrativo.
Las pantallas administrativas y PWA requieren prototipos validados antes de
implementar sus interfaces. No hay experiencia de piloto habilitada; proveedor
real, broker, push y dispositivos no fueron validados en esta etapa.
