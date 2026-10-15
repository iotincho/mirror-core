# Títulos de documentos

Plan aprobado el 2026-10-15:

- [x] Etapa 1: backend, extractor independiente, persistencia recuperable y compatibilidad de respaldos.
- [ ] Etapa 2: actualización inmediata de títulos en material, lector, búsqueda, caché local y constelaciones.
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

Pendientes de las etapas siguientes: actualización inmediata de la PWA y generación
de títulos para el material anterior. No se ejecuta un backfill automáticamente.
