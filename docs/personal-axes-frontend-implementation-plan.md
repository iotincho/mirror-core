# Plan de implementación del frontend de Laboratorio

Fecha: 2026-10-21. Estado: implementación realizada en los árboles de trabajo de
`mirror-core` y `mirror-pwa`, siguiendo la autorización posterior a este plan.
El análisis de abajo conserva la referencia al estado inicial; los ajustes A–D
ya están implementados. El [informe de implementación](laboratory-implementation-report.md)
detalla los cambios y la validación actual.

Referencias revisadas:

- Backend de `mirror-core` en `7e0c427`; prototipo actualizado en `acaeed2`.
- PWA `mirror-pwa` en `3f1360f`, con árbol de trabajo limpio al revisar.
- [Prototipo navegable](../prototypes/laboratorio/README.md),
  [API implementada](personal-axes-api.md) y
  [plan del backend](personal-axes-backend-implementation-plan.md).

## 1. Resultado y alcance

Implementar el Laboratorio como sección experimental independiente de
Constelaciones, siguiendo el prototipo aprobado:

- Inicio compacto con ejes, borrador para continuar y acción para crear.
- Bienvenida breve sólo sin ejes ni borrador y mientras no se haya descartado o
  comenzado la creación. Ayuda siempre accesible, con tres apartados desplegables.
- Creación: título/finalidad → cinco notas → prueba → ajustes → aceptación.
- Eje aceptado: descripción cerrada por defecto, pausa, edición por nueva versión,
  lista de resultados y exploración progresiva.
- Un grafo con notas, hallazgos y etiquetas. Las referencias inferiores muestran
  u ocultan tipos. Tocar nodos abre ramas; no hay expansión global ni listado
  auxiliar «Elementos y conexiones». Lista mantiene una alternativa accesible.

Los borradores y comentarios de creación siguen siendo trabajo local. El servidor
conserva sólo pruebas temporales y las definiciones aceptadas versionadas. La
preferencia de bienvenida no contiene el proceso de creación.

No incluye eliminar ejes, reprocesamiento histórico automático, modificar la
extracción de emociones ni editar el prompt técnico desde el flujo principal.
Aceptar un eje no convierte los resultados de prueba en resultados activos.

## 2. Qué ofrece realmente el backend

| Recorrido | Contrato existente bajo `/api` | Uso previsto |
| --- | --- | --- |
| Ejes | `GET /personal-axes` y `GET /personal-axes/{id}` | Inicio y definición actual; paginación por offset. |
| Crear/refinar/repetir | `POST /laboratory/axis-previews` | Solicitud durable con `Idempotency-Key`, revisión y cinco notas. |
| Avance | `GET /laboratory/axis-previews/{id}` | Estado global, etapa, vencimiento y estados/errores por nota. |
| Resultados temporales | `GET /laboratory/axis-previews/{id}/results` | Hallazgos completos, varias citas por hallazgo y grafo de muestra. |
| Reintento | `POST /laboratory/axis-previews/{id}/retry` | Misma prueba, con clave idempotente propia del intento. |
| Aceptación | `POST /laboratory/axis-previews/{id}/accept` | Acepta el `revision_hash` evaluado; replay idempotente. |
| Versiones y pausa | `GET .../versions/{version_id}`, `PATCH /personal-axes/{id}` | Detalle de versión y estado `enabled`. |
| Resultados activos | `GET .../findings`, `GET .../findings/{finding_id}` | Lista y detalle con procedencia real. |
| Etiquetas | `GET .../tags` | Catálogo paginado por eje y versión opcional. |
| Exploración | `GET .../neighbors` de eje o prueba | `node_id` y cursor propios de cada rama. |

La reserva de notas nuevas ya captura ejes habilitados y versiones. No hace
falta que el frontend ejecute extractores ni encadene trabajos por su cuenta.
Pausar afecta reservas futuras y conserva resultados y trabajos ya reservados.
Sin `version_id`, un eje puede contener hallazgos producidos por distintas versiones.

La prueba temporal no participa en el SSE de documentos: lo excluye
[`ProcessingRepository.event`](../src/processing/repository.py). El frontend no
puede asumir que el servicio de eventos actual notificará su progreso.

## 3. Ajustes de backend propuestos antes de completar la UI

No propongo rehacer extracción, persistencia, colas ni versionado. Los ajustes
son de contrato y experiencia. Los ajustes A–D ya se implementaron; este apartado conserva el diagnóstico inicial.

### A. Contexto de Laboratorio y bienvenida por usuario

Hoy no hay una preferencia de bienvenida de Laboratorio ni un contrato de
capacidades: `SessionRead` no lo devuelve y las rutas de ejes dan 404 cuando
`PERSONAL_AXES_ENABLED` está deshabilitado. El onboarding de Notificaciones es
otro circuito: no representa la decisión «Ahora no» de esta sección y tiene
retención/visibilidad propias.

Propuesta de API autenticada, a cerrar en la primera entrega:

- `GET /laboratory/context`: `enabled`, límites públicos de entrada y estado de
  bienvenida. Debe poder responder `enabled=false` sin ejecutar proveedores ni
  depender del servicio de pruebas que hoy aplica el feature flag.
- `PATCH /laboratory/preferences` con `{ "welcome_dismissed": true }`, idempotente,
  guardado por dueño. Sólo se marca al posponer o iniciar la creación; consultar
  ayuda o visitar la página no lo marca. No volver a mostrarlo por un cambio de
  versión de ayuda ni por borrar contenido sin una decisión de producto.
- Guardar sólo el marcador en el ámbito de preferencias de usuario, no la
  finalidad, las notas de muestra ni los comentarios. No crear otro módulo de
  extractores para esto. Cachear el marcador por usuario en el dispositivo.

Esto es necesario para cumplir «una vez por usuario», también entre dispositivos.
Una marca exclusivamente local sólo cumpliría «una vez por dispositivo».

### B. Identidad explícita para abrir hallazgos

Los nodos de vecindad tienen `id="AxisFinding:<uuid>"`, pero el endpoint de detalle
requiere un UUID. `ActiveNode` no expone `finding_id`; incluso las pruebas HTTP
actuales separan el string por `:`. Además, el listado temporal usa un ID con
prefijo y el listado activo usa UUID.

Propuesta aditiva:

- `finding_id` en nodos de hallazgo y `node_id` en el detalle/listado activo.
- Mantener el `id` de grafo y cursores como opacos: el cliente no reconstruye IDs,
  no decodifica etiquetas ni depende de prefijos internos.
- El adaptador frontend separa `graphId`, identidad de detalle y ámbito de lectura.

Evidencia: [`schemas.py`](../src/extractors/personal_axes/schemas.py),
[`AxisExploration.add_finding`](../src/extractors/personal_axes/exploration.py) y
[`test_version_trace_zero_findings_and_http_contract`](../tests/integration/test_personal_axis_processing.py).

### C. Contexto suficiente al expandir y ocultar tipos

En vecindades activas de nota/etiqueta se llama a `add_finding(...,
include_tags=False)`: una nota devuelve sus hallazgos y citas, pero no sus
etiquetas; una etiqueta devuelve sólo el enlace hacia esa etiqueta. Si se ocultan
hallazgos, no alcanza esa respuesta para mostrar las conexiones nota–etiqueta del
prototipo. Pedir otra vecindad por cada hallazgo produciría N+1 solicitudes.

Propuesta: cada página de hallazgos descubiertos incluye su nota, sus citas y
sus enlaces `HAS_TAG` con etiquetas canónicas como contexto acotado. El límite
sigue paginando hallazgos; documentar límites máximos de nodos y relaciones de
contexto, usando los máximos de etiquetas y evidencias del contrato. Señalar si
la adyacencia de etiquetas de un hallazgo está completa.

Alinear la política de contexto entre previews y ejes activos. Hoy los previews
paginan vecinos directos y los activos agregan contexto. Conservar los ámbitos y
cursores actuales; no convertir una apertura de rama en una lectura global.
Validar serialización HTTP, varias citas, etiquetas compartidas y última página.

Mientras este ajuste se termina, el cliente puede mostrar sólo relaciones ya
conocidas y pedir contexto explícito. No debe interpretar una página incompleta
como ausencia de relación ni fabricar enlaces por semejanza de títulos.

### D. Evidencia y diferencias de texto

Los offsets actuales se calculan con índices de Python. En JavaScript, `slice`
usa unidades UTF-16: un emoji anterior a una cita cambia el resultado. Esto se
resuelve en el frontend convirtiendo offsets por puntos de código, verificando
que el fragmento obtenido sea exactamente `quote`, sin normalizar el original.
No es necesario cambiar el significado de los offsets del backend.

Recomiendo añadir/documentar `source_hash` en los DTO de origen de pruebas y
hallazgos activos, aprovechando el hash ya validado y persistido. Permite detectar
un cambio del original entre consultar el hallazgo y abrir la nota. Si el texto
no coincide, conservar la cita y pedir actualización; nunca resaltar otra
ocurrencia aproximada. Admitir varias citas y rangos superpuestos.

### E. Mejoras que no bloquean la primera entrega

- Resúmenes por eje (`has_results`, notas revisadas, hallazgos, fecha) para las
  tarjetas. Hoy `AxisResponse` no tiene esas estadísticas. Hasta agregarlas,
  omitir cifras; no recorrer todos los hallazgos para contar ni usar las ficticias
  del prototipo.
- Filtro por etiqueta en la lista y listado paginado de notas con cero hallazgos.
  Hoy `findings` filtra por nota y versión, no por etiqueta, y sólo lista hallazgos.
  El preview sí permite mostrar sus cinco notas, incluidas las vacías. En un eje
  activo no prometer una lista completa de notas vacías a partir de `findings`;
  resolver el estado de una nota abierta mediante su vecindad.
- Optimizar `preview_neighbors`, que hoy reconstruye los resultados completos
  antes de recortar la vecindad. No requiere un nuevo almacenamiento permanente.
- Un identificador de revisión del conjunto activo si se requiere consistencia
  entre páginas durante reprocesamiento. Hoy son páginas de datos vivos, no un
  snapshot. Para la primera versión, invalidar y recargar la exploración cuando
  cambien sus resultados; no acumular indefinidamente IDs de ejecuciones viejas.

## 4. Arquitectura de la PWA

Implementación en `mirror-pwa`, sin portar el JavaScript monolítico del prototipo:

```text
src/services/laboratory-api.ts          DTO, llamadas, errores y AbortSignal
src/storage/laboratory.ts               borrador, pruebas y operaciones pendientes
src/features/laboratory/
  LaboratoryScreen.tsx                 composición y navegación interna
  LaboratoryHome.tsx                   ejes, bienvenida y borrador compacto
  LaboratoryHelp.tsx                   panel de ayuda con acordeones
  AxisDraftEditor.tsx                  título y finalidad
  SamplePicker.tsx                     selección de cinco notas del servidor
  PreviewScreen.tsx                    progreso, resultados, ajustes y aceptación
  AxisScreen.tsx                       definición, pausa y edición
  useAxisDraft.ts                      revisión local y persistencia
  useAxisPreview.ts                    envío, recuperación, avance y retry
  graph/                               modelo canónico, proyección y exploración
  laboratory.css                       estilos acotados a la sección
```

Reutilización concreta:

- `apiFetch`: sesión, cancelación, timeout y pérdida de autorización.
- Almacenamiento Dexie ya separado por usuario y sus guardas de activación;
  añadir tablas del Laboratorio sin reutilizar la tabla de borradores de captura.
- `ReadingDialog`, iconos, tokens y estilos de controles existentes. Revisar que
  el foco del diálogo incluya los `summary` de la nueva ayuda y mantenga un solo
  scroll interior en móvil.
- Cytoscape, `orb.ts`, paleta y algoritmo de inserción alrededor del nodo de
  Constelaciones. Compartir sólo primitivas agnósticas del dominio si hace falta.
- `getRemoteDocument` para el original; los borradores o audios aún sin documento
  de servidor no son seleccionables como muestra.

No usar directamente `useGraphExploration`: conoce emociones, solicitudes
serializadas y `next_limit`; Laboratorio usa tres tipos, cursores por rama y un
ámbito de eje/versión o prueba/revisión. El renderer actual también clasifica por
capas y eliminaría nodos ocultos al sincronizar; necesita adaptación para recordar
sus posiciones. No cambiar el comportamiento del grafo de emociones como efecto
secundario de esta entrega.

Integración con navegación:

- Añadir `laboratory` a `AppSection` y a la navegación de `AppShell`; en móvil
  queda como cuarta sección, conservando Notificaciones en la cabecera.
- Integrar una vista lazy en `App.tsx` y en la composición de `CaptureScreen`,
  que hoy contiene el shell y decide entre captura, material, grafo y avisos.
  Mantener captura montada y sus restricciones de navegación durante grabación.
- Añadir rutas internas recuperables de Laboratorio (inicio, borrador, prueba y
  eje), con atrás del navegador. La PWA actual no usa React Router: no agregar
  una dependencia sólo para este circuito sin necesidad.
- Cargar/habilitar la sección según capacidades. Un enlace antiguo hacia una
  función deshabilitada muestra un estado claro; 401 sigue el flujo de sesión.

## 5. Estado, persistencia y recuperación

### Borrador y solicitudes

Persistir antes de enviar: `draft_id`, revisión monotónica, título, finalidad,
cinco IDs en orden estable, ajustes acumulados, eje/versión base si es edición,
historial de IDs de prueba y una operación pendiente con cuerpo exacto y clave.
Separar el texto que se está editando de la revisión que ya fue evaluada.

- `generate`: primera evaluación; también permite empezar de nuevo si vencieron
  los temporales, sin depender de una prueba anterior desaparecida.
- `refine`: revisión mayor, mismo borrador, `previous_preview_id` y todos los
  ajustes anteriores más el nuevo. No reemplazar el historial por el último texto.
- `repeat`: mismo título/finalidad/ajustes y criterio anterior; usarlo para repetir
  la evaluación con esa definición, no para cambios de finalidad.
- Cambiar selección o contenido de fuentes requiere confirmación explícita y
  `change_sample=true`. No reemplazar silenciosamente notas eliminadas.
- Si se pierde la respuesta, reenviar el mismo cuerpo y clave; cambiar el cuerpo
  crea otra operación. Nunca crear automáticamente una nueva prueba para resolver
  la incertidumbre de una anterior.
- No calcular `revision_hash` del servidor con una implementación JS propia;
  guardar el recibido y vincularlo al snapshot local exacto de esa revisión.

Alinear validaciones con los límites actuales: título 200, finalidad 8000,
exactamente cinco notas distintas, hasta 20 ajustes de 4000 caracteres. El
prototipo usa otros máximos y un mínimo de finalidad más estricto que la API:
no trasladarlos accidentalmente ni truncar definiciones existentes al editarlas.

### Progreso, resultados y aceptación

Usar polling acotado de snapshot, por ejemplo 2 s al inicio y backoff hasta 10 s
ante fallos de conexión. Sólo mientras haya una prueba no terminal y la pantalla
esté visible/en línea; reanudar al volver. Cancelar al cambiar de revisión,
usuario o pantalla. No abrir un SSE adicional ni esperar eventos inexistentes.

Mostrar la etapa real y notas completadas; la API no ofrece porcentaje real ni
estado `running` individual por nota. Combinar errores de `snapshot.notes` con los
resultados por documento: `/results` puede dejar `pending` en una nota fallida sin
output. No presentarla como pendiente indefinidamente si snapshot indica fallo.

Conservar pruebas anteriores mientras sean consultables. Distinguir vencida,
fuente cambiada, eliminada/no disponible y error recuperable. Salir de la sección
no cancela un trabajo del servidor; al volver se recupera por su ID guardado.

Aceptar sólo la revisión vigente, con cinco notas completadas y sin cambios
locales pendientes. Enviar el hash evaluado. Una respuesta de aceptación perdida
se recupera repitiendo la misma aceptación; después leer el eje actual, limpiar
el borrador sólo al confirmar y mantener la pausa que devuelva el servidor.
La vista histórica no debe confundirse con la versión actual.

### Sesión y privacidad

Toda persistencia local y cache pertenece al usuario activo. Una respuesta tardía
no escribe en otra sesión. Persistir WIP sin conexión, pero exigir conexión para
probar, refinar y aceptar; no ejecutar pruebas costosas automáticamente al volver
la red. Con almacenamiento bloqueado, informar que el borrador dura en la pestaña.

El marcador de bienvenida se sincroniza por usuario; una decisión local pendiente
se reconcilia sin volver a mostrar la tarjeta. No publicar finalidad, comentarios,
notas, citas, prompt, IDs ni cursores en telemetría. Ampliar únicamente plantillas
sanitizadas de rutas y categorías de error.

## 6. Grafo progresivo y modelo de lectura

Separar tres estados: grafo canónico explorado, grafo visible derivado y estado
del canvas. Ámbito: usuario + eje + filtro de versión, o usuario + preview +
`revision_hash`. Un nodo estructural Axis/AxisPreview puede servir para consultar
sin convertirse en un cuarto tipo de nodo visible.

1. Abrir una rama inicial acotada: una etiqueta del catálogo o una nota de la
   raíz. El catálogo actual ordena por clave: no llamarla «la más frecuente» sin
   un contrato que lo garantice. Si no hay etiquetas, permitir notas sin hallazgos.
2. Al tocar un nodo, mostrar su detalle y solicitar su vecindad. Guardar por rama
   `{cursor, loading, error, exhausted}` y páginas ya aplicadas. Coalescer doble
   toque; permitir que ramas distintas progresen sin invalidarse entre sí.
3. Unir por IDs y conservar toda procedencia. Una expansión agrega elementos cerca
   del nodo abierto; no ejecuta layout global, fit ni cambia zoom/paneo.
4. Para continuar una rama, tocar otra vez un nodo que indique vecinos pendientes
   o usar «Seguir explorando» en su detalle. Error/reintento y fin de rama son por
   nodo. No hay botón que cargue el eje entero.
5. Ocultar tipos recalcula sólo una proyección de lo ya cargado, sin otra petición.
   Mantener las posiciones de los nodos ocultos y el detalle de selección.
6. «Ordenar» y «Ajustar» son acciones explícitas. En móvil, una expansión mantiene
   el grafo en pantalla; leer una relación permite ir al detalle y volver al mapa.
7. Respuestas de otro ámbito se descartan. Ante datos reemplazados o fuente
   cambiada, invalidar la exploración afectada y ofrecer actualización. Incorporar
   `extractor_key` al tipo `ProcessingState` de PWA para reconocer eventos de
   `axis:<uuid>`; el backend ya lo emite.

Proyecciones de visibilidad, fieles al prototipo:

| Tipos visibles | Relaciones |
| --- | --- |
| Todos | Nota → hallazgo → etiqueta. Citas en nota–hallazgo. |
| Notas + etiquetas | Contraer el hallazgo en el enlace, conservando IDs y todas sus citas. |
| Notas + hallazgos / sólo hallazgos | Citas y enlaces por etiquetas compartidas conocidas. |
| Hallazgos + etiquetas | Enlaces originales; nota y citas consultables en detalle. |
| Sólo notas | Enlace por etiquetas compartidas entre sus hallazgos. |
| Sólo etiquetas | Enlace sólo si coinciden en el mismo hallazgo. |

Los enlaces derivados son punteados y conservan referencias al grafo canónico;
no se persisten en el backend. Compartir una etiqueta no equipara ideas. No inferir
sinónimos ni normalizar IDs opacos en JS. Los conteos parciales deben decir
«descubiertos» y nunca aparentar totales globales.

La Lista usa resultados completos, no únicamente nodos visibles del grafo. En
preview incluye las cinco notas, incluso las vacías; en activo pagina hallazgos
por API y permite contexto de una nota seleccionada. Muestra la versión real de
cada hallazgo, consultando su definición histórica bajo demanda.

## 7. Entregas y criterios de salida

| Entrega | Trabajo | Comprobación antes de seguir |
| --- | --- | --- |
| 0. Contratos | Ajustes A–C; definir offsets/hash de D; fixtures HTTP y tipos. | Bienvenida entre dos sesiones; IDs sin parsing; expansión con contexto completo y límites; feature deshabilitado. |
| 1. Inicio | Navegación experimental, ejes paginados, borrador compacto, bienvenida y ayuda; almacenamiento propio. | Primera visita, posponer, comenzar, regreso, dos usuarios, offline, teclado y 320 px. |
| 2. Crear/probar | Editor, selector de cinco notas, envío durable, recuperación de respuesta perdida, polling y errores. | Misma clave/cuerpo en replay; recarga en cada etapa; selección inmutable y fuente cambiada; no disparar duplicados. |
| 3. Revisar/aceptar | Lista temporal, lector con citas, refinamiento, comparación y aceptación versionada. | Varias citas, emoji y offsets; revisión obsoleta; cinco completadas; 409/410/429; aceptación repetida. |
| 4. Explorar | Grafo canónico, vecindades paginadas, tres controles de tipos y detalle. | Siete combinaciones, ramas intercaladas, cursor agotado/erróneo, retry local, posiciones y cámara estables. |
| 5. Eje activo | Lista/detalle, versiones, pausa, edición con versión base y actualización por procesamiento. | Resultados de versiones distintas; pausa sin borrar; versión base obsoleta; eje sin resultados; nota eliminada/reprocesada. |

Las entregas 1 y parte de 2 pueden avanzar en paralelo con los ajustes de contrato
usando fixtures acordadas. No declarar la integración terminada con mocks: cerrar
el circuito contra API/workers y bases desechables, con proveedor determinístico.
La implementación se autorizó posteriormente de forma explícita en la conversación.

Validación final:

- Pruebas de estado/servicio con HTTP simulado para replay, carreras, vencimiento
  y cambio de sesión. IndexedDB falsa para migración y recuperación de WIP.
- Integración con PostgreSQL/ArcadeDB desechables: cinco notas → refinar → aceptar
  → nota nueva → explorar → pausar/editar → retry. Aceptación no promueve la muestra.
- `npm test`, `npm run lint`, `npm run build`, `npm run verify:build` en PWA.
- Revisión visual en 320/390/768/1440 px, orientación horizontal, foco, lector/ayuda
  con scroll propio y controles de 44 px. Comprobar que volver al inicio muestra
  contenido útil sin repetir la presentación.
- Prueba manual de PWA instalada y dispositivo táctil, y evaluación del criterio
  con LLM real como validaciones posteriores separadas de tests sintéticos.

## 8. Evidencia de la revisión previa

Se inspeccionaron rutas, DTO, use cases, proyecciones, persistencia/versiones,
pruebas de integración existentes y composición real de PWA. Pasaron las 12
pruebas de `test_personal_axis_extractor.py` y `test_personal_axis_projection.py`
con proveedores simulados. La corrida aislada se detuvo en IO asíncrono; la misma
selección pasó fuera de ese aislamiento, sin llamadas al proveedor real.

En esa revisión no se repitieron las integraciones con bases reales ni se verificó despliegue.
Los resultados históricos de integración están documentados en
[API y operación](personal-axes-api.md); no se presentan como una corrida nueva.
El cambio preexistente de `nginx/default.conf` quedó fuera del commit del prototipo.
