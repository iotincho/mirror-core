# Backend experimental de ejes personales: entregas 1 a 4

Implementa creación, prueba, aceptación versionada, ejecución automática en
notas nuevas y exploración de resultados activos por API. La UI queda para su
etapa de diseño. La familia reutiliza `Extractor` y sus artefactos; las citas se
guardan en relaciones, siguiendo el modelo de emociones.

## Configuración y preparación

Aplicar las migraciones Alembic hasta `20261021_14` antes de iniciar los procesos que usan
estos modelos. Mantener el volumen de workspaces compartido entre API, workers y
dispatcher, como el resto de los artefactos durables.

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `PERSONAL_AXES_ENABLED` | `false` | Habilita rutas y selección de ejes para nuevas reservas. |
| `PERSONAL_AXES_PREVIEW_HOURS` | `72` | Vigencia fija de cada prueba. |
| `PERSONAL_AXES_PREVIEW_CONCURRENCY` | `2` | Notas procesadas simultáneamente por prueba. |
| `PERSONAL_AXES_MAX_PENDING_PREVIEWS` | `10` | Pruebas pendientes simultáneas por dueño. |
| `PERSONAL_AXES_MAX_INPUT_CHARS` | `100000` | Máximo de caracteres originales por nota, sin truncado. |
| `PERSONAL_AXES_MAX_OUTPUT_TOKENS` | `6000` | Límite solicitado al proveedor. |

Se utilizan `LLM_PROVIDER=openai`, `OPENAI_MODEL` y `OPENAI_API_KEY` existentes.
API, workers y dispatcher deben compartir configuración. Las credenciales nunca
forman parte de manifests, especificaciones persistidas ni respuestas.

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
