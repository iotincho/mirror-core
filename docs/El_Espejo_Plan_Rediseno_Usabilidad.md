# El Espejo: plan de rediseño y mejoras de usabilidad

Fecha de acuerdo: 2026-10-14.
Estado general: **etapas 1–5 implementadas localmente, pendientes de aceptación visual y pruebas en teléfonos; etapa 6 con validación automática y runtime local completados; aceptación visual/dispositivos y publicación pendientes**.
Referencia visual: [prototipo navegable](../prototypes/app-refresh/README.md).

Este documento es el registro de alcance y avance del rediseño aprobado. El usuario aprobó el estilo general, la navegación, el botón único de captura, continuar grabando, la protección frente al bloqueo de pantalla y la posibilidad de fechar cualquier nota. El plan y el prototipo quedaron comiteados. El 2026-10-14 el usuario autorizó implementar sucesivamente las etapas 1, 2, 3, 4, 5 y la validación de la etapa 6, reutilizando la misma rama para acumular los cambios. La aceptación visual/en dispositivos y la publicación continúan como pasos pendientes.

## Cómo mantener este plan

Actualizar este archivo al completar trabajo, en el mismo cambio o PR que lo implementa, incluso si el código pertenece a `mirror-pwa` o `mirror-deploy`.

- Marcar una tarea sólo cuando el comportamiento esté implementado y tenga la validación correspondiente.
- Registrar fecha, repositorio, commit/PR, comprobaciones y limitaciones en el historial.
- Distinguir implementación, validación automática, revisión visual, pruebas en teléfono y publicación. Un build exitoso no acredita funcionamiento en dispositivos ni despliegue.
- Si cambia el alcance o aparece una dependencia, anotarlo explícitamente; conservar los criterios pendientes.
- Mantener las decisiones de formatos de audio y composición de segmentos junto a sus evidencias.

## Estado por etapa

| Etapa | Estado | Evidencia de cierre |
| --- | --- | --- |
| 1. Base visual y navegación | Implementada localmente; aceptación visual pendiente | `mirror-pwa` · `feat/app-refresh-stage1` · `eedbbde`; build, lint y pruebas automáticas |
| 2. Captura y fecha original | Implementada localmente; aceptación visual pendiente | `mirror-pwa` · misma rama `feat/app-refresh-stage1` · `9fa20ef`; build, lint y 13 archivos de pruebas |
| 3. Material, lectura y ajustes | Implementada localmente; aceptación visual pendiente | `mirror-pwa` · misma rama `feat/app-refresh-stage1` · `58129b0`; build, lint y 15 archivos de pruebas |
| 4. Grabación protegida y recuperable | Implementada localmente; aceptación visual, codecs y teléfonos pendientes | `mirror-pwa` · misma rama `feat/app-refresh-stage1` · 4674067; build, lint y 16 archivos de pruebas |
| 5. Constelaciones | Implementada localmente; aceptación visual/mobile y servidor real pendientes | `mirror-pwa` · misma rama `feat/app-refresh-stage1` · `975bdfd`; build, lint y 17 archivos de pruebas |
| 6. Validación integral y publicación | Validación automática/runtime local completados; aceptación visual/dispositivos y publicación pendientes | `mirror-pwa` · misma rama · `4c6d1bc`; 17 archivos PWA, 175 pruebas backend, integración HTTP/SQL/RabbitMQ e imagen local |

El prototipo es una referencia de diseño con datos ficticios. No acredita la implementación funcional de estas etapas.

## Bases verificadas antes de la implementación

En `mirror-pwa`, `CaptureScreen.tsx` ya alterna entre grabar y enviar según el contenido. Se mejorarán la presentación y los estados, aprovechando esa lógica.

La fecha original ya forma parte del borrador, de `LocalDocument.authoredAt` y del envío al backend. Al inicio del plan, su edición aparecía sólo en capturas compartidas (`isSharedCapture`); la etapa 2 la generaliza. `authored-date.ts` valida fecha/hora local y la convierte a ISO con zona; se reutilizará esta base.

La grabación actual acumula fragmentos en memoria y guarda el Blob al detenerse. El grabador vive dentro de la pantalla de captura y sus tracks se detienen al desmontarla. No solicita protección de pantalla.

Ya existen almacenamiento Dexie separado por usuario, borradores, sincronización, recuperación de procesamiento, importación/exportación y el motor Cytoscape de Constelaciones. El rediseño debe conservar sus contratos y datos.

## 1. Base visual y navegación

Repositorio principal: `mirror-pwa`.

- [x] Extraer la paleta, tipografía, espaciado, bordes y tamaños del prototipo a estilos compartidos.
- [x] Unificar botones, campos, etiquetas, estados, diálogos, mensajes e iconos SVG.
- [x] Usar fondo petróleo, superficies suaves, texto marfil, acento salvia y ámbar en encabezados; errores y acciones destructivas con tratamiento propio.
- [x] Mantener controles cómodos al tacto, con botones principales de 44 px y jerarquía visual contenida.
- [x] Incorporar navegación compartida: Capturar, Tu material y Constelaciones.
- [x] Desktop: sidebar simple, ajustes y cierre de sesión al pie; contenido con ancho máximo.
- [x] Mobile: navegación inferior, ajustes desde avatar y espacio para áreas seguras.
- [x] Adaptar también acceso, carga inicial, errores y pantallas vacías.

Aceptación: no hay scroll horizontal a 320 px ni en desktop; textos largos envuelven; teclado móvil y áreas seguras no tapan acciones; foco visible y navegación por teclado; los estados no dependen únicamente del color. Corregir el origen del overflow sin ocultarlo globalmente.

### Avance registrado: 2026-10-14

Implementación: `mirror-pwa`, rama `feat/app-refresh-stage1`, commit `eedbbde` (`feat: add shared mobile-first navigation and design foundations`), basado en `origin/develop`.

- `src/index.css`: variables compartidas de color, tipografía, tamaños y superficies; estilos accesibles de controles y movimiento reducido.
- `src/components/AppShell.tsx` y `app-shell.css`: sidebar desktop, navegación inferior mobile, acceso a ajustes y contenido con ancho flexible.
- `src/components/Icon.tsx` y `ReadingDialog.tsx`: vocabulario SVG y lector compartido con Escape, contención y restauración de foco.
- `src/App.css`: sustituye capas históricas de overrides por estilos agrupados de captura, material, lectura, ajustes, acceso y carga.
- Captura permanece montada al navegar a material/constelaciones, conservando el editor. Hasta la etapa 4, la navegación sigue deshabilitada durante la grabación actual; todavía no se implementaron pausa, continuación ni Wake Lock.
- La entrada Tu material ya presenta las listas existentes en una pantalla dentro de la estructura compartida. La búsqueda, filtros, unificación local/remota y acciones concentradas en el detalle siguen pendientes de etapa 3.
- Constelaciones adopta las variables y la estructura compartida; el rediseño específico de nodos/aristas y su validación permanecen en etapa 5.
- Acceso, carga de sesión, errores, vacíos y ajustes usan las nuevas bases. Ajustes permite cerrar sesión desde mobile y presenta ahí cualquier error de salida.
- Se actualizó el color de tema de HTML/manifest para acompañar la nueva base, conservando las variantes de iconos por entorno.

Validación realizada:

- `npm run build`: pasó, incluyendo TypeScript y generación de la PWA.
- `npm run lint`: pasó.
- `npm test`: pasaron los 12 archivos de pruebas.
- `node tests/invitation-ui.test.mjs`: 14 pruebas pasaron tras el último ajuste. Cubren también navegación sin perder borrador, foco en material, apertura/cierre de ajustes, lector con teclado, bloqueo de navegación durante la grabación actual y error de logout visible en ajustes.
- `git diff --check`: pasó.
- `npm run test:integration`: la prueba HTTP/SQL/RabbitMQ quedó omitida por faltar su configuración de entorno; no cuenta como validación integral ejecutada.

Aceptación aún pendiente:

- [ ] Revisar layout real y ausencia de overflow a 320, 375, 390, 768, 1024 y 1440 px.
- [ ] Verificar teclado móvil, áreas seguras, zoom/texto aumentado y gestos táctiles.
- [ ] Comprobar contraste y estados con render real.
- [ ] Ejecutar integración HTTP/SQL/RabbitMQ en un entorno configurado.

El navegador integrado no está disponible (`Browser is not available: iab`; lista de navegadores vacía). Las pruebas DOM no acreditan layout, scroll ni comportamiento táctil. No hubo despliegue ni validación de producción. Por eso la implementación no se marca como etapa completamente aceptada.

## 2. Captura y fecha original

Repositorio principal: `mirror-pwa`; reutilizar contratos existentes de `mirror-core`.

- [x] Un único botón de captura: micrófono por defecto; enviar/guardar cuando haya texto no vacío o adjunto; vuelve al micrófono al quitar contenido.
- [x] Iconos accesibles, tooltip y estados claros de carga, guardado y error. Evitar envíos duplicados.
- [x] Habilitar Fecha en cualquier captura: texto escrito o pegado, archivo y audio.
- [x] Permitir fecha, hora opcional, modificación y regreso a “Ahora”; precargar fecha/hora local al abrir un editor vacío y mostrar un resumen.
- [x] Persistir la selección en el borrador y conservarla al navegar, recargar o abrir/restaurar una invitación.
- [x] Usar `authored_at` para fecha original y conservar `created_at` como incorporación al sistema.
- [x] Cuando sólo se conozca el día, guardar con 00:00 sin exigir hora; mantener calendario y alternativa de entrada manual. Ajuste solicitado el 2026-10-15.
- [x] Aplicar la fecha elegida también al audio, conservando el momento de grabación como valor por defecto.
- [x] Conservar adjuntos, share target, borradores y respuestas a invitaciones con sus asociaciones actuales.

Aceptación: pegar una nota antigua, fecharla, salir y volver, guardar y sincronizar conserva contenido y fecha. La fecha se presenta consistentemente en lista, lector y Constelaciones. Un error de validación o guardado conserva el borrador.

### Avance registrado: 2026-10-14

Implementación: `mirror-pwa`, commit `9fa20ef` (`feat: add original dates and adaptive capture controls`), sobre la misma rama `feat/app-refresh-stage1` y después de `eedbbde`. El plan continúa en `mirror-core/feat/app-refresh-plan`; no se crearon ramas adicionales para esta etapa.

- Botón único de 44 × 44 px: icono de micrófono por defecto, enviar si hay texto o archivo y detener mientras se graba. Tiene nombre accesible, tooltip y estado ocupado.
- Se conserva el contrato existente de invitaciones con respuesta escrita: si una invitación está vacía, el botón de enviar permanece deshabilitado hasta escribir. Esta etapa no incorpora audio como respuesta vinculada a una invitación.
- Fecha está disponible en cualquier captura y muestra un resumen junto al editor. Permite calendario o entrada manual, hora local, elección explícita de 00:00 y regreso a Ahora. Abrir el panel y volver a Ahora gestionan el foco.
- La fecha elegida se conserva al navegar y remontar la pantalla. Los borradores que sólo tienen fecha también se conservan al abrir/restaurar una invitación o recibir contenido compartido.
- La validación rechaza fechas incompletas o imposibles antes de guardar; conserva texto, adjunto y fecha ante errores.
- `authored_at` mantiene la fecha original. `created_at` sigue siendo la fecha de creación del documento nuevo. Volver a Ahora elimina la fecha histórica seleccionada.
- Audio fija la fecha elegida al iniciar; sin selección usa el instante de inicio. La fecha se envía mediante el multipart ya existente. Al confirmar el guardado se limpia la selección para la siguiente captura.
- Lista, lector, transcripción y Constelaciones comparten presentación de fecha original, con fecha de guardado como alternativa cuando no existe fecha original.
- Hay guardas síncronas contra doble guardado, doble solicitud de micrófono y doble detención, además de estado visible mientras se solicita permiso o se guarda. Una concesión tardía de micrófono tras desmontar/cambiar sesión cierra los tracks.
- El mensaje de borrador guardado aparece después de confirmar su escritura; los errores de almacenamiento tienen anuncio accesible.
- No se agregaron dependencias ni se modificaron endpoints o esquemas del backend. Pausa/continuación, Wake Lock y persistencia progresiva del audio permanecen en etapa 4.

Validación realizada:

- `npm test`: pasaron los 13 archivos de pruebas, incluyendo 9 casos nuevos en `tests/capture-usability.test.mjs` y 14 pruebas de UI de invitaciones.
- Casos nuevos: alternancia del botón; texto histórico con navegación/remontaje; validación y hora desconocida; regreso a Ahora; archivo y contenido compartido; borrador sólo con fecha e invitaciones; fallo real simulado de escritura IndexedDB y reintento; fecha de audio y guardas de concurrencia; permiso de micrófono concedido después de desmontar.
- Se verificaron payloads JSON/multipart de texto, archivo y audio mediante el servicio real de la PWA y respuestas HTTP simuladas; esto no acredita procesamiento real del servidor.
- `npm run build`, `npm run lint` y `git diff --check`: pasaron.

Aceptación aún pendiente:

- [ ] Revisar tamaño, distribución y foco del botón/panel de fecha a 320–1440 px en navegador real.
- [ ] Probar los selectores nativos y entrada manual en Safari/iOS y Chrome/Android, con teclado y áreas seguras.
- [ ] Confirmar fechas y procesamiento en una prueba de extremo a extremo con servidor configurado.

El navegador integrado continúa sin estar disponible (`Browser is not available: iab`). No hubo push, despliegue ni pruebas de micrófono real en esta etapa.

## 3. Tu material, lectura y ajustes

Repositorio principal: `mirror-pwa`.

- [x] Reemplazar el menú sobrecargado por una pantalla completa de material.
- [x] Añadir búsqueda y filtros por texto, audio, archivo, pendientes y borradores.
- [x] Definir explícitamente el alcance de búsqueda según los documentos cargados; no presentar búsquedas parciales como completas.
- [x] Reunir copias locales/remotas por identificadores y vínculos conocidos, incluyendo audio y su documento derivado; no fusionar por parecido de contenido.
- [x] Conservar elementos locales sin sincronizar y mostrar claramente su disponibilidad en el dispositivo/servidor.
- [x] Separar visualmente guardado local, subida pendiente/en curso, procesamiento, listo y error.
- [x] Llevar lectura, reproductor, transcripción y acciones al detalle de cada nota.
- [x] Ofrecer descarga del audio, reintento desde la transcripción cuando corresponda, nueva subida y eliminación con confirmación.
- [x] Actualizar material con los eventos de procesamiento existentes.
- [x] Incorporar ajustes de invitaciones: activación, horario, zona y prueba, preservando gestión de permisos y sesión.
- [x] Crear vistas de respaldo/importación, con límites y errores claros. El respaldo JSON no incluye archivos de audio.
- [x] Conservar identidad, fechas, detección de conflictos y procesamiento durable de documentos importados.

Aceptación: no aparecen duplicados por la convivencia local/remota; ninguna nota pendiente desaparece al cambiar de vista; cada acción se puede usar desde mobile; fallos de sincronización/procesamiento permiten recuperación sin perder original o transcripción.

### Avance registrado: 2026-10-14

Implementación: `mirror-pwa`, commit `58129b0` (`feat: unify material browsing, recovery details and archives`), en la misma rama `feat/app-refresh-stage1`, sobre las etapas 1 y 2. El plan continúa en la rama existente `mirror-core/feat/app-refresh-plan`.

- `features/material/model.ts`: reúne copias por UUID de documento, `remoteDocumentId`, referencia explícita de procesamiento o metadata `audio_note_id` inequívoca. Un ID de audio no se interpreta por sí solo como ID de documento. Referencias ambiguas o textos parecidos no provocan fusiones.
- La unificación es de presentación: no sobrescribe persistencia local. Todas las copias y originales asociados se conservan, y los textos diferentes de una misma identidad se pueden leer individualmente.
- `MaterialScreen`: búsqueda y filtros Todas/Texto/Audio/Archivo/Pendientes/Borradores; incluye el borrador actual y los conservados. Las fechas originales ordenan la lista cuando están disponibles.
- La búsqueda alcanza títulos, nombres de archivo, textos y transcripciones cargados. No lee todos los Blobs para indexarlos. Los archivos locales sin texto en el modelo se buscan por nombre; el texto remoto entra al cargarse. Fallos de carga conservan los resultados disponibles y anuncian que la búsqueda puede estar incompleta.
- Cada fila distingue disponibilidad, envío y procesamiento. No se presenta un documento como procesado sólo porque exista en el servidor.
- `MaterialDetail`: lectura, reproducción, transcripción, descarga de originales, reintento de envío/procesamiento, nueva subida y eliminación con confirmación. Las acciones dejaron de ocupar cada fila de la lista.
- Reintentar procesamiento utiliza las rutas existentes y conserva original/transcripción. La nueva subida exige confirmación separada; no se dispara como sustituto automático de un reintento.
- Audio local: Quitar copia local conserva el documento del servidor. En otros documentos se elimina usando la identidad remota correcta y luego se retiran las copias locales, sólo tras confirmar. El borrado del texto derivado no elimina el recurso de audio original del servidor. Un bloqueo de procesamiento devuelve una explicación útil y conserva las copias.
- Las actualizaciones existentes refrescan filas y detalle sin reiniciar búsqueda/filtro. La URL del audio permanece estable ante clones de Blob por cambios de metadata, para evitar reiniciar la reproducción. Lecturas/respuestas tardías de otra sesión o de una petición anterior se descartan.
- `ArchiveDialog`: descarga e importación con mensajes propios, selección de JSON y reintento conservando el archivo. Informa formato/versionado, 25 MiB/10.000 documentos, conflictos y exclusión de audios/notas sin subir del respaldo.
- La importación conserva el contrato de identidad, fechas y aceptación durable del backend; se reutilizan las mismas rutas, sin introducir un flujo alternativo ni sobrescrituras. Se revisaron las rutas de archivo y el límite real del contrato.
- Ajustes mantiene activación, horario, zona y prueba de invitaciones, permisos y logout. El respaldo se puede abrir también desde ajustes.
- Los diálogos contienen/restauran foco, bloquean scroll del fondo mientras están abiertos e impiden cierre durante una operación confirmada en curso.
- No hubo cambios backend, de esquemas ni dependencias nuevas. La grabación protegida/recuperable sigue pendiente de etapa 4.

Validación realizada:

- `npm test`: pasaron los 15 archivos de pruebas. Las pruebas existentes de captura, invitaciones, sincronización, audio, archivos y exploración siguen pasando.
- `tests/material-model.test.mjs`: 8 pruebas de identidad explícita, audio/documento derivado, ambigüedad, copias pendientes, estados independientes, versiones de procesamiento, búsqueda y semántica de eliminación. Pasaron también tras el último ajuste de fecha de una copia pendiente.
- `tests/material-ui.test.mjs`: 13 pruebas de navegación/listado, búsqueda/filtros, conservación ante errores remotos, lectura de textos divergentes, eventos con detalle abierto, recuperación de audio, confirmación de borrado, identidad de eliminación, reintentos remotos con clave estable, conflicto/importación con fechas, aislamiento entre cuentas, respuestas fuera de orden, nueva subida fallida, bloqueo de procesamiento y estabilidad del reproductor. Varias comprobaciones se agrupan en un mismo caso.
- `npm run build`, `npm run lint` y `git diff --check`: pasaron.
- Las pruebas UI usan DOM/IndexedDB simulados y respuestas HTTP controladas; no son evidencia de reproducción física ni de procesamiento real del servidor.

Aceptación aún pendiente:

- [ ] Revisar búsqueda, filtros, lista, detalle y archivos a 320–1440 px, incluyendo títulos largos y listas extensas.
- [ ] Probar scroll de diálogos, teclado, reproducción, descargas e importación en Safari/iOS y Chrome/Android reales.
- [ ] Validar reintentos, eventos y aceptación de importación con servidor/SQL/RabbitMQ configurados.

El navegador integrado continúa sin estar disponible (`Browser is not available: iab`). No hubo push, despliegue ni validación de producción.

## 4. Grabación protegida y recuperable

Repositorio principal: `mirror-pwa`; cambios puntuales en `mirror-core` si la composición de segmentos lo requiere. Es la etapa de mayor riesgo funcional.

### 4.0. Validación temprana de formatos

- [ ] Validar al comienzo del trabajo los formatos producidos en Safari/iOS y Chrome/Android: entrega de fragmentos, finalización, reconstrucción y reproducción.
- [x] Distinguir fragmentos de una misma sesión de MediaRecorder de segmentos independientes después de una interrupción.
- [x] Resolver y documentar la composición de segmentos antes de cerrar el diseño de persistencia/subida. No asumir que concatenar Blobs independientes genera un archivo válido.
- [x] Resolver si se requiere ensamblado en servidor: se compone PCM/WAV en el cliente, conservando originales. No cambia el contrato backend, que ya admite WAV; la validación física de codecs sigue pendiente.

### 4.1. Controlador de grabación independiente de la pantalla

- [x] Mover el dueño de grabación a un controlador compartido que sobreviva a la navegación interna.
- [x] Incorporar estados explícitos: solicitando micrófono, grabando, pausado, finalizando, interrumpido, recuperable y error.
- [x] Mantener una barra visible con tiempo efectivo, pausa/continuar y finalizar; el tiempo no depende del número de fragmentos ni de ticks de un intervalo.
- [x] Mantener separación por usuario y sesión; impedir que cambios de sesión o logout mezclen o abandonen una grabación activa sin resolución.

### 4.2. Protección de pantalla

- [x] Solicitar Screen Wake Lock durante grabación activa cuando esté disponible.
- [x] Mostrar el estado confirmado: activo, no disponible, rechazado o liberado.
- [x] Liberar al pausar o terminar; solicitar de nuevo al continuar o volver a primer plano si aún corresponde.
- [x] Mantener operativa la recuperación cuando el sistema no permita o retire la protección.

### 4.3. Persistencia y recuperación

- [x] Añadir almacenamiento de sesiones/fragmentos en IndexedDB con orden, formato, identidad y estado, mediante migración que conserve datos existentes.
- [x] Persistir progresivamente los datos que entregue el grabador; indicar guardado sólo tras confirmar escritura.
- [x] Esperar la entrega final y las escrituras pendientes antes de confirmar la finalización.
- [x] Crear el documento local final de forma recuperable e idempotente; limpiar fragmentos temporales sólo cuando el resultado esté confirmado.
- [x] Detectar sesiones incompletas al reabrir y verificar qué material puede reconstruirse realmente.
- [x] Ofrecer escuchar, descargar, guardar o continuar en un nuevo segmento, conservando lo anterior como parte de la misma nota lógica.
- [x] Ante falta de espacio o error de escritura, conservar el material disponible en memoria, informar la situación y ofrecer respaldo cuando sea posible.
- [x] Conservar original y transcripción durante fallos de subida/procesamiento; reutilizar reintentos existentes.

Aceptación: navegar no detiene la grabación; pausar/continuar conserva el contenido; una interrupción permite recuperar lo efectivamente persistido; terminar o reintentar no duplica notas; los mensajes no prometen duración o material no verificados.

Límites reales: mantener la pantalla activa no garantiza grabación en segundo plano. El sistema puede retirar el wake lock y el navegador puede demorar o suspender eventos de datos al bloquear. Pedir fragmentos periódicos no garantiza persistencia cada N segundos. La protección y la recuperación deben convivir.

Referencias técnicas:

- [MDN: Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)
- [MDN: MediaRecorder dataavailable](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event)

### Avance registrado: 2026-10-14

Implementación: `mirror-pwa`, misma rama `feat/app-refresh-stage1`, commit `4674067`. Decisiones y recorridos de aceptación: `mirror-pwa/docs/voice-recording.md`.

- Controlador compartido por almacenamiento activo, fuera del árbol de captura. Material, Constelaciones y desmontar/remontar el editor conservan el grabador. Barra persistente con pausa/continuación, tiempo monotónico, guardado, reproducción y descarga.
- Al ocultar la aplicación, abandonar la página o recibir mute/ended/error del micrófono, se intenta cerrar el segmento. Volver ofrece continuar, sin prometer grabación en segundo plano. Logout explícito bloqueado hasta resolver el audio; pérdida forzada de sesión detiene tracks y conserva lo ya escrito. Web Locks excluye grabaciones simultáneas entre pestañas cuando está disponible.
- Wake Lock confirmado/rechazado/no disponible/liberado, con liberación de concesiones tardías y protección frente a carreras al pausar/continuar.
- Migración Dexie v7: sesiones y fragmentos ordenados por identidad/segmento/secuencia; cola de escrituras y mensajes confirmados al completar la cola. Cuota/error conserva memoria, ofrece respaldo y reintenta todos los datos antes de finalizar.
- Finalización espera el último dato y las escrituras. Documento con ID estable y limpieza de recuperación en una transacción; no reemplaza notas existentes ni pierde claves/estados de sincronización. Recuperación por cuenta, varias sesiones seleccionables y eliminación sólo mediante confirmación.
- Composición definida antes de persistir: concatenación únicamente dentro del mismo MediaRecorder; continuaciones independientes se decodifican por separado y generan WAV mono/16 kHz/16 bits. Los originales permanecen descargables en Material. No requiere cambios de backend. Un segmento truncado necesita decodificación exitosa antes de aceptar su guardado; si falla se conservan las partes.
- Límite local de salida: 25 MiB, aproximadamente 13 min 39 s para WAV compuesto. Una sola grabación comprimida puede durar más. Componer requiere memoria adicional; errores de formato/memoria/tamaño conservan los originales y permiten respaldo. Esta limitación debe aceptarse junto con las pruebas físicas.
- Se anticipó la protección de actualización de etapa 6: `registerType: prompt`, sin activar una versión nueva ni recargar automáticamente clientes abiertos. Falta comprobar la transición desde la PWA actualmente instalada.

Validación local: `npm run build`, `npm run lint`, `npm test` (16 archivos; grabación 13/13, captura 10/10) y `git diff --check`. Pruebas específicas de persistencia, entrega final, idempotencia, pausa/tiempo, interrupción/reapertura, aislamiento/permiso tardío, cuota, Wake Lock, contenedores incompletos, composición PCM/orden/límite, migración v6→v7, descarte confirmado, exclusión entre pestañas y continuidad como una única nota. UI: navegación material/grafo, remontaje y guardia de logout. Grabador y decodificador de audio controlados: estos resultados no acreditan codecs de teléfonos ni reproducción real.

Pendiente: la validación temprana física de 4.0 no pudo realizarse; el navegador integrado no está disponible. Se definió la composición con el contrato W3C de MediaRecorder y soporte WAV verificado en el backend actual, pero se mantiene abierta la aceptación de formatos. Probar Safari/iOS y Chrome/Android reales, navegador/PWA, WebM/MP4/WAV, bloqueo, llamada, cambio de app, cierre abrupto, reproducción de partes, composición/subida/transcripción, cuota real, actualización y revisión visual. No hubo despliegue, publicación ni verificación contra servidor real. La siguiente implementación es etapa 5; la aceptación física de etapa 4 sigue pendiente hasta contar con esos dispositivos.

## 5. Constelaciones con el estilo aprobado

Repositorio principal: `mirror-pwa`.

- [x] Llevar la composición del prototipo al motor real de Cytoscape: colores, nodos, conexiones, controles y panel de evidencia.
- [x] Definir estilos según tipo/capa y selección, conservando consistencia entre grafo, lista y detalle.
- [x] Adaptar grafo y detalle a mobile, con gestos y lectura cómodos.
- [x] Conservar entrada por nota/emoción, capas de la API, Lista, citas y lectura completa.
- [x] Conservar ramas, posiciones, zoom y desplazamiento al expandir.
- [x] Volver restaura el estado anterior sin ramas añadidas posteriormente; Ordenar redistribuye bajo acción explícita.
- [x] Cambiar de nota abre todas las capas; actualizar conserva el filtro seleccionado.
- [x] Preservar el contexto al abrir una nota y regresar a la exploración.

Aceptación: estética aprobada aplicada a datos reales, incluso grafos densos; filtros y navegación conservan su semántica y trazabilidad; Lista ofrece acceso por teclado.

### Avance registrado: 2026-10-14

Implementación: `mirror-pwa`, misma rama `feat/app-refresh-stage1`, commit `975bdfd`. Decisiones y aceptación pendiente en `mirror-pwa/docs/constellation-redesign.md`.

- Fondo petróleo con luz suave, nodos compactos y etiquetas externas; conexiones discretas, centro destacado y selección mediante contorno/halo. Paleta derivada del prototipo: notas salvia, emociones verde suave, entidades azul y afirmaciones ámbar. La misma clasificación guía grafo, leyenda y lista; se conservan elipses para emociones y clases semánticas de centro/selección. Capas desconocidas siguen visibles con nombre y tono alternativo.
- Controles, selector, filtros, lista, historial y detalle comparten las bases visuales. CSS histórico reemplazado por reglas organizadas; controles táctiles de 44 px, leyenda y acciones que envuelven, sin posiciones absolutas dependientes de alturas fijas.
- Grafo con altura adaptable; detalle lateral cuando hay espacio y debajo en mobile, con enlace para llegar a la selección. Citas editoriales con nota/fecha de origen y lector completo. Texto íntegro en lista/detalle; etiquetas del lienzo acotadas para que nombres extensos no dominen la composición.
- Grafo/Lista conserva la instancia de Cytoscape, posiciones, zoom y pan. La distribución inicial considera etiquetas y se aplaza si el lienzo está oculto; volver a mostrarlo recalcula tamaño sin ajustar el encuadre automáticamente.
- Alternar Por nota/Por emoción conserva el estado de cada exploración. Actualizar la misma nota mantiene el grafo mientras carga y conserva el filtro; errores dejan visible el grafo previo y ofrecen reintento. Cambiar de nota abre todas las capas.
- Se conserva la semántica de expansión en el mismo grafo, snapshots/historial/Volver sin ramas posteriores, Ordenar explícito, evidencia y lectura sin perder contexto. Sin cambios de API, extracción o conexiones inferidas.

Validación local: `npm run build`, `npm run lint`, `npm test` (17 archivos) y `git diff --check`. Nuevos recorridos UI 6/6 con React/JSDOM y Cytoscape real en modo headless: tipos/paleta/lista/evidencia, vista/lector sin perder viewport, refresh/filtro/cambio de nota, error/reintento, expansión/Volver/alternancia y etiquetas largas. Modelo de Constelaciones 17/17, incluidas expansión, posiciones, citas, snapshots y Ordenar con grafos densos. Las respuestas HTTP son controladas; sólo se sustituye el renderer de canvas en los nuevos tests.

Pendiente: Browser no disponible (`iab` ausente; lista de navegadores vacía), por lo que no se acredita aceptación visual, ancho real de texto ni gestos. Revisar 320/375/390/768/1024/1440 px, datos y grafos densos reales, Safari/iOS y Chrome/Android, selección de conexiones, foco/teclado, pan/zoom, contraste y convivencia con barra de audio/áreas seguras. Sin despliegue ni validación contra servidor real. La siguiente etapa es validación integral y publicación, con la publicación como paso posterior autorizado.

## 6. Validación integral y publicación

Repositorios: `mirror-pwa`, `mirror-core` si cambian contratos/audio, `mirror-deploy` sólo si se requieren ajustes de despliegue.

- [x] Ejecutar build, lint y suites existentes relevantes.
- [x] Agregar pruebas de fecha generalizada, conservación de borradores, unificación de material, migración de almacenamiento y persistencia/recuperación del audio.
- [x] Probar contratos e idempotencia de composición de segmentos si hay cambios backend.
- [ ] Revisar visualmente 320, 375, 390, 768, 1024 y 1440 px; textos largos, listas extensas, teclado, foco, contraste, áreas seguras, carga, vacíos y errores.
- [ ] Probar Safari/iOS y Chrome/Android reales, tanto navegador como PWA instalada cuando esté disponible.
- [ ] Audio real: bloqueo automático/manual, cambio de aplicación, llamada, permisos revocados, cierre/reapertura, falta de espacio y desconexión.
- [x] Verificar que la migración conserva notas, audios, transcripciones, borradores y aislamiento por usuario.
- [x] Impedir que una actualización de la PWA fuerce recarga durante grabación o finalización.
- [ ] Completar aceptación en entorno de prueba HTTPS con evidencia de versión y resultados. Ya hay validación de imagen/HTTP en contenedores locales aislados.
- [ ] Publicar sólo como paso posterior autorizado y verificar recorridos reales tras el despliegue.

Aceptación: evidencia separada de implementación, controles automáticos, revisión visual, pruebas de teléfono y publicación. Los criterios que no se puedan comprobar quedan pendientes, identificando la limitación.

### Avance registrado: 2026-10-14

Implementación y evidencia: `mirror-pwa`, misma rama `feat/app-refresh-stage1`, commit `4c6d1bc`. Informe respaldado y archivos JSON en `mirror-pwa/docs/validation/app-refresh-2026-10-14/README.md`. Esta etapa **permanece abierta** por aceptación visual, teléfonos, entorno HTTPS y publicación.

- Suite PWA: 17 archivos aprobados, incluidos 17 casos de audio y los recorridos de material/Constelaciones. Build y verificación de artefactos en producción y desarrollo, lint y diff sin errores.
- Suite backend: 175 aprobados y 107 omitidos por sus propios prerrequisitos. La ejecución ASGI quedó esperando el event loop bajo sandbox; el test aislado y luego la suite completa pasaron fuera del sandbox, con proveedores deshabilitados y endpoints/paths de prueba. No se alteró código funcional del core.
- Integración entre repositorios sin omitir: PostgreSQL 17 y RabbitMQ 4.3.6 nuevos en loopback, migraciones hasta `20261013_09`, API/auth y workers Taskiq reales. Push/DOM/APIs del navegador/SSE controlados. Se verificaron invitaciones, reintento, borrador, respuesta, horario, logout y aislamiento. El codificador WAV y adaptador de subida de producción enviaron audio a la API real: fecha/tamaño/MIME, replay idempotente y bytes originales conservados por usuario; también archivo de texto histórico. Los trabajos de documentos/audio quedaron aceptados/en cola, sin ejecutar modelos externos.
- Imagen Docker de producción construida y probada sólo localmente: Nginx y health, HTML/assets, rutas, iconos productivos y caché `no-store`. El manifest ahora tiene `application/manifest+json`. Evidencia del digest y respuestas en el informe; no se generó un release ni tag remoto.
- Verificación reproducible nueva: `npm run verify:build` (requiere build previo), más `python3 scripts/validate-integration.py` para levantar y limpiar sus servicios temporales. No usa el stack productivo ni descarga imágenes automáticamente. Todos los contenedores de QA quedaron eliminados.
- Se corrigió y agregó regresión para continuar un audio, seleccionar otro y volver al primero: los snapshots conservan todos los segmentos y no reutilizan índices. Al adquirir Web Locks una pestaña desactualizada relee los segmentos actuales; si otra ya guardó/eliminó la sesión, no la sobrescribe. Una lectura fallida de recuperación impide iniciar otra grabación sin revisar lo pendiente. Los fallos de escritura se conservan por sesión para que guardar otro audio no confirme material que sigue sólo en memoria; se mantiene su reserva de Web Locks hasta persistir o descartar esas partes.
- Migración v6→v7 ampliada: conserva nota, Blob de audio, transcripción, fecha, identidad remota, estado/clave de envío, versión de procesamiento y borrador reservado con adjunto. Estas son pruebas con IndexedDB simulado; sigue pendiente el dispositivo real.
- La protección contra actualización quedó verificada en los artefactos: worker sin activación/claim inmediatos y registro sin recarga forzada. No acredita todavía la transición desde el service worker instalado ni la navegación offline real.

Pendiente: Browser continúa no disponible (`iab` ausente; catálogo vacío), sin capturas/layout/gestos acreditados. Safari/iOS y Chrome/Android físicos; audio/formatos/decodificación real, bloqueo, llamadas, muerte/reapertura, cuota; flujo con proveedores; update/offline; revisión responsive y ruta pública Gateway/Cloudflare. Se solicitó la URL/mecanismo de publicación de un entorno de prueba HTTPS; mientras no se identifique, se conserva el límite de validación local. No se publicaron ramas, imágenes, tags o PRs ni se mergeó/desplegó. Publicación preparada en el informe, para el paso posterior autorizado tras la aceptación; no requiere migraciones SQL ni cambios de contratos backend por este rediseño.

## Secuencia y dependencias

Orden acordado: **1 → 2 → 3 → 4 → 5 → 6**. Ejecutar la validación temprana 4.0 al principio para descubrir necesidades del backend. Las pruebas se ejecutan durante cada etapa; la etapa 6 reúne la validación integral y publicación.

La persistencia del audio debe definirse después de validar los formatos; la recuperación debe estar operativa antes de dar por terminada la mejora de grabación. El rediseño no debe sustituir los contratos reales por las simplificaciones del prototipo.

## Ajustes de revisión — 2026-10-15

Implementados en `mirror-pwa`, misma rama `feat/app-refresh-stage1`, commit `0813076`.

- Fecha: al abrir el editor sin fecha elegida se precargan fecha y hora locales actuales. La hora pasa a ser opcional: si se borra o se recupera un borrador sólo con día, se usa 00:00. Se mantienen validación de fechas imposibles, zona local, fecha original, borradores y regreso a Ahora.
- Constelaciones: se sustituyen rellenos y figuras planas por esferas SVG con luz radial, reflejo, sombra y halo, compartidas por tono y disponibles offline. La leyenda/lista acompaña la nueva silueta; el centro es mayor y la selección mantiene aro/halo. No cambia exploración ni evidencia. Se inspeccionó el SVG de una esfera rasterizado como recurso aislado; no se obtuvo captura del grafo completo.
- Tu material: en las filas, el chip de envío se reemplaza por icono de ancho fijo (dispositivo, subiendo, enviado/servidor o error), con nombre accesible y tooltip. Queda un solo chip de procesamiento, sin prefijo repetitivo, en una fila estable; los estados extensos se acotan visualmente y conservan el texto completo accesible. El detalle mantiene los estados completos.

Validación: 17 archivos de pruebas PWA aprobados, incluidos guardado sólo con fecha, precarga local y preservación de contenido ante fechas imposibles; pruebas de grafo actualizadas para la presentación esférica; build, lint, artefactos PWA y diff sin errores. Browser continúa no disponible: quedan pendientes aceptación visual responsive, transiciones de estado en mobile y render real de las esferas en Safari/Chrome. Sin despliegue ni publicación; la etapa 6 mantiene sus pendientes de aceptación/dispositivos.

### Corrección desde captura del usuario — 2026-10-15

`mirror-pwa`, misma rama `feat/app-refresh-stage1`, commit `5dcb226`. La captura mostró el icono de nube visualmente pegado y desalineado respecto del chip. Se reemplazó por check circular de 16 px, con espacio fijo de 24 × 28 px, SVG en bloque y fila flex centrada con separación de 12 px. El icono no se contrae; el chip puede acotarse con elipsis sin invadirlo. La fila reutiliza también la base compartida de badges y mantiene nombres accesibles/tooltip para todos los estados de envío.

Validación: build, lint, 13 pruebas existentes de UI Material y diff sin errores. No se agregaron pruebas que sólo repitan CSS. Browser continúa no disponible; falta comprobar el resultado visual en navegador/mobile. Sin publicación ni despliegue.

## Historial de avance

| Fecha | Trabajo | Evidencia | Pendientes |
| --- | --- | --- | --- |
| 2026-10-14 | Diseño y ajustes del prototipo aprobados; plan registrado en rama desde origin/develop | `mirror-core` · `9142f91`; `prototypes/app-refresh/`; sintaxis y recorridos JSDOM | Implementación real de etapas 1–6; revisión visual y pruebas en dispositivos |
| 2026-10-14 | Etapa 1 implementada localmente | `mirror-pwa` · `feat/app-refresh-stage1` · `eedbbde`; build/lint; 12 archivos de pruebas y UI 14/14 | Aceptación visual/mobile e integración configurada; etapas 2–6; publicación |
| 2026-10-14 | Etapa 2 implementada sobre la misma rama | `mirror-pwa` · `feat/app-refresh-stage1` · `9fa20ef`; build/lint; 13 archivos de pruebas, captura 9/9 | Aceptación visual/mobile y extremo a extremo; etapas 3–6; publicación |
| 2026-10-14 | Etapa 3 implementada sobre la misma rama | `mirror-pwa` · `feat/app-refresh-stage1` · `58129b0`; build/lint; 15 archivos de pruebas, modelo 8/8 y UI 13/13 | Aceptación visual/mobile y extremo a extremo; etapas 4–6; publicación |
| 2026-10-14 | Etapa 4 implementada sobre la misma rama | `mirror-pwa` · `feat/app-refresh-stage1` · `4674067`; build/lint; 16 archivos, grabación 13/13 y captura 10/10 | Aceptación visual, codecs/teléfonos y extremo a extremo; etapas 5–6; publicación |
| 2026-10-14 | Etapa 5 implementada sobre la misma rama | `mirror-pwa` · `feat/app-refresh-stage1` · `975bdfd`; build/lint; 17 archivos, UI Constelaciones 6/6 y modelo 17/17 | Aceptación visual/mobile, gestos y servidor real; etapa 6; publicación |
| 2026-10-14 | Etapa 6: validación automática y runtime local; correcciones de recuperación y manifest | `mirror-pwa` · misma rama · `4c6d1bc`; 17 archivos PWA; backend 175/107 omitidos; integración real aislada; imagen y HTTP local | Aceptación visual/dispositivos/HTTPS, proveedores, PWA instalada/offline y publicación; etapa 6 abierta |

| 2026-10-15 | Ajustes pedidos en revisión: hora opcional, volumen del grafo e iconos de envío | `mirror-pwa` · misma rama · `0813076`; 17 archivos de pruebas, build/lint/artefactos, inspección SVG aislada | Aceptación visual y dispositivos; pendientes de etapa 6 y publicación |

| 2026-10-15 | Corrección de icono y separación en Tu material a partir de captura | `mirror-pwa` · misma rama · `5dcb226`; build/lint, UI Material 13/13 | Comprobación visual/mobile y pendientes de etapa 6 |

### Publicación de ramas y PR — 2026-10-15

Ramas publicadas en `origin` y PR abiertos contra `develop`:

- [mirror-core #33](https://github.com/iotincho/mirror-core/pull/33): `feat/app-refresh-plan`, prototipo, plan y generación durable de títulos bajo demanda.
- [mirror-pwa #28](https://github.com/iotincho/mirror-pwa/pull/28): `feat/app-refresh-stage1`, rediseño completo, recuperación de audio y actualización de títulos.

Ambos PR incluyen alcance, validación local y pendientes de aceptación; están
vinculados entre sí. Esta publicación no acredita ejecución de CI, merge,
publicación de imágenes ni despliegue. Se mantienen los pendientes de navegador,
dispositivos, PWA instalada y proveedores reales de la etapa 6.

### Plantilla para próximas actualizaciones

- Fecha y etapa/tareas:
- Repositorio y commit/PR:
- Comportamiento implementado:
- Validación automática:
- Revisión visual:
- Pruebas en teléfono:
- Publicación y verificación posterior:
- Limitaciones, decisiones y próximos pasos:
