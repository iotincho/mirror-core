# Plan de implementación del backend de ejes personales

Estado: entregas 1 a 4 implementadas localmente; frontend y evaluación con LLM
real pendientes. Ver [API y operación](personal-axes-api.md).

Base: [diseño del modelo y las pruebas](personal-axes-backend-design.md).

## Alcance y resultado esperado

Implementar el backend del issue #51: generar/refinar un criterio, probar cinco
notas, consultar hallazgos/grafo, aceptar una definición versionada, ejecutar los
ejes habilitados sobre notas nuevas y explorar sus resultados mediante API.

Todo el desarrollo pertenece a `mirror-core`. El frontend del Laboratorio y su
diseño visual quedan para otra etapa. La constelación actual mantiene su contrato.
No se modifica el prompt ni el comportamiento del extractor de emociones.

La familia vive en `src/extractors/personal_axes/` e implementa `Extractor`.
Reutiliza `ExtractorProfile`, `ExtractionOutput`, `LayerArtifacts`,
`ProcessingArtifacts`, `DocumentStore` y `ExtractorRegistry`. No agrega otra
interfaz de extracción ni otro almacenamiento de resultados equivalente.

## Criterio de exploración acordado para la implementación real

El Laboratorio utiliza un solo grafo con notas, hallazgos y etiquetas. Las
referencias debajo del gráfico permiten mostrar u ocultar tipos de nodo. La
finalidad del eje se consulta en un desplegable cerrado por defecto.

La exploración debe crecer al tocar nodos, sin un botón de expansión global:

- Consultar los vecinos del nodo seleccionado, con límites y paginación por
  rama, tanto en pruebas temporales como en ejes aceptados. El backend valida
  propietario y ámbito de prueba/eje/versión antes de devolver cualquier vecino.
- Mantener identidades estables para combinar vecinos sin duplicar nodos o
  relaciones, conservando los hallazgos y las citas que justifican cada enlace.
- El cliente incorpora las ramas nuevas alrededor del nodo seleccionado,
  conserva las ramas abiertas, las posiciones manuales, el zoom y el paneo.
  Carga, reintento y fin de vecinos corresponden a cada nodo; una respuesta tardía
  no debe modificar otra prueba ni otro eje.
- Ocultar tipos es una decisión visual sobre lo ya explorado; no carga el grafo
  entero. Los enlaces resumidos conservan el acceso a los hallazgos y las citas.
- No mostrar el listado auxiliar «Elementos y conexiones». Mantener una vista
  Lista accesible para leer los mismos resultados y sus evidencias.

El backend ofrece vecindades paginadas para muestras y resultados activos,
con identidades y ámbitos explícitos. El prototipo simula vecinos con datos
locales; la integración del frontend, conservación de cámara/posiciones y diseño
visual quedan pendientes. Las pruebas del backend validan paginación y permisos.

## Hito A: creación, pruebas y aceptación utilizables por API

### 1. Contratos, configuración y modelo persistente

Cambios:

- Crear los modelos de finalidad/especificación y payload de hallazgos dentro de
  `src/extractors/personal_axes/`.
- Implementar `personal_axes` y `personal_axis_versions`, su repositorio y las
  restricciones del diseño: propietario, versiones inmutables, número único,
  versión actual del mismo eje y aceptación idempotente por prueba.
- Agregar una migración posterior al head vigente al implementar; registrar los
  modelos en `migrations/env.py`. No fijar ahora un número que pueda quedar viejo.
- Separar hash de especificación ejecutable de identidad del eje y de la revisión
  local: guardar una definición aceptada no altera el prompt ya evaluado.
- Configurar habilitación experimental del backend, retención de pruebas,
  concurrencia, límites de entrada/salida y ajustes de proveedor. Usar el modelo
  configurado existente inicialmente; no introducir un cambio global de modelo.

Validación de salida:

- Migración desde el esquema vigente y restricciones verificadas en PostgreSQL.
- Crear/leer versiones sólo desde el propietario; no se aceptan referencias
  cruzadas entre ejes ni se sobrescriben versiones aceptadas.
- Los contratos representan cero y múltiples hallazgos, evidencia y etiquetas.

### 2. Generador/refinador y extractor concreto

Cambios:

- Implementar `prompt_builder.py` y el adaptador LLM para generar/refinar el
  criterio con finalidad, criterio previo e historial temporal de ajustes.
- Ensamblar el `ExtractorProfile` efectivo con reglas y formato fijos del backend.
  El modelo genera el criterio semántico; no redefine el esquema ni permisos.
- Implementar `PersonalAxisExtractor(Extractor)`: `produce`, `validate_payload`,
  `write_layer` y `produce_for_run` cuando se necesiten checkpoints de corrección.
- Reutilizar el sobre común; ubicar título, contenido, citas y etiquetas dentro
  de `ExtractionOutput.payload`. Validar citas contra el original y calcular
  offsets en el backend. Conservar advertencias de correcciones aplicadas.
- Limitar a una corrección de salida inválida por ejecución. Guardar los
  checkpoints para que una respuesta recuperable no se genere otra vez.
- Implementar el almacenamiento de la capa activa detrás del escritor del
  extractor. La familia administra sus tipos e índices de ArcadeDB y verifica
  transaccionalmente lo escrito, como las capas existentes.
- Representar ejecuciones y hallazgos locales al documento; conservar etiquetas
  como atributos/relaciones locales y agrupar entre notas mediante una proyección
  de lectura. Evitar nodos globales que compliquen reemplazo y borrado.
- Conservar la regla de emociones: una relación por cita, con texto y offsets.
  No guardar `quote` ni `evidence_json` en `AxisFinding`; la vista previa expone
  las mismas evidencias sobre sus enlaces nota-hallazgo.
- Reemplazar atómicamente sólo resultados de `(document_id, axis_id)`, conservando
  los de otros ejes y emociones. Una ejecución vacía también reemplaza su capa.
- Registrar un constructor `personal_axis`; inyectar especificación y almacén de
  artefactos, con raíz temporal para pruebas y raíz normal para ejecución activa.

Validación de salida:

- `extract(..., dry_run=True, run_id=...)` produce artefactos recuperables sin
  escribir en ArcadeDB; una segunda llamada reutiliza el resultado guardado.
- Citas inexistentes/ambiguas, notas largas y respuesta truncada fallan de forma
  explícita; una lista vacía válida no falla. No se trunca silenciosamente la nota.
- Un fallo de persistencia conserva resultados previos y se recupera con
  `persist(output)` sin construir un proveedor ni repetir extracción.
- Dos ejes sobre la misma nota no se borran mutuamente; las emociones se conservan.

### 3. Solicitud y workflow de pruebas temporales

Cambios:

- Implementar `preview_store.py` componiendo `ProcessingArtifacts` para la entrada
  y `LayerArtifacts` bajo el directorio temporal de cada prueba para resultados.
- Agregar solicitud/reserva idempotente, validación de cinco notas propias
  distintas y manifiesto inmutable con hashes, revisión local y vencimiento.
- Diferenciar generar, refinar, repetir con el mismo criterio y cambiar muestra.
  Refinar conserva IDs y hashes; cambiar muestra requiere una entrada explícita.
- Registrar `axis_preview` v1 en `src/processing/workflows.py` y agregar el caso de
  uso `ProcessAxisPreview`:
  `prompt_generation → sample_extraction → preview_projection → done`.
- Coordinar las cinco llamadas a `Extractor.extract` en dry run, con concurrencia
  limitada e IDs derivados de prueba/nota. No crear otro motor de extracción.
- Reutilizar leases, fencing, broker y outbox; agregar manejo específico de fallos
  de generación, extracción, evidencia, expiración y fuente modificada.
- Reservar primero, escribir entrada inmutable y publicar sólo cuando sea válida.
  Incorporar reconciliación de reservas interrumpidas y limpieza de huérfanos.
- Agregar consulta y retry propios para pruebas; no pasar por el camino actual
  que interpreta cualquier recurso no documental como audio.
- Implementar desde esta etapa vencimiento, limpieza e invalidación por borrado.
  Filtrar pruebas de los listados/eventos destinados a notas de la PWA actual.

Validación de salida:

- Caídas después de generar criterio o completar algunas notas conservan sus
  checkpoints; entregas duplicadas no duplican pruebas ni resultados guardados.
- Se puede consultar progreso y resultados parciales, pero sólo se acepta una
  muestra con sus cinco notas completadas y válidas.
- Vencimiento, borrado y ejecución concurrente no dejan resultados accesibles de
  una nota eliminada ni permiten que un mensaje tardío recree una prueba purgada.
- Las iteraciones no se mezclan ni aparecen como procesamiento de una nota.

### 4. API de pruebas, proyección y aceptación versionada

Cambios:

- Registrar rutas autenticadas en `src/api/router.py`, manteniendo el prefijo
  público `/api` que ya aplica el proxy.
- Exponer creación, snapshot, resultados y retry de pruebas; listado/detalle de
  ejes aceptados; aceptación de un eje nuevo o una nueva versión del existente.
- Devolver en las respuestas identidades de prueba, revisión y especificación,
  vencimiento y estados por nota. Mantener solicitudes/respuestas documentadas
  en OpenAPI para diseñar el frontend después.
- Construir lista y grafo temporales desde `ExtractionOutput.payload`, con IDs
  acotados a la prueba. No persistir ni promover esos hallazgos a ArcadeDB.
- En aceptación validar prueba vigente, revisión, fuentes y cinco resultados.
  Para una edición comprobar mediante bloqueo la versión base del eje.
- Copiar la especificación exacta evaluada y registrar eje/versión en una
  transacción. Aceptar no llama al LLM ni a `extractor.persist`.
- Reconocer aceptaciones repetidas incluso después de limpiar los archivos de
  prueba. Aplicar 404 a recursos ajenos/desconocidos, 409 a conflictos y 410 a
  pruebas vencidas conocidas.

Validación de salida:

- Flujo HTTP completo: descripción → prueba → ajuste → nueva prueba → aceptación.
- Ninguna iteración rechazada crea ejes o versiones permanentes.
- Respuesta perdida, doble aceptación y edición simultánea desde dos dispositivos.
- Título, finalidad, prompt y configuración guardados coinciden con lo evaluado.
- Pruebas y resultados inaccesibles desde otro usuario, incluso con UUID conocido.

## Hito B: ejecución automática y exploración activa por API

### 5. Identidad de rama y captura de especificaciones por usuario

Cambios:

- Separar tipo de implementación (`extractor_name`) de identidad de rama
  (`extractor_key`): `emotions`, `document_embeddings`, `document_title` y
  `axis:<uuid>`. Mantener versiones del prompt fuera de esa identidad estable.
- Migrar/backfillear la clave en hijos existentes y ajustar índice único por
  padre/clave, generación de IDs, comparación de hijos y snapshots de procesamiento.
- Incorporar coordinador de documento v5 para configuraciones con ejes personales;
  conservar las definiciones v2/v3/v4 y el comportamiento de trabajos ya aceptados.
- Revisar conjuntamente `extractors_and_wait`, `wake_parent`, recuperación de
  padres y retry de descendientes: extender los caminos v4 para incluir v5.
- Resolver ejes habilitados del dueño al reservar una nota nueva, fijando IDs de
  versión, profile y configuración. Persistir esa selección junto con la reserva.
  Replays/retries recuperan el snapshot original; no consultan la versión actual.
- Propagar la selección desde el audio a su documento transcrito. Activar un eje
  mientras se transcribe no modifica la configuración ya aceptada para ese audio.
- Para el reprocesamiento explícito existente, incluir todos los ejes habilitados
  junto con los extractores incorporados; retry sigue retomando los ya fijados.
- Mantener la restauración por archivo sin agregar automáticamente ejes personales
  al historial importado. No activar un barrido de notas antiguas al aceptar un eje.

Validación de salida:

- Una nota textual y una de audio ejecutan dos ejes y los extractores incorporados
  como ramas independientes, con identidad y resultados diferentes.
- Cambiar versión después de reservar una nota no altera su ejecución/retry.
- Un eje fallido no cancela hermanos; retry de padre/hijo no repite éxitos.
- Trabajos anteriores, usuarios sin ejes, importación y reproducción idempotente
  conservan sus contratos y comportamiento previo.

### 6. Consultas activas, habilitación y ciclo de vida

Cambios:

- Agregar proyección de lectura propia para `Nota → Hallazgo → Etiqueta`, con
  agrupación por eje y etiqueta normalizada; nunca unir ejes por compartir texto.
- Ofrecer catálogo de etiquetas, vecindades desde nota/etiqueta y detalle de
  hallazgo con contenido, evidencias y versión de origen. Aplicar paginación,
  límites y truncamiento explícito; contar notas distintas.
- Conservar la versión de cada hallazgo incluso cuando una agrupación incluya
  resultados de distintas versiones del mismo eje. Aprobar una versión no
  reemplaza hallazgos anteriores hasta un reprocesamiento explícito de esa nota.
- Exponer habilitar/pausar el eje: afecta reservas nuevas; los trabajos aceptados
  conservan su selección. Los resultados ya guardados siguen disponibles.
- Completar borrado por documento y limpieza de todos sus artefactos, incluyendo
  pruebas que lo referencien. No implementar eliminación completa de ejes aún.
- Mantener endpoints y proyecciones actuales de emociones. Las consultas nuevas
  tendrán rutas específicas para que su diseño no fuerce cambios en la UI actual.
- Ocultar las nuevas capas personales en la proyección genérica que consume hoy
  la UI (usando la marca de visibilidad existente); las rutas propias del
  Laboratorio consultan su proyección explícita. Así los resultados activos no
  aparecen accidentalmente en los lectores actuales antes de diseñar esa UI.

Validación de salida:

- Agrupación entre notas del mismo eje, sin cruces entre ejes/usuarios.
- Contenido largo y varias citas recuperables por API, con origen verificable.
- Persistencia y lecturas con ArcadeDB real, incluidos reemplazo, borrado, cero
  hallazgos, límites y errores de disponibilidad; nunca un falso resultado vacío.
- Pausa, nueva versión y reprocesamiento conservan las reglas de snapshot y origen.

## 7. Validación integrada y documentación de entrega

- Probar con proveedores determinísticos el recorrido completo de ambos hitos,
  incluyendo recuperación de workers, outbox, aceptación y persistencia ambigua.
- Ejecutar regresiones de emociones, capas independientes, ingesta, audio,
  reprocesamiento, archivos, borrado, aislamiento y feed de procesamiento.
- Ejecutar migraciones y comprobación de metadata; Ruff y `git diff --check` sobre
  el alcance cambiado. Usar `.venv/bin/python -m pytest` para las suites del repo.
- Preparar fixtures sintéticos para finalidad de valores e ideas de podcast;
  no guardar notas personales en fixtures, documentación o registros.
- Preparar un procedimiento de evaluación LLM real con cinco notas por finalidad,
  generación, al menos un refinamiento, aceptación y comprobación del prompt.
  Ejecutarlo sólo con credenciales de prueba y datos destinados a esa evaluación.
- Documentar endpoints y ejemplos HTTP, errores, configuración, retención, pausa,
  recuperación y la diferencia entre retry, nueva prueba y reprocesamiento.
- Informar por separado qué se validó con proveedores determinísticos, bases
  reales y LLM real. Una integración local no demuestra despliegue ni utilidad
  semántica de los hallazgos.

## Secuencia de entregas revisables

1. **Base del extractor:** etapas 1–2; modelos, migración, generación, dry run y
   persistencia propios usando la interfaz común.
2. **Circuito de pruebas:** etapas 3–4; workflow temporal, API, limpieza, grafo
   temporal y aceptación. Cierra el hito A.
3. **Ejecución en notas nuevas:** etapa 5; identidad de rama, snapshots por dueño,
   texto/audio y recuperación compatible con trabajos anteriores.
4. **Exploración y cierre:** etapa 6 y validación integrada; API activa, pausa,
   regresiones y documentación. Cierra el hito B.

Cada entrega incorpora sus pruebas significativas; no se posterga toda la
validación al final. Estas unidades permiten commits o PRs revisables de alcance
acotado. La habilitación experimental permanece apagada por defecto; la evaluación con
LLM real y la habilitación del entorno se realizan por separado.

## Límites de este plan

No incluye cambios en `mirror-pwa`, mockups/UI, despliegue, publicación de imágenes,
reprocesamiento masivo automático, descubrimiento de ejes, equivalencias por
embeddings, segmentación nueva de notas largas ni cambios en transcripción.
Las muestras no se promueven automáticamente al grafo activo. La eliminación
completa de ejes y una pantalla permanente de administración avanzada se difieren.

El diseño previo detalla puntos 1 y 2 del trabajo original. Este plan amplía la
secuencia al backend completo; las políticas nuevas de integración (restauración,
pausa y reprocesamiento explícito) fueron implementadas en las entregas 3 y 4.
