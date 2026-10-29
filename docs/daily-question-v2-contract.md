# Pregunta diaria v2 · Contratos y backend curado

Estado: etapas 1–3 implementadas localmente. Paquetes curados, persistencia y
rutas listos para entornos migrados a `20261029_18`; flujo PWA integrado, sin
generación LLM. Implementación no desplegada. Ver el [plan](daily-question-v2-plan.md)
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
y teclado virtual reales siguen pendientes. La personalización corresponde a la entrega 4.
