# Títulos de documentos

Contrato del extractor, actualización de títulos en la PWA y generación para
documentos anteriores sin título, sin repetir otras capas.

## Ubicación del código

Las responsabilidades están separadas según la arquitectura vigente:
modelos/profile/puertos en `src/core/extractors/document_title.py`; ciclo y escritura
coordinada en `src/use_cases/extraction/`; programación acotada al leer en
`src/use_cases/documents/ensure_document_titles.py`; implementaciones filesystem,
ArcadeDB y OpenAI en `src/adapters/`. `src/bootstrap/documents.py` inyecta
configuración y dependencias del workspace. Los módulos anteriores de títulos
se retiraron al actualizar sus consumidores.

`TitleReadPolicy` contiene límite/habilitación, sin claves. `TitleScheduling`
expone programación durable sin sesiones SQL al caso de lectura; bootstrap lo
conecta al backfill en `src/use_cases/documents/backfill_document_titles.py`, que
usa transacciones de procesamiento sin sesiones SQL. El registro de workflows y
su configuración se componen en bootstrap; ver [arquitectura](../ARCHITECTURE.md).

## Contrato y ejecución

`Document.title` sigue siendo un atributo opcional del documento, con máximo de
80 caracteres. El alta guarda el original sin esperar al LLM. La configuración de
las nuevas solicitudes agrega `document_title` a emociones y embeddings en el
workflow de documento v4 o v5 si hay ejes habilitados. Cada hijo tiene su propio
estado, ejecución y artefacto.
Los trabajos ya aceptados conservan sus extractores y configuración originales.
El audio genera el título después de transcribir y crear su documento; importación,
texto pegado y carga de archivos usan el mismo procesamiento de documentos.

`DocumentTitleExtractor` posee su contrato, profile `document-title/v1`, validación
y persistencia. Su proveedor OpenAI usa Responses con salida estructurada, según
la [documentación oficial](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
Proveedor, modelo y prompt quedan fijados al aceptar la solicitud. Inicialmente se
usan `LLM_PROVIDER` y `OPENAI_MODEL`, como para emociones. La generación recibe el
texto completo como datos, sin interpretar instrucciones dentro de la nota.

El objetivo editorial es un título específico de 4–8 palabras, preferentemente
menos de 60 caracteres, en el idioma de la nota y sin inventar información. Para
notas muy breves puede tener menos palabras. El contrato rechaza títulos vacíos,
mayores a 80 caracteres, multilínea, con controles, espacios irregulares o comillas
envolventes. La adecuación semántica se confía al modelo; no se acreditó con un LLM real.

## Persistencia y recuperación

El resultado se guarda primero en el artefacto durable de la ejecución. Persistirlo
no necesita proveedor ni credenciales del LLM. Actualiza solamente el título del
JSON canónico y después su proyección en ArcadeDB. No hay una transacción entre
ambos almacenes: si falla la proyección, el título canónico y el artefacto permanecen
disponibles para reintentar sin volver a generar. El adaptador verifica el texto
original y el resultado del cambio dentro de una transacción del grafo; usa `MATCH`
para no recrear originales ausentes. No crea entidades, relaciones ni capas
visualizables adicionales.

Un título existente se conserva, incluso si proviene de una importación con otro
formato editorial. Una ejecución atrasada tampoco reemplaza un título asignado
después de extraer. No se implementó regeneración explícita ni edición manual.
Los guards existentes del runtime excluyen ejecuciones duplicadas y bloquean el
borrado/reprocesamiento exclusivo mientras trabajan los extractores. Persistir
requiere el artefacto del workspace y el mismo contenido original.

Un fallo del título no elimina la nota ni detiene sus hermanos. Se conserva el
comportamiento del coordinador: si una rama falla, informa `extractors_failed`;
los reintentos recuperables continúan solamente las ramas fallidas. La API
existente expone los estados por extractor y permite reintentar el hijo.

## Respaldos

La exportación incluye el título actual. Al reimportar se comparan todos los campos
originales, incluido ID, metadata y fechas, excluyendo únicamente `title`. Para
documentos existentes se conserva el título actual; para documentos nuevos se
restaura el del respaldo. Las nuevas reservas identifican el original sin título
y registran `archive_identity: original/1`. La recuperación de reservas usa esa
misma identidad. Los recibos anteriores conservan su hash y pueden reimportarse
después de cambiar el título, una vez comprobado el original existente bajo lock.

## Validación

Pruebas unitarias: contrato de títulos, respuesta estructurada/rechazo del proveedor,
dry run, reuso de artefacto, fallos de archivo/grafo, preservación del original y de
títulos importados, workspace ajeno, cambios de contenido, documentos eliminados,
configuración aceptada y compatibilidad de recibos de importación antiguos/nuevos.

Integración opt-in: `tests/integration/test_document_title_processing.py` usa
PostgreSQL migrado y ArcadeDB aislados, con proveedor determinístico. Verifica
título disponible antes que emociones, retry de proyección sin repetir LLM, audio
sin repetir transcripción, reprocesamiento que conserva títulos y recuperación/
reimportación de respaldos. No requiere migraciones nuevas ni modifica el contrato HTTP.

Validación local del 2026-10-15: suite general 205 aprobadas y 111 integraciones
omitidas por falta de servicios opt-in; ejecución separada con PostgreSQL 17 y
ArcadeDB 26.9.1 temporales: 17 integraciones aprobadas (4 de títulos y 13 de
extractores independientes, emociones y embeddings). Ruff y `git diff --check`
sin errores. Los contenedores temporales se eliminaron al finalizar. Sin despliegue,
llamadas a proveedores reales ni evaluación editorial de títulos generados por un LLM.

## Títulos en la PWA

Implementada localmente el 2026-10-15 en `mirror-pwa`, misma rama
`feat/app-refresh-stage1`, commit `15e200d`. Los eventos de `document_title`
reconcilian el título sin adoptar/completar el trabajo padre. Los audios obtienen
el título desde que existe el documento, sin esperar al resto de extractores.
Lista, búsqueda y lector abierto reflejan los cambios; las copias sincronizadas
conservan el título en IndexedDB para reabrir sin servidor. Las identidades se
vinculan por documento confirmado o metadata de audio explícita y no ambigua;
las copias pendientes y el material original se preservan.

Constelaciones hidrata sólo etiquetas de notas sobre el grafo existente. Mantiene
canvas, posiciones, selección, filtros, zoom/pan y snapshots de exploración. Los
lectores, breadcrumbs y pasos anteriores muestran los títulos actuales sin
volver a cargar relaciones. La primera línea del contenido sirve de referencia
provisional antes que nombres de archivos cuando todavía no hay título.

Validación: 156 pruebas aprobadas en 17 archivos PWA (50 focalizadas en títulos,
procesamiento diferido, material y constelaciones), build, lint, verificación de
artefactos PWA y diff sin errores. Incluye lectura tras reabrir sin servidor,
audio/transcripción preservados y respuestas tardías al cambiar de cuenta. Las
pruebas usan JSDOM, IndexedDB simulado, Cytoscape headless y HTTP/SSE simulados;
quedan pendientes aceptación en navegador/dispositivo real y flujo con LLM real.
Documentación detallada en `mirror-pwa/docs/document-titles.md`. Sin despliegue.

## Material anterior y backfill

Implementada localmente el 2026-10-15, sobre `feat/app-refresh-plan`.
`BackfillDocumentTitles` inspecciona originales de un workspace y encola un
coordinador de documento v4 cuya única extracción es `document_title`. Se persiste
el original en el grafo antes de generar el título, por lo que también funciona
si un documento antiguo todavía no tiene vértice. No repite transcripción,
emociones ni embeddings, ni elimina sus resultados existentes.

Cada documento tiene una clave determinística por workspace. Recibo, trabajo,
evento y outbox se confirman juntos; repetir el comando no duplica trabajos.
Cambiar el modelo/profile configurado tampoco genera otra ejecución para un
documento ya aceptado: conserva la configuración y artefactos originales.
Los fallos recuperables del propio backfill retoman el trabajo existente, incluso
si el título ya está en el original y sólo falta persistirlo en el grafo. Los
fallos permanentes se informan sin crear otra llamada al LLM automáticamente.

Los documentos con título, ocupados, ausentes o marcados como eliminados se
omiten. Título, existencia y disponibilidad se revisan otra vez bajo el guard
exclusivo antes de encolar; el retry también comprueba que no haya otro workflow
activo. Las respuestas muestran solamente IDs y estados, sin contenido, títulos
ni credenciales.

### Uso

Ejecutar con la versión actual del código, la configuración y el almacenamiento
compartido del backend. `WORKSPACE_ID` debe contener el UUID del usuario dueño del
workspace, no el nombre de la base de ArcadeDB. La vista previa requiere acceso
a PostgreSQL y al workspace activo, pero no credenciales del LLM ni consultas al
grafo. Por defecto sólo inspecciona:

```bash
python -m src.bootstrap.title_backfill --workspace "$WORKSPACE_ID" --limit 100
```

Para encolar el lote revisado:

```bash
python -m src.bootstrap.title_backfill --workspace "$WORKSPACE_ID" --limit 100 --apply
```

`--apply` verifica la configuración del proveedor antes de escribir. Dispatcher
y workers deben estar activos para consumir el outbox y ejecutar las extracciones;
el comando no llama al LLM directamente ni espera a que terminen los trabajos.
`--limit` limita nuevos trabajos/reintentos por invocación (100 por defecto).
Repetirlo permite avanzar con los siguientes documentos sin duplicar los anteriores.

Para seleccionar documentos concretos se puede repetir `--document`:

```bash
python -m src.bootstrap.title_backfill --workspace "$WORKSPACE_ID" --document "$DOCUMENT_ID"
```

El JSON informa `mode`, `workspace`, `limit`, `total_documents`, `counts` y los IDs
de documentos/trabajos con sus estados:

| Estado | Significado |
| --- | --- |
| `eligible` / `retryable` | Se crearía un trabajo o se retomaría uno recuperable; vista previa |
| `deferred` | Pendiente fuera del límite del lote |
| `queued` / `retried` | Trabajo nuevo encolado o trabajo anterior retomado |
| `already_scheduled` / `completed` | El propio backfill ya lo tiene en curso o completado |
| `titled` | Tiene título; se conserva |
| `busy` | Otro procesamiento ocupa el documento; se puede revisar más tarde |
| `failed` | Fallo permanente; no se vuelve a generar automáticamente |
| `missing` / `deleted` | Original ausente o marcado como eliminado; no se recrea |

### Validación y estado operativo

Suite general: 210 pruebas aprobadas y 119 integraciones omitidas por falta de
servicios opt-in. Ejecución separada con PostgreSQL 17 y ArcadeDB 26.9.1
temporales: 25 integraciones aprobadas, incluidas 8 de backfill. Cubren vista previa
sin escrituras, límites/lotes, encolado concurrente sin duplicados, creación del
vértice faltante, conservación de originales/títulos, aislamiento de workspace,
tombstones, rollback de recibo/evento/outbox, retry con el mismo artefacto y
protección ante un procesamiento que se encoló después de la vista previa.
Ruff, ayuda de la CLI y `git diff --check` sin errores. Los contenedores temporales
se eliminaron al terminar.

En esa validación no se ejecutó el backfill sobre notas reales, no se consultó un
proveedor real ni se desplegó. La CLI sirve para mantenimiento opcional; la
generación bajo demanda descrita abajo es el mecanismo habitual.

## Generación bajo demanda al leer

Los GET autenticados de `/v2/documents/{document_id}`, `/v2/documents` y la lista
legacy `/documents` intentan encolar la extracción si falta el título canónico.
La etiqueta provisional local o el fallback de primera línea no cuentan como
`Document.title`: no impiden generar un título real. El GET devuelve el original
sin esperar al LLM; el worker actualiza el título y los eventos existentes lo
reflejan en la PWA.

`EnsureDocumentTitles` limita la creación a **5 trabajos nuevos por consulta**,
configurable con `DOCUMENT_TITLE_READ_LIMIT` (0–100). El valor 0 deshabilita sólo
la generación disparada por lecturas; las notas nuevas mantienen su extractor de
títulos normal. También debe estar configurado el proveedor/modelo/API key del
backend. Si falta esa configuración, no se crean trabajos con un modelo inválido.
La lista filtra el trabajo existente por lotes de hasta 100 IDs para que los
documentos ya procesados o fallidos no bloqueen los siguientes pendientes.

La coordinación reutiliza la identidad y el recibo determinístico del backfill.
Los guards y la restricción única de PostgreSQL evitan duplicados entre lecturas,
entre GET individual/lista y entre lecturas/CLI. Bajo el guard se revisa de nuevo
el título y se detectan tanto los trabajos `document_title` como los coordinadores
normales que ya lo incluyen en su configuración. También se respetan reservas de
subida/importación aún no aceptadas, que existen antes de publicar su trabajo.
Esto cubre la ventana en la que el archivo original ya puede leerse pero todavía
no existe el trabajo normal en `processing_records`.

Los GET no reactivan trabajos terminales, aunque el error haya sido recuperable:
los reintentos automáticos y su límite pertenecen al worker. Después de agotarlos,
el retry explícito por API o CLI conserva el trabajo y sus artefactos. Los fallos
permanentes tampoco generan otro trabajo con cada lectura. Los documentos
ocupados, eliminados, ya titulados o pertenecientes a otro workspace no se encolan.
Si falla la coordinación del título, se conserva la lectura normal del original;
se registra únicamente workspace y tipo de error, sin contenido ni configuración.
Una lectura posterior puede reintentar un encolado que no llegó a confirmarse.

No se agrega una migración de datos, un barrido global ni una tarea al iniciar el
backend. Sólo se consideran los documentos devueltos por las consultas del usuario.
Dispatcher/outbox/workers siguen siendo los responsables de ejecutar el trabajo;
no se usa una tarea en memoria asociada a la vida del request HTTP.

Validación: 216 pruebas de regresión aprobadas y ejecución separada con PostgreSQL
17 y ArcadeDB 26.9.1 aislados: 34 integraciones aprobadas, incluidas 9 de lecturas.
Cubren GET concurrentes al detalle/listas con un solo recibo/trabajo/outbox,
respuesta sin llamada al LLM, actualización posterior del título, límite por GET,
respeto del procesamiento normal antes de crear hijos, reservas previas a aceptar
una subida, fallo de encolado sin perder la lectura, aislamiento de workspace,
reintentos agotados que no se reinician al consultar y nueva comprobación bajo
guard tras una vista previa desactualizada. Ruff y diff sin errores. Sin despliegue
ni generación sobre notas reales; se usaron proveedores determinísticos de prueba.
