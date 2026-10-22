# Laboratorio: implementación y validación

Fecha: 2026-10-21. Cambios locales en `mirror-core`, `mirror-pwa`, `mirror-admin` y configuración de `mirror-deploy`.

## Comportamiento implementado

La PWA incorpora Laboratorio como cuarta sección móvil, cargada bajo demanda y
habilitada por `/laboratory/context`. Captura mantiene su composición y sus
restricciones de navegación. Constelaciones sigue siendo una sección independiente.

El inicio muestra ejes paginados, un borrador para retomar y una acción para crear.
La bienvenida se ofrece sólo sin ejes ni borrador y mientras no se haya pospuesto
o iniciado una creación. Ayuda permanece accesible y usa apartados desplegables;
en móvil se presenta desde abajo, con foco y scroll dentro del diálogo.

La creación sigue finalidad → entre una y cinco notas del servidor → prueba → ajustes →
aceptación. Título, finalidad, muestra, ajustes acumulados y comentario sin enviar
se guardan por cuenta en IndexedDB. Los cambios de una pantalla no se pierden al
remontarla: las escrituras se serializan por base local y la lectura espera la
última escritura. Se informa cuándo terminó el guardado y se protege la salida
con escrituras pendientes o trabajo que no se pudo persistir. Un error de lectura
no se interpreta como un borrador vacío.

Cada solicitud guarda cuerpo e identidad antes de enviarse. Crear y reintentar
reutilizan la misma clave ante una respuesta perdida; aceptar reenvía el hash de
la revisión probada. Una reserva que no se pudo guardar no se envía. La aceptación
recupera la definición actual antes de limpiar el borrador. Cambios de muestra o
contenido requieren una decisión explícita; una prueba vencida puede reemplazarse
con `generate` sin referenciar temporales desaparecidos.

El polling usa únicamente el estado del backend, se pausa en segundo plano o sin
conexión y aplica backoff ante fallos. Las notas de la muestra se muestran en Lista,
incluyendo resultados vacíos y fallidos. La aceptación exige todas las notas de la muestra completadas,
revisión vigente y ausencia de cambios o comentarios sin evaluar.

El eje aceptado muestra su descripción cerrada, pausa y edición mediante una
nueva versión. Las pruebas no se promueven a resultados activos. Aceptar otra
versión conserva la pausa. Cada hallazgo permite consultar la definición histórica
que lo produjo y leer la nota original con todas sus citas.

## Grafo

Un único canvas Cytoscape usa las primitivas visuales de Constelaciones y mantiene
un modelo propio para notas, hallazgos y etiquetas. En los ejes aceptados, el
grafo abre automáticamente la última nota, como Constelaciones. «Por nota / Por
etiqueta» y un selector directo permiten cambiar de origen y alcanzar componentes
desconectados. Las notas usan el mismo listado ordenado de Constelaciones y las
etiquetas recorren su catálogo paginado completo. Se reutilizan las rutas de tags y vecindades;
no se necesita un cambio del backend. Las pruebas temporales conservan su muestra.
Tocar nodos abre vecindades con cursores y errores por rama. Las páginas agregan
contexto sin reemplazar ramas anteriores. Nuevos nodos se insertan separados de
los existentes; sólo las acciones explícitas de ajustar/ordenar cambian el encuadre.

Las tres referencias inferiores muestran u ocultan tipos. Las siete combinaciones
conservan los hallazgos y citas que sostienen sus enlaces: nota–etiqueta sin
hallazgos visibles, hallazgo–hallazgo y nota–nota por etiquetas compartidas,
y etiqueta–etiqueta sólo cuando coinciden en el mismo hallazgo. No se infieren
sinónimos ni se reconstruyen identidades a partir de títulos. Ocultar tipos
conserva posiciones, zoom y pan. Lista es la alternativa accesible al canvas.

## Cambios del backend

Se reutilizan `src/extractors/personal_axes`, los extractores existentes, artefactos
temporales, workers, versiones inmutables y persistencia activa. Se añaden:

- Contexto de capacidades y preferencia monotónica de bienvenida por usuario.
- Migración Alembic `20261021_15` para el marcador de bienvenida.
- Identidad de detalle explícita, hash de origen y completitud de etiquetas.
- Contexto completo y acotado al expandir hallazgos desde una nota o etiqueta.
- Protección de origen en mutaciones de Laboratorio y ejes.

## Validación

- Backend: 15 pruebas unitarias de extractor, proyección, autenticación,
  aislamiento e idempotencia de bienvenida.
- Integración: 28 pruebas existentes de pruebas temporales, extracción activa,
  versiones, propietarios, citas, paginación y recuperación, contra PostgreSQL y
  ArcadeDB desechables. Se probó la migración nueva subiendo/bajando/subiendo.
- Se repitió el caso de paginación activa después de ajustar `tags_complete` para
  que también describa correctamente una respuesta parcial de un hallazgo.
- La prueba `tests/integration/test_laboratory_pwa.py` sirve la PWA compilada y usa
  autenticación de cookie, HTTP, SQL, almacenamiento de documentos, ejecución de workflows y
  ArcadeDB reales con proveedor determinístico. Recorre crear, recargar un ajuste
  local, refinar, aceptar, extraer una nota nueva, abrir citas, consultar la versión
  histórica, pausar, aceptar versión 2 y procesar otra nota manteniendo la pausa.
  El transporte SSE y los servicios ajenos al Laboratorio se aíslan en este fixture;
  las rutas de dominio de Laboratorio y documentos no se simulan. Los workflows
  se despachan desde un runner de prueba; esta corrida no valida RabbitMQ.

Las validaciones de navegador y frontend y sus capturas se documentan también en
`mirror-pwa/docs/laboratory.md`.

## Preparación de ejecución

Aplicar `alembic upgrade head` hasta `20261021_17` antes de iniciar los procesos
nuevos de backend. Después habilitar `PERSONAL_AXES_ENABLED` en API, workers y
dispatcher y admin-api. Desde Usuarios → Ver cuenta → Laboratorio habilitar
el permiso de cada cuenta. Por defecto todas quedan sin acceso. La PWA consulta la
capacidad por API y no incorpora otra bandera de compilación. Los workspaces
mantienen el volumen compartido que ya utiliza el procesamiento durable.

La validación local no publica imágenes ni despliega. La evaluación del criterio
con LLM real y la revisión de una PWA instalada en un dispositivo táctil quedan
como comprobaciones de ejecución separadas.

Los cambios preexistentes de concurrencia del worker y exposición del puerto LAN se conservan fuera del alcance de esta implementación.


## Acceso experimental por cuenta

Se añadió el permiso persistente `user.laboratory_enabled` con default `false`,
migración `20261021_16`, control en el detalle de usuario del panel LAN y estado
visible en su listado. La API protege todas las rutas de pruebas/ejes/resultados y
la reserva de extracciones automáticas con el global combinado con el permiso.
Revocar conserva los datos y los trabajos previamente aceptados. La PWA muestra
un chip «Experimental» en la cabecera de toda la sección.

El panel muestra el estado de guardado, reconsulta ante errores y explica cuando
el global está apagado. La escritura es estrecha, idempotente, con booleano estricto,
campos extra prohibidos y origen exacto. Las lecturas administrativas conservan
sus transacciones de sólo lectura. El proxy permite exclusivamente ese PATCH,
preserva host/puerto y mantiene bloqueadas otras mutaciones. Ambos Compose pasan
el global a admin-api; no se modificaron ni reiniciaron servicios desplegados.

Validación de esta extensión:

- 7 pruebas de autorización/contexto/API y 20 integraciones PostgreSQL/ArcadeDB:
  persistencia administrativa real, combinación global/cuenta, migración con
  cuentas/sesiones existentes, revocación y finalización de trabajos reservados.
- Panel: 14 pruebas, lint, tipos, build y verificación sin fixtures. Chrome revisó
  guardado, recarga, fallo de guardado, global apagado y anchos 320/390/768/1440.
- PWA: lint/build/verificación y recorrido completo de navegador con API simulada,
  sin errores de página; captura del chip en inicio y cabecera de los ejes.
- Nginx aislado en contenedor sin root y filesystem de sólo lectura: estáticos,
  reenvío exclusivo del PATCH, bloqueo de otras mutaciones y Host con puerto.

Capturas sintéticas: `mirror-admin/docs/validation/laboratory-access-2026-10-21`
y `mirror-pwa/docs/validation/laboratory-access-2026-10-21`.


## Extensión: análisis histórico de notas

Cada eje aceptado ofrece **Analizar notas anteriores** con búsqueda por título,
fechas, selección y confirmación explícita de la versión. Funciona también en
pausa. El historial ocupa una fila compacta al terminar y al volver a entrar;
progreso activo, solicitudes por confirmar y errores actuales abren el detalle.
Se conservan el detalle por nota, análisis anteriores, detener pendientes y
reintentar sólo fallos recuperables. Un error de un lote antiguo no mantiene
desplegado un análisis posterior exitoso.
No hay análisis automático al aceptar ni promoción de las muestras temporales.

El backend incorpora migración `20261021_17`, lotes/ítems y workflow
`axis_history_note/1` sobre el ejecutor, outbox y extractor existentes. La reserva
valida la selección completa y fija versión/hashes; las notas vigentes, incluidas
las de cero hallazgos, o ya reservadas se omiten. Los lotes son durables en el
servidor; la recuperación de una solicitud sin respuesta usa la misma clave y
cuerpo guardados por cuenta/eje en IndexedDB. No se guarda contenido de notas en
la nueva tabla de seguimiento.

Detener finaliza las reservas pendientes y cerca sus entregas anteriores;
lo iniciado puede terminar. Retry reutiliza checkpoints. Una fuente cambiada o
eliminada no se analiza con el manifest anterior. La persistencia atómica ordena
las escrituras por versión y reserva, también para extracciones automáticas:
una ejecución vieja nunca desplaza otra más nueva. Un conflicto simultáneo de
escritura se resuelve mediante el retry existente.

Validación de la extensión:

- 11 integraciones PostgreSQL/ArcadeDB con proveedor determinístico: permisos,
  propiedad, idempotencia, cobertura vacía, pausa, duplicados, stop/retry, fuentes
  modificadas/eliminadas, reanudación y escrituras simultáneas fuera de orden.
- Integración de la PWA compilada con HTTP, cookie, SQL, ejecutor y grafo reales:
  nueve notas sobre versión 2 pausada, respuesta perdida y recarga, 18 hallazgos,
  cobertura vigente y ninguna nueva generación de criterio.
- Chrome con HTTP simulado a 320/390/844/1440 px, márgenes/foco/scroll, acción
  fija de continuar, recuperación tras perder respuestas y fallo de IndexedDB.
  Regresión del recorrido de creación/refinado/aceptación y grafo previo.
- Frontend: suite de 28 archivos, lint, tipos/build y verificación PWA.
  Backend: Ruff y migración up/down/up sobre bases desechables.

Entorno local de desarrollo: migración 17 aplicada y procesos API, worker y
dispatcher recargados; PWA servida desde el código actualizado. Se comprobó que
no había trabajos activos antes del reinicio. No se iniciaron análisis sobre
notas reales ni se alteraron permisos. Esto no publica imágenes ni despliega en
producción. Las pruebas automatizadas usan proveedor determinístico y runner
local; no acreditan la entrega real por RabbitMQ ni un dispositivo táctil físico.


## Voz personal de los hallazgos — 2026-10-22

Se añadieron reglas comunes de segunda persona cercana al prompt de extracción,
respetando las formas de trato y vocabulario de la propia narración del usuario.
No se impone voseo rioplatense: sin evidencia se usan expresiones compartidas,
sin deducir procedencia por nombres ni por citas de otros. Títulos naturales,
etiquetas temáticas, citas literales y matices de
la fuente se conservan; las otras personas no se confunden con quien escribe.
El criterio generado define contenido semántico y no reemplaza esta voz. El
mismo prompt se usa al corregir evidencia inválida.

La cobertura histórica ahora contrasta también el hash del perfil, tanto al
listar notas como al reservar y ejecutar un lote. Permite regenerar una nota
cuyas instrucciones cambiaron, sin reutilizar un resultado producido con otro
prompt ni repetir trabajo cuando ya coincide.

La API conserva la inmutabilidad de las versiones aceptadas. No incorpora una
ruta que permita modificarlas. El caso excepcional de actualizar una definición
durante desarrollo se verifica en una base descartable, restaurando la protección
SQL dentro de la misma transacción.

Validación: 15 pruebas unitarias de extractor/proveedor, integraciones de
historial/previews/procesamiento y una integración específica de cambio de prompt
sobre la misma versión, con PostgreSQL y ArcadeDB descartables. Se verificaron
citas intactas y transporte de las instrucciones para voseo, tuteo, ustedeo y
texto sin señales regionales. Los casos de proveedor usan respuestas simuladas;
no acreditan la calidad lingüística de un modelo real. Se verificó la invalidación
del perfil anterior, nueva cobertura y protección SQL nuevamente activa.

Cambiar las instrucciones no reescribe los hallazgos almacenados: es necesario
analizar nuevamente las notas. La evaluación lingüística con un LLM real queda
separada de estas verificaciones determinísticas.
