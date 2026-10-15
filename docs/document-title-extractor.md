# Títulos de documentos

Plan aprobado el 2026-10-15:

- [x] Etapa 1: backend, extractor independiente, persistencia recuperable y compatibilidad de respaldos.
- [x] Etapa 2: actualización inmediata de títulos en material, lector, búsqueda, caché local y constelaciones.
- [ ] Etapa 3: generación específica para documentos anteriores sin título, sin repetir otros extractores.

## Contrato y ejecución

`Document.title` sigue siendo un atributo opcional del documento, con máximo de
80 caracteres. El alta guarda el original sin esperar al LLM. La configuración de
las nuevas solicitudes agrega `document_title` a emociones y embeddings en el
workflow de documento v4. Cada hijo tiene su propio estado, ejecución y artefacto.
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

## Etapa 2 — PWA

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

Pendiente: etapa 3, generación específica de títulos para el material anterior.
No se ejecuta un backfill automáticamente.
