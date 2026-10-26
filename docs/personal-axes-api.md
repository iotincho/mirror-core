# Backend experimental de ejes personales: entregas 1 a 4

Implementa creación, prueba, aceptación versionada, ejecución automática en
notas nuevas y exploración de resultados activos por API. La PWA integra estos
contratos en una sección independiente de Laboratorio. La familia reutiliza `Extractor` y sus artefactos; las citas se
guardan en relaciones, siguiendo el modelo de emociones.

## Organización interna

Reglas/modelos/puertos en `src/core/extractors/personal_axes/`; ciclo del extractor
canónico en `src/use_cases/extraction/personal_axis.py`; generación de criterio en
`src/use_cases/personal_axes/build_specification.py`. OpenAI y la proyección ArcadeDB
se implementan en sus adaptadores `personal_axes.py`, compuestos por
`src/bootstrap/personal_axes.py`. Los perfiles, hashes y formatos conservan sus bytes.

Rutas, definiciones SQL, previews e histórico todavía viven en la familia anterior;
su separación continúa según el [plan](development/personal-axes-migration-plan.md).
El binder de reservas mantiene temporalmente su API, traducida al contexto tipado
de escritura. Este movimiento no modifica el contrato funcional siguiente.

## Configuración y preparación

Aplicar las migraciones Alembic hasta `20261021_17` antes de iniciar los procesos que usan
estos modelos. Mantener el volumen de workspaces compartido entre API, workers y
dispatcher, como el resto de los artefactos durables.

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `PERSONAL_AXES_ENABLED` | `false` | Interruptor global; requiere además el permiso por cuenta. |
| `PERSONAL_AXES_PREVIEW_HOURS` | `72` | Vigencia fija de cada prueba. |
| `PERSONAL_AXES_PREVIEW_CONCURRENCY` | `2` | Notas procesadas simultáneamente por prueba. |
| `PERSONAL_AXES_MAX_PENDING_PREVIEWS` | `10` | Pruebas pendientes simultáneas por dueño. |
| `PERSONAL_AXES_MAX_INPUT_CHARS` | `100000` | Máximo de caracteres originales por nota, sin truncado. |
| `PERSONAL_AXES_MAX_OUTPUT_TOKENS` | `6000` | Límite solicitado al proveedor. |

Se utilizan `LLM_PROVIDER=openai`, `OPENAI_MODEL` y `OPENAI_API_KEY` existentes.
API, workers, dispatcher y admin-api deben compartir el interruptor global. API, workers y dispatcher deben compartir configuración. Las credenciales nunca
forman parte de manifests, especificaciones persistidas ni respuestas.

## Contexto y bienvenida de Laboratorio

`GET /api/laboratory/context` requiere autenticación y devuelve `enabled` (global encendido y permiso vigente de la cuenta),
`welcome_dismissed`, `sample_size=5`, `title_limit=200`, `purpose_limit=8000`,
`adjustment_limit=4000` y `max_adjustments=20`. Responde también con la función
apagada; no necesita abrir el workspace ni llamar a proveedores.

`PATCH /api/laboratory/preferences` acepta únicamente
`{"welcome_dismissed": true}`. La preferencia es monotónica e idempotente y sólo
modifica al usuario autenticado. Visitar la sección o consultar ayuda no escribe
este marcador. Se marca al posponer la bienvenida o comenzar un eje.

La migración `20261021_15` añade un timestamp nullable a `user`; no guarda el
borrador, las notas ni el historial de ajustes. Las mutaciones de esta familia
usan la protección de origen de la aplicación.

## Habilitación por usuario desde administración

La migración `20261021_16` añade `user.laboratory_enabled`, booleano no nullable
con default `false` para cuentas nuevas y existentes. La capacidad efectiva exige
`PERSONAL_AXES_ENABLED=true`, permiso de la cuenta y cuenta activa. El contexto
responde `enabled=false` cuando no se cumplen esas condiciones; las rutas de
pruebas, ejes y resultados responden 404 antes de abrir el workspace.

En el panel LAN, **Usuarios → Ver cuenta → Laboratorio** permite modificar el
permiso. Su contrato, exclusivo del proceso administrativo, es:

```http
PATCH /api/admin/users/{user_id}/laboratory
Content-Type: application/json

{"laboratory_enabled": true}
```

Acepta únicamente ese campo con booleano estricto y rechaza otros orígenes.
Devuelve el usuario con `laboratory_enabled` y `laboratory_global_enabled`, también
presentes en lista/detalle. Repetir el mismo valor es idempotente. El permiso puede
prepararse con el global apagado; el panel explica que todavía no estará disponible.
El proxy LAN sólo permite PATCH en esta ruta y conserva host/puerto para verificar
el origen. Las demás mutaciones siguen bloqueadas. Las lecturas administrativas
mantienen transacciones de sólo lectura; esta escritura usa una transacción propia.

La API pública no registra este endpoint ni acepta el permiso en alta/edición de
cuenta. El permiso se consulta en cada petición y al reservar procesamiento: quitarlo
no necesita reiniciar procesos, no borra datos y no cambia la pausa de los ejes.
Las tareas aceptadas antes del cambio conservan su configuración y pueden terminar.
Volver a dar acceso recupera los mismos ejes y versiones. La navegación de una PWA
abierta se actualiza al recargar; la autorización del backend se aplica inmediatamente.

## Voz de los hallazgos

Las reglas comunes de extracción hablan directamente a quien escribió la nota.
En español respetan las formas de trato, conjugaciones y vocabulario presentes
en la propia narración: voseo, tuteo, ustedeo o combinaciones regionales naturales.
Sin señales claras usan segunda persona de uso compartido, sin imponer una
variante ni inferir origen por nombres o por citas de otras personas. No se
pretende identificar un acento oral a partir de texto. Usan títulos breves y lenguaje cercano, evitando
describir al dueño como «el autor» o producir un informe sobre él. Las etiquetas
siguen siendo temas concisos. El generador de criterios define qué observar y
deja la voz a esas reglas comunes, también en la corrección de evidencias.

Las citas se conservan literalmente, incluida su persona gramatical. Las otras
personas mencionadas permanecen diferenciadas de quien escribe. La cercanía no
habilita agregar emociones, intenciones o certezas ausentes en la fuente.

El seguimiento histórico comprueba también `profile_hash`: una extracción con
instrucciones anteriores no acredita cobertura del prompt actualizado, aunque
se haya autorizado excepcionalmente cambiar una definición en desarrollo sin
crear otra versión. La API normal conserva la inmutabilidad de las versiones.

## Crear y refinar una prueba

Todas las rutas requieren la sesión existente y se publican bajo `/api`.
Este ejemplo usa UUIDs ilustrativos; reemplazarlos por cinco notas propias.

```http
POST /api/laboratory/axis-previews
Idempotency-Key: 5d893fb6-47d7-4420-a8a2-98a4b825cc82
Content-Type: application/json

{
  "draft_id": "f69f064f-59ac-4bdf-a609-f796fca117d1",
  "revision": 1,
  "title": "Ideas para podcast",
  "purpose": "Recuperar propuestas independientes y su desarrollo para retomarlas luego.",
  "document_ids": [
    "409b9552-3a96-4208-81a3-e05dff414166",
    "7949354d-7585-42d8-8a55-6387f512f805",
    "16690587-b626-4eb8-aa50-0e96f592e48e",
    "979d03ce-1f68-4a11-bae5-58965ce596cd",
    "4d0f52d2-979a-4258-b2c5-f6d1868d211d"
  ]
}
```

Devuelve `202` con identidad de prueba, `revision_hash`, vencimiento, etapa,
estado y progreso por nota. El trabajo usa el runtime/outbox existentes. No se
emiten eventos de notas ni se agrega la prueba a sus listados de procesamiento.

Modos:

- `generate`: crea el criterio desde finalidad y ajustes; no recibe prueba anterior.
- `refine`: recibe `previous_preview_id`, mismo `draft_id`, revisión mayor,
  finalidad vigente y `adjustments` con el historial de comentarios del borrador.
  Es una lista acumulativa: debe conservar los comentarios anteriores y agregar
  los nuevos al final; el backend rechaza la pérdida accidental de ese historial.
- `repeat`: repite la muestra con la especificación exacta anterior, sin generar
  otro criterio. Título, finalidad y ajustes deben coincidir con la prueba previa.

La muestra conserva sus IDs y hashes de texto. Para modificarla se envía
`change_sample=true` expresamente, incluso si se mantienen los IDs pero cambió
el contenido. Una prueba anterior vencida no acredita un prompt local: se debe
iniciar una nueva evaluación desde el borrador.

Una edición de eje aceptado inicia otro borrador con `axis_id` y
`base_version_id`. La aceptación comprueba que esa versión siga siendo actual.

## Consultar resultados

- `GET /api/laboratory/axis-previews/{id}`: snapshot/progreso y errores seguros.
- `GET /api/laboratory/axis-previews/{id}/results`: snapshot, resultados por nota
  y grafo temporal. Cada hallazgo conserva título, contenido, etiquetas y citas
  con offsets sobre el texto original. Una nota completada puede tener cero
  hallazgos; los resultados parciales no habilitan aceptación.

Los nodos de prueba representan muestra, documentos, hallazgos y grupos de
etiquetas. Sus identidades no se mezclan con otras pruebas ni se escriben en
ArcadeDB. El esquema completo de respuestas está disponible en OpenAPI.

Cada cita es una relación `HAS_FINDING` entre nota y hallazgo, con `quote`,
`start_char` y `end_char`. Dos citas de un hallazgo producen dos relaciones con
IDs distintos hacia el mismo nodo. Los nodos no guardan las citas. Las relaciones
de muestra y etiquetas no llevan evidencia textual.

El listado por nota conserva `findings[].evidence` como agrupación de lectura.
En el grafo activo la cita se persiste en `HAS_AXIS_FINDING`, no en `AxisFinding`,
siguiendo el modelo de emociones. Repetir la persistencia conserva los IDs y
repara la representación inicial que había guardado `evidence_json` en el nodo.

## Retry, aceptación y versiones

`POST /api/laboratory/axis-previews/{id}/retry` requiere `Idempotency-Key`.
Retoma sólo fallos recuperables de la misma prueba. Generación y extracciones ya
guardadas se reutilizan. Una interrupción del proveedor antes de guardar su
respuesta puede repetir esa llamada; no se promete cobro único ni exactly-once.
Una corrección de evidencia interrumpida requiere una nueva prueba.

```http
POST /api/laboratory/axis-previews/{id}/accept
Content-Type: application/json

{"revision_hash": "<hash devuelto por la prueba evaluada>"}
```

La aceptación requiere las cinco notas completadas, fuentes vigentes y revisión
coincidente. Guarda una versión inmutable de finalidad y especificación exacta,
sin llamadas LLM ni promoción de resultados de muestra. No crea un historial
permanente de comentarios, muestras o iteraciones rechazadas.

Aceptar repetidamente la misma prueba devuelve el mismo eje y versión, incluso
después de limpiar los artefactos temporales. Dos dispositivos no pueden aprobar
cambios sobre una versión base obsoleta.

- `GET /api/personal-axes?offset=0&limit=50`: ejes aceptados del dueño.
- `GET /api/personal-axes/{id}`: definición actual para iniciar otro borrador.

`GET /api/personal-axes/{id}/versions/{version_id}` recupera una definición
histórica propia. `PATCH /api/personal-axes/{id}` con `{"enabled": false}` pausa
nuevas reservas; `true` las habilita otra vez. No borra hallazgos ni modifica
trabajos ya reservados. Una versión nueva conserva el estado de pausa del eje.

## Analizar notas anteriores

El análisis histórico es manual y puede ejecutarse con el eje pausado. No se
dispara al aceptar una versión y no promueve las cinco notas de prueba. Sólo
ejecuta el extractor del eje elegido, con la versión aceptada que se confirma.

| Ruta bajo `/api/personal-axes/{axis_id}` | Uso |
| --- | --- |
| `GET /history/notes` | Candidatos con título, fecha, hash, cobertura y cantidad de hallazgos. |
| `POST /history/batches` | Confirmar selección; responde 202 con el lote durable. |
| `GET /history/batches` | Lotes de la cuenta, del más reciente al más antiguo. |
| `GET /history/batches/{batch_id}` | Progreso y estados por nota paginados. |
| `POST /history/batches/{batch_id}/stop` | Detener pendientes; lo iniciado puede terminar. |
| `POST /history/batches/{batch_id}/retry` | Retomar solamente fallos recuperables. |

Crear y reintentar requieren `Idempotency-Key` UUID. Detener es idempotente sin
clave. Todas las rutas exigen el acceso efectivo a Laboratorio y propiedad del
eje/lote; las mutaciones conservan la protección de origen.

Los candidatos aceptan `q` (título, hasta 200 caracteres), `date_from`, `date_to`
(fechas inclusivas en America/Argentina/Buenos_Aires), `offset` y `limit` (máximo
100). Sus estados son `unanalysed`, `current`, `previous_version`, `changed` e
`in_progress`. `remaining` cuenta los candidatos seleccionables dentro del filtro.
Un `AxisExtraction` vigente acredita cobertura incluso con cero hallazgos.

```json
{
  "version_id": "<UUID de la versión aceptada>",
  "documents": [
    {"document_id": "<UUID propio>", "source_hash": "<SHA-256 del texto>"}
  ]
}
```

La confirmación admite de 1 a 1000 notas distintas. Valida propiedad, versión y
todos los hashes antes de reservar trabajo. Lote, ítems, trabajos y outbox se
guardan en una transacción. La clave se asocia al cuerpo exacto: una respuesta
perdida puede recuperarse sin duplicar el lote aunque las fuentes hayan cambiado
después. Una misma clave con otro cuerpo produce conflicto. Las notas vigentes o
ya en proceso para este eje se registran como omitidas, sin otra llamada al modelo.

La migración `20261021_17` añade `axis_history_batches` y `axis_history_items`.
Cada nota usa el workflow existente de procesamiento durable con la definición
`axis_history_note/1`: extracción → persistencia → fin. Reutiliza
`PersonalAxisExtractor`, `LayerArtifacts`, leases, checkpoints y outbox. El lote se
consulta desde cualquier dispositivo; sólo la solicitud pendiente de confirmación
se conserva localmente, separada del borrador de creación.

El snapshot informa `counts`, `finished`, `retryable`, `items` y `next_offset`.
Además de los estados del ejecutor, los ítems pueden terminar `completed`,
`skipped`, `stopped`, `changed`, `deleted` o `superseded`. Los resultados nuevos
reemplazan atómicamente sólo la capa de ese eje/nota. Una escritura de versión
anterior o de una reserva anterior de la misma versión no reemplaza otra más
nueva, incluso si termina después. Las extracciones automáticas usan la misma
protección de orden; las escrituras concurrentes disputan el mismo documento.

Detener cierra inmediatamente los trabajos pendientes y libera sus leases; sus
entregas anteriores quedan invalidadas por generación. Las notas ya iniciadas
pueden terminar y conservan sus resultados. Reintentar mantiene versión y hashes,
reutiliza checkpoints y sólo reinicia fallos recuperables; si la nota cambió o se
eliminó, termina con ese estado sin analizar otro texto. Los lotes históricos no
entran en el feed SSE ni en el listado general de procesamiento de documentos.

## Ejecución automática y recuperación

La reserva SQL de una nota textual o de audio captura los ejes habilitados del
dueño y la especificación completa de cada versión. La selección se guarda en
la misma transacción que la reserva, antes de escribir archivos o encolar.
Incluso una reserva interrumpida conserva esa selección al recuperarse. El
documento transcrito hereda la del audio: no vuelve a consultar ejes actuales.

El coordinador `document` v5 crea ramas independientes de tipo `personal_axis`,
con claves estables `axis:<uuid>`. `extractor_name` identifica la implementación;
`extractor_key` distingue cada eje y aparece en snapshots/eventos de sus trabajos.
IDs de hijo y extracción dependen de esa clave. Los workflows v2/v3/v4 y los IDs
de hijos anteriores conservan su comportamiento. Usuarios sin ejes siguen en
su workflow anterior.

Un fallo no cancela las otras ramas. El retry de hijo/padre/audio conserva las
versiones reservadas y sólo retoma fallos recuperables. Si la extracción ya creó
su artefacto, la persistencia se reintenta sin proveedor. Deshabilitar globalmente
la función detiene la selección para reservas nuevas y oculta rutas; no cancela
trabajos ya aceptados.

El reprocesamiento explícito existente (individual o por lote) captura los ejes
habilitados actuales junto con los extractores incorporados. Un retry reutiliza
esa captura. La importación de originales por archivo mantiene su política
anterior y no agrega automáticamente ejes personales. Aceptar una versión no
dispara un barrido histórico ni promueve resultados de la muestra.

Cada persistencia reemplaza atómicamente sólo `(document_id, axis_id)`, incluso
cuando el resultado nuevo es vacío. Los demás ejes y emociones se conservan.
Un eje pausado mantiene sus hallazgos consultables. Sin filtro de versión, los
resultados activos pueden proceder de diferentes versiones: cada hallazgo y
relación de evidencia indica su versión real.

La migración `20261021_14` backfillea `extractor_key=extractor_name` para hijos
heredados y conserva sus IDs. Un trigger permite inserciones de escritores
anteriores; el índice único usa padre/clave. El downgrade se rechaza mientras
existan coordinadores v5 o ramas que el esquema anterior no puede representar.
No elimina trabajos para forzar la reversión.

## Exploración progresiva y vista de lista

| Ruta GET bajo `/api` | Respuesta |
| --- | --- |
| `/personal-axes/{id}/neighbors` | Vecinos de un nodo del eje aceptado. |
| `/personal-axes/{id}/tags` | Etiquetas normalizadas y cantidad de notas distintas. |
| `/personal-axes/{id}/findings` | Hallazgos completos paginados para la vista Lista. |
| `/personal-axes/{id}/findings/{finding_id}` | Contenido, citas y origen de un hallazgo. |
| `/laboratory/axis-previews/{id}/neighbors` | Vecinos temporales dentro de la muestra/revisión. |

Las rutas activas admiten `version_id` opcional, validado contra versiones propias
del mismo eje; omitirlo incluye las versiones actualmente representadas en las
notas. `findings` admite además `document_id`. Etiquetas coincidentes de ejes
diferentes nunca forman un mismo grupo. La normalización usa NFC, minúsculas y
espacios; no une sinónimos.

`neighbors` admite `node_id`. Omitirlo abre el eje (o la muestra); los IDs opacos
de la respuesta permiten abrir sucesivamente documentos, hallazgos y etiquetas.
La expansión de una etiqueta pagina hallazgos y agrega sus notas/citas como
contexto acotado. La expansión de una nota pagina hallazgos; la de un hallazgo,
su nota y etiquetas. Una nota procesada sin hallazgos permanece en la raíz.

La paginación usa `limit` entre 1 y 100 (predeterminado 30; etiquetas 50) y
`next_cursor`, que se envía como `cursor` para continuar esa misma rama. El cursor
está ligado al dueño, eje/prueba, versión/revisión y nodo o filtro. Las páginas
activas reflejan datos vivos: un reprocesamiento entre páginas puede cambiar la
vecindad; no constituyen un snapshot congelado de varias solicitudes HTTP.

Los IDs permanecen estables para el mismo resultado. Las relaciones nota–hallazgo
llevan citas, offsets, eje, versión y ejecución; varias citas generan varias
relaciones al mismo hallazgo. Las relaciones con etiquetas no llevan citas. La
lectura valida evidencia contra el original del workspace y su hash. El detalle
y la lista agregan esas relaciones en `evidence` para facilitar la lectura.

Cada respuesta de vecindad incluye `root_id`, ámbito y cursor; la de prueba añade
`revision_hash`. El futuro cliente puede unir ramas sin duplicar IDs y descartar
respuestas de otra revisión. Preservar posiciones/cámara y ocultar tipos de nodo
corresponde a la etapa de UI.

Las consultas de vecindad y lista están limitadas a la página solicitada. El
catálogo cuenta metadatos de hasta 10000 hallazgos por eje/filtro; superar ese
límite produce `422 axis_catalogue_limit`, nunca conteos incompletos. Un grafo
truncado, esquema parcial o fallo de transporte produce un error explícito. La
lectura vacía sólo es válida cuando no hay capa activa o resultados coincidentes.
Las capas personales siguen ocultas en las proyecciones genéricas existentes.

Borrar una nota elimina sus resultados de todos los ejes y sus artefactos, además
de invalidar las pruebas temporales que la usan. Los mensajes tardíos de trabajos
marcados como eliminados no recrean resultados. No se agrega eliminación de ejes.

## Errores y retención

Las respuestas usan `detail` con un código técnico estable, sin texto de notas,
criterios ni respuestas del proveedor. Casos principales:

| Estado | Casos |
| --- | --- |
| `404` | Función deshabilitada, recurso desconocido o ajeno. |
| `409` | Conflicto de clave/revisión/versión base, muestra cambiada, fuente cambiada o lock ocupado. |
| `410` | Prueba vencida conocida o solicitud ya aceptada cuyos temporales se limpiaron. |
| `422` | Solicitud/cursor inválido, nota o catálogo por encima del límite. |
| `429` | Límite de pruebas pendientes por dueño o reserva concurrente de cuota. |
| `503` | Proveedor/modelo sin configurar, grafo incompleto, truncado o no disponible; evidencia inconsistente. |

El dispatcher elimina pruebas vencidas/invalidadas y registros operativos
relacionados, sin interrumpir un worker que conserve su lock. También limpia
entradas huérfanas de transacciones interrumpidas. Tras la limpieza completa un
ID sin registro permanente devuelve `404`. Los mensajes tardíos no recrean el
trabajo eliminado.

El borrado de una nota invalida todas las pruebas que la referencian. Sus
resultados dejan de consultarse o aceptarse y sus temporales se limpian después
de liberar las ejecuciones que puedan seguir activas.

## Validación y evaluación de utilidad

Las integraciones usan PostgreSQL/ArcadeDB desechables y proveedores
determinísticos. Cubren aceptación exacta, refinamiento, aislamiento, reintentos,
transacciones interrumpidas, vencimiento, borrado y reemplazo por eje.

Para evaluar utilidad con LLM real, usar credenciales y cinco notas destinadas a
prueba: crear un eje de valores con la finalidad deseada, revisar evidencia y
ambigüedades, agregar un ajuste y aceptar; repetir con ideas de podcast y revisar
que conserve desarrollo y varios hallazgos por nota. Comparar el hash de la
prueba con el de la versión aceptada. Esta evaluación humana no queda reemplazada
por las pruebas automatizadas ni se ejecuta sobre notas privadas automáticamente.

Validación local realizada el 2026-10-20:

- 27 pruebas nuevas aprobadas con proveedores determinísticos, PostgreSQL y
  ArcadeDB desechables. Incluyen pérdida de conexión SQL en medio de la muestra,
  recuperación de lease y conservación del prompt ya generado.
- 38 pruebas focalizadas de ejes, reprocesamiento y ramas independientes aprobadas.
- Upgrade, downgrade y `alembic check` correctos; Ruff y revisión de whitespace
  correctos.
- La corrida general dio 402 aprobadas, 74 omitidas y una falla preexistente:
  `test_levels_group_labels_deduplicate_runs_and_preserve_evidence`, en
  `tests/integration/test_emotion_exploration.py:114`. Se reprodujo por separado
  en una copia limpia de `HEAD` (`5046410`): espera dos ejecuciones cuando la capa
  de emociones reemplaza la anterior. Este trabajo no cambia ese comportamiento.

No se ejecutó evaluación con LLM real ni se desplegó el cambio.

Revisión del 2026-10-21: se corrigió la ubicación de evidencias para mantener el
modelo de emociones (una relación por cita, sin evidencia en el nodo del hallazgo).
Pasaron 37 pruebas focalizadas de proyección/serialización, circuito de pruebas,
persistencia de ejes y persistencia de emociones, con bases desechables. Se
verificó además el replay de una capa con la representación inicial: elimina la
evidencia del nodo y reconstruye relaciones estables sin duplicarlas.

Entregas 3 y 4, validadas localmente el 2026-10-21:

- Once integraciones nuevas con SQL y grafo reales cubren selección de versiones,
  varias ramas concurrentes del mismo extractor, audio, pausa, retry parcial, persistencia sin
  proveedor (también tras conflictos transitorios del grafo), reserva interrumpida,
  importación, reprocesamiento por lote,
  recuperación de coordinador, aislamiento, borrado, paginación y errores de grafo.
- La API temporal también tiene vecindades paginadas por nodo/revisión. Las rutas
  activas incluyen catálogo, lista/detalle, vecindades y habilitación/pausa.
- La suite general: 417 aprobadas, 74 omitidas y la misma falla preexistente de
  exploración de emociones documentada arriba (`test_emotion_exploration.py:114`).
- La migración `20261021_14` pasó upgrade/downgrade, backfill de un hijo heredado
  conservando sus IDs y `alembic check`. Ruff y whitespace correctos.

La función sigue deshabilitada por defecto. Estos resultados usan proveedores
sintéticos; no acreditan evaluación semántica con LLM real, frontend o despliegue.


## Contrato adicional para exploración en la PWA

- Los nodos `AxisFinding` incluyen `finding_id` explícito para el endpoint de
  detalle, `source_hash` y `tags_complete`. Sus IDs de grafo y los de etiquetas
  son opacos para el cliente.
- El listado y detalle activos incluyen `node_id` y `source_hash`. Cada documento
  de resultados temporales también incluye el hash de contenido.
- Una vecindad de nota/etiqueta devuelve las notas, todas las citas y las etiquetas
  de cada hallazgo descubierto en esa página; no requiere otra petición por
  hallazgo. El límite pagina hallazgos y el contexto está acotado por el contrato:
  hasta 20 etiquetas y 30 citas por hallazgo. Para límite L, el máximo conservador
  es 22L+1 nodos y 50L relaciones. La PWA solicita 12 vecinos por página.
- Las vecindades de prueba incluyen el mismo contexto completo de los hallazgos
  visibles. Al paginar un hallazgo activo, `tags_complete` es falso si faltan
  etiquetas en esa respuesta. El cliente acumula páginas sin descartar ramas.
- `source_hash` es SHA-256 del texto original codificado en UTF-8. Los offsets
  cuentan puntos de código de Python. Antes de resaltar, la PWA verifica el hash,
  convierte los offsets a UTF-16 y compara el fragmento exacto con `quote`.
- Las relaciones contraídas al ocultar tipos son una proyección del cliente:
  conservan las referencias a hallazgos y citas y no agregan relaciones persistidas.
