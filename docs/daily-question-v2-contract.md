# Pregunta diaria v2 · Contratos y preparación

Estado: etapas 1–4 implementadas localmente; fase 5 con herramientas y pruebas locales.
Requiere migrar a `20261029_22`. Corrida real sintética ejecutada; revisión humana,
dispositivo y habilitación pendientes.
Incluye flujo PWA y preparación personalizada en segundo plano. Modo predeterminado
`curated`; proveedor probado con dobles y con material sintético en OpenAI.
Implementación no desplegada. Ver el [plan](daily-question-v2-plan.md)
y la [operación de invitaciones](exteriorization-notifications.md).

## Modelos y ejemplos ejecutables

- [Contratos](../src/core/exteriorization/question_contracts.py): paquete público,
  adaptación histórica, referencia de respuesta, feedback e interacciones.
- [Política](../src/core/exteriorization/question_policy.py): límites de tema,
  reapertura por evidencia y selección sobre propuestas ya ordenadas.
- [Fixture JSON](../tests/fixtures/daily_questions_v2_contract.json): paquete
  completo sintético, entrada de feedback/interacciones y dieciséis casos de
  selección con resultado esperado.
- [Pruebas](../tests/test_daily_question_contracts.py): validación del contrato,
  compatibilidad, aislamiento y transiciones. No invocan modelos o servicios.

Los modelos están en el núcleo, sin HTTP, SQL o proveedores. Los schemas
HTTP traducen estos contratos con sus propios modelos de acceso. `model_json_schema()` permite obtener el esquema de cada modelo.

## Identidad y paquete público

`InvitationQuestionSet` es un fragmento aditivo de la lectura de una invitación.
`id` conserva el UUID de la invitación, no crea una segunda ocurrencia. La lectura
real conserva además sus campos actuales de fechas, versiones, categoría, etc.

| Campo nuevo | Contrato |
| --- | --- |
| `question_schema_version` | `"1"`, versión del formato del paquete; independiente de la versión del motor. |
| `default_question_id` | UUID de la pregunta media del primer grupo. |
| `question_groups` | Entre uno y tres grupos ordenados, con IDs únicos. |
| Grupo: `id`, `source`, `layout`, `questions` | Procedencia `generic`/`personalized`; formato `depths` o `legacy`. |
| Pregunta: `id`, `depth`, `text` | UUID único en el paquete, profundidad y texto exacto de hasta 240 caracteres. |

Un grupo `depths` contiene exactamente `gentle`, `middle`, `deep`, en ese orden.
No admite profundidades duplicadas, texto vacío, saltos de línea o IDs repetidos.
El texto heredado `question` coincide exactamente con `default_question_id`.
Cambiar de profundidad conserva el grupo; cambiar de grupo vuelve a `middle`.
La selección devuelve IDs ordenados, nunca reescribe el texto publicado.

El paquete no contiene usuario, ID de tema, notas de evidencia, ranking o estado
privado del tema. Los textos no aparecen en el `repr` de los modelos. El adaptador
no debe registrar errores de validación con el payload original incluido.

Las invitaciones v1 se proyectan como un único grupo `legacy`, con una sola
pregunta y `depth: null`. Sus IDs se derivan de forma estable con UUIDv5 usando
el UUID de invitación como namespace y los nombres `legacy-group-v1` y
`legacy-question-v1`. No insertar nuevas interpretaciones en filas históricas.
La PWA ocultará controles para alternativas inexistentes. No hay backfill de
temas personales a partir de las doce preguntas anteriores.

## Referencia de respuesta e idempotencia

Ejemplo de los campos que se agregarán al alta de una nota:

```json
{
  "invitation_id": "76bb947b-ae61-521b-b718-c5d6aa1a1450",
  "invitation_question_id": "32017122-2698-50fb-8003-2e68cc72c2e7"
}
```

Son campos JSON en documentos y multipart en audio. Ambos pueden omitirse para
escritura libre. Una pregunta sin invitación es inválida. Un cliente que envía
solo `invitation_id` responde la pregunta inicial, incluso si el paquete tiene
alternativas. El servidor no acepta un texto de pregunta enviado por el cliente
como sustituto del ID.

El caso de uso obtiene primero la invitación del propietario autenticado; luego
`resolve_response_question` verifica pertenencia y normaliza la variante omitida.
Un ID ajeno no cambia de propietario ni se resuelve por búsqueda global.
Una pregunta histórica sigue siendo respondible aunque su tema esté cerrado:
la política restringe futuras propuestas, no la exteriorización voluntaria.

La aceptación guarda la variante normalizada en recibo, manifest, original y vínculo
SQL. Clave repetida más la misma asociación equivale a replay; cambiar la variante
con esa clave es conflicto. Preservar el formato/hash de recibos v1 aceptados:
leer primero la versión del recibo existente para validar su replay; no recalcular
su identidad con un hash v2. La omisión en una solicitud nueva equivale al default,
pero nunca convierte un replay antiguo en respuesta de otra variante.

## API de feedback e interacciones

Rutas bajo `/api`, autenticadas y con la protección de origen existente.
El `user_id`, fechas de recepción y secuencias se resuelven
en servidor; los modelos de entrada rechazan campos adicionales.

### Feedback

`POST /exteriorization/invitations/{id}/feedback`, con `Idempotency-Key: UUID`:

```json
{
  "invitation_question_id": "32017122-2698-50fb-8003-2e68cc72c2e7",
  "value": "closed"
}
```

| Acción visible | Valor | Efecto en el tema |
| --- | --- | --- |
| Me sirvió | `helpful` | Señal de calidad; conserva límites existentes. |
| No conectó conmigo | `unrelated` | Señal de pertinencia; no supone cierre. |
| Hoy no era el momento | `not_now` | Pausa temporal. |
| Por ahora está cerrado | `closed` | No volver a proponer hasta nueva intención válida. |
| No quiero hablar de esto | `do_not_prompt` | Límite explícito; no vence por tiempo. |

Cerrar el modal, «En otro momento» y «Hoy paso» no crean estos eventos.
La nota no necesita haber llegado al servidor para registrar feedback. El evento
apunta a la pregunta persistida, no a la última nota ni a la selección mutable
del cliente. La secuencia de recepción del servidor ordena sus efectos.

Respuesta: `200` con un recibo estable `{id, invitation_id,
invitation_question_id, value, recorded_at}`. Misma clave/cuerpo devuelve el mismo
recibo; misma clave con otra intención produce `409`. Validación/forma inválida
produce `422`, sesión ausente `401`, e invitación o pregunta ajena/inexistente
`404` sin revelar datos. Un lock de preferencias del propietario serializa
generación y actividad; evento, recibo y estado de tema se confirman juntos.
La actividad de una invitación `test` se conserva sin modificar límites ni
consumir historial real.

### Interacciones

`POST /exteriorization/invitations/{id}/interactions`, con `Idempotency-Key: UUID`:

```json
{
  "events": [{
    "event_id": "7ac39472-01a0-5929-86e5-9f5b41e70ddb",
    "invitation_question_id": "9669a2b4-0e97-5015-b971-122f5da288a9",
    "kind": "shown"
  }]
}
```

Tipos: `shown`, `another_requested`, `passed`. El batch contiene entre uno y
32 eventos con IDs distintos. El cliente conserva los IDs para reintentar.
Prefetch, alternativas ocultas y aceptación del proveedor push no son `shown`.
El primer `shown` por propietario/invitación/pregunta cuenta una
vez, aunque lleguen UUID distintos desde otro dispositivo. No contar renders o
reiniciar el plazo de silencio por duplicados. Las fechas son de recepción del
servidor: una sincronización tardía retrasa prudentemente el comienzo del plazo.

Respuesta: `200` con `{recorded_event_ids}`. El replay exacto devuelve
el recibo inicial. Un event ID reutilizado con otro contenido es `409`; IDs ajenos
o preguntas de otro paquete son `404`. Los eventos se encolan y envían sin bloquear
la elección local. Navegación no equivale a rechazo ni modifica límites.

## Política `daily-question-policy-v1`

Los valores se congelan con la ejecución aceptada. Son hipótesis operativas
ajustables, no medidas psicológicas:

| Parámetro | Inicial | Semántica |
| --- | --- | --- |
| `max_groups` | 3 | Máximo de temas preparados; reservar una opción curada. |
| `max_followups` | 1 | Tras una continuación mostrada, descansar ese tema. |
| `rest_days` | 7 | Descanso por continuación, silencio o `not_now`. |
| `silence_hours` | 48 | Espera desde el primer `shown` recibido sin respuesta aceptada. |
| `general_every` | 4 | Tras tres preguntas iniciales personales, la cuarta empieza con catálogo. |

`select_question_groups` recibe candidatos **ya ordenados** y evidencia verificada
por aplicación. No realiza ranking semántico ni lee notas. Antes de publicar,
elimina evidencia inválida, límites, pausas activas, continuaciones agotadas y
silencio vencido; mantiene un solo grupo por tema. El orden nunca supera estos
filtros. La cadencia se cuenta por la pregunta inicial de ocurrencias programadas,
no por alternar profundidades o enviar push a distintos dispositivos.

Si falta una alternativa curada elegible, devuelve `requires_catalog: true` y
ningún paquete publicable. El finalizador deberá buscar otro grupo curado válido;
no puede relajar un cierre para garantizar un envío. Si todo el catálogo está
excluido, omite esa ocurrencia con un código seguro, conservando su reserva diaria.

El silencio descansa durante siete días desde que se cumplen las 48 horas. La
continuación descansa desde que fue mostrada. Los intervalos incluyen el inicio y
excluyen su final. Una respuesta tardía aceptada elimina el motivo de silencio
en la siguiente evaluación, pero no revoca feedback explícito. La aplicación
reinicia el contador de continuaciones al comenzar un ciclo después del descanso.
Paquete preparado pero nunca mostrado no inicia ese contador.

`apply_topic_feedback` consume la secuencia monotónica del servidor y no repite
efectos de secuencias viejas. Un comentario positivo no levanta pausas o cierres;
un límite menor tampoco rebaja otro más fuerte. La persistencia confirma
evento y estado derivado en una transacción bajo el lock del propietario. La
futura reapertura deberá usar ese mismo orden de locks para no perder cierres
concurrentes. La función pura no reemplaza ese lock.

## Reapertura e identidad de tema

El ID interno de tema pertenece a una cuenta. Su alcance es una situación concreta;
cerrar un conflicto de trabajo no prohíbe toda pregunta laboral. En catálogo, el
límite recae sobre el grupo curado, sin inventar biografía. Grupos publicados en
días distintos conservan su referencia al tema, pero sus preguntas tienen IDs
históricos propios de cada paquete.

La aplicación debe resolver esa identidad antes de marcar `evidence_valid`.
Si una propuesta podría ser una reformulación de un tema limitado y la asociación
es incierta, descartarla; no crear otro ID para eludir el límite. El selector puro
no compara semánticamente títulos ni demuestra por sí solo esa correspondencia.

`reopen_topic` requiere una asociación confirmada al mismo tema, intención explícita
de retomarlo y un original disponible del mismo propietario. Tanto autoría como
aceptación deben ser posteriores al límite y no estar en el futuro. Una mención,
otro rechazo, asociación dudosa o importación de una nota vieja no lo reabre.
No aplicar un TTL a cierres. Una nueva intención válida puede reabrir también un
grupo curado limitado, sin crear por eso un tema personal inferido.

Conservar el límite original y el ID de la nota que motivó la reapertura. Esa
reapertura deja de aplicar pausas por exposiciones anteriores, pero no impide que
feedback posterior vuelva a cerrar. La futura etapa de propuestas evalúa intención
y correspondencia; estos contratos no prueban que un LLM lo interprete bien.

## Casos de aceptación y alcance pendiente

La fixture cubre selección normal, cierre pese a ranking alto, rechazo sin
vencimiento, pausa y su frontera exacta, espera de 48 horas, descanso por silencio,
su vencimiento, respuesta tardía, continuación, reapertura, evidencia borrada,
cadencia general, catálogo cerrado/ausente y temas duplicados. Las pruebas suman
compatibilidad histórica, referencia de variante ajena, modelos inmutables,
secuencias repetidas, intención insuficiente e aislamiento de cuentas.

```sh
.venv/bin/python -m pytest tests/test_daily_question_contracts.py
.venv/bin/python -m ruff check src/core/exteriorization/question_contracts.py \
  src/core/exteriorization/question_policy.py tests/test_daily_question_contracts.py
```

## Persistencia y validación de la entrega 2

`20261029_18` agrega paquete/política JSONB a la invitación, índice relacional de
preguntas y variante nullable en respuestas. Agrega temas del catálogo por dueño,
recibos de actividad, feedback, interacciones y reservas de ocurrencia. El índice
permite claves foráneas compuestas de pertenencia; los grupos y textos viven en
el snapshot inmutable. Un índice `legacy` se materializa al responder/opinar sin
modificar el texto histórico ni asignarle un tema.

Los eventos `shown` de dispositivos distintos pueden quedar en el ledger; la
proyección usa el primer instante por tema/invitación y la última ocurrencia
mostrada, sin contar renders ni reiniciar plazos. Una respuesta a otra profundidad
del mismo tema también se reconoce. Las pruebas `test` quedan fuera de esa proyección.

El catálogo de doce temas tiene tres profundidades curadas. Usa la rotación previa
como orden inicial y luego aplica límites y pausas. No clasifica todavía notas ni
aplica continuaciones personales: esa parte corresponde al motor de la entrega 4.
Las lecturas históricas conservan el paquete original; los límites se aplican a
nuevas propuestas. Los valores de política aceptados se guardan privadamente y se
reutilizan al procesar feedback de esa invitación.

Verificaciones reproducibles, con servicios exclusivamente aislados:

```sh
INVITATIONS_TEST_DATABASE_URL='postgresql+asyncpg://…/isolated_test' \
  .venv/bin/python -m pytest tests/integration/test_daily_question_packages.py
PROCESSING_TEST_DATABASE_URL='postgresql+asyncpg://…/isolated_test' \
  .venv/bin/python -m pytest tests/integration/test_daily_question_ingestion.py
```

Las suites cubren HTTP, propiedad, origen, duplicados concurrentes, rollback de
batch, reservas omitidas, compatibilidad v1, selección de variante en texto/audio,
recuperación de metadata y persistencia sin repetir transcripción. Upgrade y
ciclo downgrade/upgrade se validan con invitación y respuesta v1 sintéticas.
Los tests usan grafo/proveedores simulados; no acreditan push real, calidad de un
LLM, sincronización de la PWA ni dispositivo.

## Integración de la entrega 3 en PWA

La PWA consume el paquete sin cambiar estos contratos. La selección de profundidad
y tema es local; texto y multipart envían `invitation_question_id`. Borradores y
sesiones de voz conservan referencia y texto histórico. Dexie v9 confirma nota y
oferta de opinión juntas; feedback/interacciones tienen cola e identidad propias
y pueden llegar antes de subir la nota. Las lecturas antiguas sin paquete mantienen
una pregunta única, sin inventar IDs ni alternativas.

Regresión PWA: 32 archivos Node aprobados, lint/build/verify:build y revisión en
Chrome headless a 320, 390, 768 y 1440 px, con API y contenido sintéticos. No se
repitió la integración conjunta PostgreSQL/RabbitMQ; dispositivo, push, micrófono
y teclado virtual reales siguen pendientes. La implementación personalizada se detalla a continuación.

## Preparación personalizada de la entrega 4

`PrepareQuestions` coordina por puertos el workflow interno `question_preparation/1`.
Bootstrap lo registra en el registro compartido; no agrega scheduler, extractor
ni reintentos Taskiq. El dispatcher publica primero las ocurrencias vencidas y
después reserva preparaciones para preferencias habilitadas con workspace activo,
hasta 30 minutos antes del horario. La clave incluye propietario, instante y versión
de preferencias. Dos dispatchers aceptan una sola preparación, job y outbox.
Los trabajos internos no aparecen en `/processing`, SSE ni retry público.

`PreparationConfiguration` congela modelo, versiones de prompt/selector, límites
de entrada/salida, tiempo, concurrencia y anticipación, sin secretos. El worker
consulta vigencia antes de generar y antes de aceptar el paquete. Desactivar,
cambiar horario/zona/versión de preferencias o suspender el workspace invalida
esa preparación. Una activación con poco margen se prepara en el siguiente ciclo;
el programador no espera que termine. El modo `curated` también evita ejecutar
nuevas llamadas desde jobs internos ya aceptados.

### Contexto y propuestas

- Inventario SQL de originales con job de documento aceptado, hasta 20 documentos
  de los últimos 30 días. Prioriza respuestas de las últimas 14 invitaciones y luego
  notas recientes. Lee originales por el puerto del propietario, sin cargar todas
  las notas ni consultar emociones, ejes o ArcadeDB. Audio usa su documento
  derivado existente; no transcribe de nuevo.
- El historial distingue pregunta inicial, variantes efectivamente mostradas,
  respuestas por variante y último feedback recibido. No presenta todas las
  alternativas como si hubieran sido vistas. Consultas de actividad/feedback
  acotadas a 126 registros por tipo y a esas catorce invitaciones.
- Fecha autoral y de aceptación se conservan por separado. Importar una nota antigua
  no la vuelve evidencia actual de reapertura. Las referencias guardan hash del
  contenido, fechas, longitud de excerpt y marca de recorte. No copian notas completas
  al snapshot. El texto enviado al proveedor se reconstruye desde esos originales.
- Hasta 64 descriptores personales conocidos; si se excede ese límite no se genera
  con un inventario incompleto de restricciones. Ese día queda el catálogo.
- Presupuesto conservador: bytes UTF-8 como cota de tokens textuales, con reserva de
  7000 para instrucciones/esquema; el adaptador comprueba además el tamaño de ambos.
  Los excerpts usan como máximo 2400 bytes por documento y declaran el recorte.
  Historial y descriptores también consumen presupuesto. Un contexto demasiado grande
  falla con código seguro y no llama al proveedor.
- El prompt trata notas e historial como datos no confiables, respeta el trato del
  usuario y propone hasta tres temas con tres profundidades. IDs de tema existentes
  tienen prioridad frente a títulos; la incertidumbre pide omitir, no fusionar o
  renombrar un límite. La identidad de un tema nuevo se ancla a evidencia, no sólo
  al título. La aplicación valida propietario, referencias, offsets y preguntas
  distintas de una sola línea y hasta 240 caracteres. La calidad semántica necesita
  la evaluación de la entrega 5.

El adaptador usa Responses con salida estructurada Pydantic, `store=False`,
timeout, límite de salida y retries SDK desactivados, siguiendo
[OpenAI Docs](https://developers.openai.com/api/docs/guides/structured-outputs).
Errores del proveedor y validación se sustituyen por códigos seguros sin cadenas
con texto privado. No se registran notas, preguntas personales ni payloads.

### Selección y publicación

La selección tiene un artefacto/versionado propios y es determinística: orden
lexicográfico por fundamento explícito, recencia autoral y esfuerzo bajo, con
desempate estable. Después aplica las exclusiones de `QuestionPolicy`; ningún
criterio de orden supera una pausa o cierre. Incluye una alternativa curada y
la primera opción es general al menos cada cuatro ocurrencias personalizadas.
El silencio no se convierte en desinterés ni disponibilidad emocional inferida.

Al horario, el finalizador toma el mismo lock de preferencias, consume la preparación
lista y revalida referencias, hashes y límites actuales. Los originales se protegen
con los mismos locks compartidos de recurso usados por borrado/procesamiento.
Un recurso ocupado lleva al catálogo; evidencia que ya no existe descarta las
propuestas que la usan. El fallback no invoca un modelo. La transacción conserva invitación, índices, procedencia,
bandeja, envíos y outbox juntos. Un resultado lento no reemplaza una publicación ni
origina otra notificación. Una ocurrencia sin catálogo elegible se omite.

Reabrir un tema conocido exige correspondencia confirmada por el proponente,
intención explícita `reopen`, evidencia disponible y fechas autoral y de aceptación
posteriores al límite. Una mención, inferencia, importación antigua o cierre posterior
al snapshot no alcanzan. Se conserva el feedback histórico y la nota que habilitó
la reapertura. Evaluar la correspondencia semántica del proveedor sigue pendiente.

La lectura HTTP agrega `available_question_ids`: filtra nuevas opciones según
restricciones actuales sin alterar `question`, variantes, IDs o textos guardados.
La PWA la usa al abrir/refrescar y al cambiar; conserva la variante de una respuesta
histórica ya iniciada. Un cliente con la vista cargada puede estar desactualizado.
La aceptación de una respuesta voluntaria histórica no exige que el tema siga abierto.

### Recuperación, retención y configuración

Los artefactos `context`, `proposals` y `selection` son exclusivos, hash-verificados
y publicados con fsync. Un fallo de checkpoint o aceptación SQL reutiliza los artefactos
sin otra generación. I/O de archivos o SQL no confirmado conserva la entrega para
recuperación por lease. Una caída entre respuesta remota y guardado durable todavía
puede repetir una llamada; no se promete ejecución remota exactamente una vez.
Proveedor inválido/fallido no recibe correcciones automáticas ni retries pagos SDK.

`20261029_19` agrega preparaciones y descriptores de temas personales; `20261029_20`
conserva procedencia por grupo y un código de decisión del finalizador. No hay backfill
ni cambios a originales. Temporales y artefactos vencen 36 horas después del horario,
con limpieza por lotes de 50 en el dispatcher. La procedencia aceptada queda vinculada
a la invitación: configuración/versiones y referencias/hashes de evidencia, sin
copias de las notas. Los jobs mantienen sólo configuración técnica y checkpoints.
Downgrade pierde preparaciones/procedencia nuevas; conserva preguntas y respuestas.

| Variable | Default y alcance |
| --- | --- |
| `DAILY_QUESTION_MODE` | `curated`; `personalized` prepara automáticamente para quienes ya tienen invitaciones habilitadas. No activa preferencias apagadas. |
| `DAILY_QUESTION_MODEL` | Vacío reutiliza `OPENAI_MODEL`; ambos vacíos impiden preparar, sin elegir otro modelo. |
| `DAILY_QUESTION_MAX_INPUT_TOKENS` | 24000, cota conservadora de entrada, rango 8000–64000. |
| `DAILY_QUESTION_MAX_OUTPUT_TOKENS` | 3000, rango 1000–8000. |
| `DAILY_QUESTION_TIMEOUT_SECONDS` | 45, rango 1–120; también limitado por el tiempo hasta el horario. |
| `DAILY_QUESTION_CONCURRENCY` | 2 por proceso/configuración de proveedor, rango 1–8; además rige la concurrencia del worker. |
| `DAILY_QUESTION_LEAD_MINUTES` | 30, rango 1–120. |

El dispatcher admite hasta 100 preparaciones por ciclo y 1000 jobs vigentes globales.
API, worker y dispatcher deben compartir modo, configuración y volumen de workspaces.
No activar `personalized` en un entorno con datos como parte de esta implementación.

### Verificación local

```sh
.venv/bin/python -m pytest tests/test_daily_question_preparation.py
INVITATIONS_TEST_DATABASE_URL='postgresql+asyncpg://…/isolated_test' \
  .venv/bin/python -m pytest tests/integration/test_question_preparations.py
```

Pruebas con originales y proveedor sintéticos: contexto acotado/recortado, referencias
inválidas, errores seguros, repetición tras checkpoint/confirmación perdida, dispatcher
y worker duplicados, fencing perdido, proveedor lento frente a fallback, cierre/borrado
posterior, preferencias/workspace obsoletos, reapertura explícita, frecuencia general,
inventario de respuestas y conservación de procedencia tras limpiar temporales.
La suite usa el executor SQL real y su outbox sin necesitar un broker; no acredita
transporte RabbitMQ, push, calidad de un modelo real ni comportamiento de teléfonos.

Validación del 2026-10-29: **133 pruebas de core y 51 de PostgreSQL aprobadas**;
una omitida por requerir RabbitMQ aislado. Upgrade → downgrade hasta `20261029_18`
→ upgrade y `alembic check` aprobados, conservando invitación/respuesta v1 sintéticas.
Arquitectura, Ruff y documentación sin errores. La PWA pasó sus 32 archivos Node,
lint/build/verify:build y aplica disponibilidad sin cambiar el diseño aprobado.
La corrida real posterior y los pendientes de habilitación se detallan en la entrega 5.

## Evaluación y controles de la entrega 5

El [procedimiento operativo](daily-question-operations.md) es la referencia para
dataset/runner, revisión, configuración compartida, métricas, habilitación y rollback.
Incluye 18 casos sintéticos con puertos en memoria que ejecutan el mismo contexto
y selector de producción; un resultado de referencia nunca acredita calidad real.
Las corridas pagas exigen plan explícito de modelo, tarifas verificadas, presupuesto
y límite de llamadas, además de autorización específica. Recibos ambiguos no se
repiten automáticamente y la revisión se vincula al hash exacto de los resultados.

`PreparationConfiguration.policy` congela las opciones aceptadas. API y dispatcher
inyectan la política tipada en `GenerateInvitation`; la invitación conserva su propio
snapshot para feedback posterior. El contador SQL de seguimientos usa el descanso
configurado, sin un segundo valor fijo. Jobs v1 sin política conservan los defaults v1.

`20261029_21` agrega métricas sin contenido y recibos por job/token de fencing;
`20261029_22` indexa la admisión por día UTC. La cuota global actual limita todos
los modelos/propietarios, incluyendo intentos desconocidos, antes de llamar al proveedor.
Los artefactos conservan uso/latencia y referencia del intento para recuperar un
fallo posterior de métricas sin otra generación. No se promete ejecución remota única
si una caída ocurre antes de guardar el resultado.

Las métricas sobreviven al TTL de preparación y vencen a los 90 días, con limpieza
acotada. Sólo se exponen agregados operativos, sin notas, preguntas o IDs de personas.
El feedback de prueba se excluye. Uso desconocido permanece desconocido; el costo
USD no se inventa sin tarifas. La vuelta a `curated` conserva paquetes, respuestas y
feedback, y no activa nuevas preferencias ni cambia el estado de push.

Verificación local del 2026-10-29: **140 pruebas de core, 59 de PostgreSQL y una
de transporte con dos workers Taskiq/RabbitMQ aprobadas**. La prueba de transporte
usa push simulado; no acredita entrega a un teléfono. Los 18 casos de referencia
pasan sin API, manteniendo calidad real y habilitación pendientes en ese checkpoint.
Su wheel incluye dataset/entrypoint y coincide con los fuentes de esa verificación. Ruff, arquitectura
y enlaces documentales sin errores. Upgrade/downgrade/upgrade hasta `20261029_22`
y `alembic check` aprobados con invitación y respuesta v1 sintéticas conservadas.
No se repitieron pruebas PWA de la fase 4 porque no cambió su código en esta entrega.

El 2026-10-30 se ejecutó la evaluación real con `gpt-6-luna`: primera corrida 17/18,
un fixture de pausa corregido en `daily-question-eval-v2` y una llamada adicional.
Resultado corregido 18/18, reutilizando sólo respuestas cuya entrada coincidía
exactamente. Total 17 llamadas, costo estándar estimado USD 0,0050673 frente a
USD 0,50 autorizados. Prompt y política permanecieron sin cambios. La distinción
entre autoría previa y posterior al límite tiene regresiones propias. Naturalidad
editorial, revisión humana y dispositivo siguen pendientes; ver la
[evidencia operativa](daily-question-operations.md#corrida-real-sintética--2026-10-30).
