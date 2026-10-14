# El Espejo: plan de rediseño y mejoras de usabilidad

Fecha de acuerdo: 2026-10-14.
Estado general: **diseño aprobado; implementación pendiente**.
Referencia visual: [prototipo navegable](../prototypes/app-refresh/README.md).

Este documento es el registro de alcance y avance del rediseño aprobado. El usuario aprobó el estilo general, la navegación, el botón único de captura, continuar grabando, la protección frente al bloqueo de pantalla y la posibilidad de fechar cualquier nota. La autorización actual comprende documentar y comitear el plan junto con el prototipo; implementar y publicar son pasos posteriores.

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
| 1. Base visual y navegación | Pendiente | — |
| 2. Captura y fecha original | Pendiente | — |
| 3. Material, lectura y ajustes | Pendiente | — |
| 4. Grabación protegida y recuperable | Pendiente | — |
| 5. Constelaciones | Pendiente | — |
| 6. Validación integral y publicación | Pendiente | — |

El prototipo es una referencia de diseño con datos ficticios. No acredita la implementación funcional de estas etapas.

## Bases existentes verificadas

En `mirror-pwa`, `CaptureScreen.tsx` ya alterna entre grabar y enviar según el contenido. Se mejorarán la presentación y los estados, aprovechando esa lógica.

La fecha original ya forma parte del borrador, de `LocalDocument.authoredAt` y del envío al backend. Su edición actualmente aparece sólo en capturas compartidas (`isSharedCapture`). `authored-date.ts` valida fecha/hora local y la convierte a ISO con zona; se reutilizará esta base.

La grabación actual acumula fragmentos en memoria y guarda el Blob al detenerse. El grabador vive dentro de la pantalla de captura y sus tracks se detienen al desmontarla. No solicita protección de pantalla.

Ya existen almacenamiento Dexie separado por usuario, borradores, sincronización, recuperación de procesamiento, importación/exportación y el motor Cytoscape de Constelaciones. El rediseño debe conservar sus contratos y datos.

## 1. Base visual y navegación

Repositorio principal: `mirror-pwa`.

- [ ] Extraer la paleta, tipografía, espaciado, bordes y tamaños del prototipo a estilos compartidos.
- [ ] Unificar botones, campos, etiquetas, estados, diálogos, mensajes e iconos SVG.
- [ ] Usar fondo petróleo, superficies suaves, texto marfil, acento salvia y ámbar en encabezados; errores y acciones destructivas con tratamiento propio.
- [ ] Mantener controles cómodos al tacto, con botones principales de 44 px y jerarquía visual contenida.
- [ ] Incorporar navegación compartida: Capturar, Tu material y Constelaciones.
- [ ] Desktop: sidebar simple, ajustes y cierre de sesión al pie; contenido con ancho máximo.
- [ ] Mobile: navegación inferior, ajustes desde avatar y espacio para áreas seguras.
- [ ] Adaptar también acceso, carga inicial, errores y pantallas vacías.

Aceptación: no hay scroll horizontal a 320 px ni en desktop; textos largos envuelven; teclado móvil y áreas seguras no tapan acciones; foco visible y navegación por teclado; los estados no dependen únicamente del color. Corregir el origen del overflow sin ocultarlo globalmente.

## 2. Captura y fecha original

Repositorio principal: `mirror-pwa`; reutilizar contratos existentes de `mirror-core`.

- [ ] Un único botón de captura: micrófono por defecto; enviar/guardar cuando haya texto no vacío o adjunto; vuelve al micrófono al quitar contenido.
- [ ] Iconos accesibles, tooltip y estados claros de carga, guardado y error. Evitar envíos duplicados.
- [ ] Habilitar Fecha en cualquier captura: texto escrito o pegado, archivo y audio.
- [ ] Permitir fecha/hora, modificación y regreso a “Ahora”; mostrar un resumen junto al editor.
- [ ] Persistir la selección en el borrador y conservarla al navegar, recargar o abrir/restaurar una invitación.
- [ ] Usar `authored_at` para fecha original y conservar `created_at` como incorporación al sistema.
- [ ] Cuando sólo se conozca el día, ofrecer usar 00:00 de manera explícita; mantener calendario y alternativa de entrada manual.
- [ ] Aplicar la fecha elegida también al audio, que actualmente se guarda con la fecha del momento de grabación.
- [ ] Conservar adjuntos, share target, borradores y respuestas a invitaciones con sus asociaciones actuales.

Aceptación: pegar una nota antigua, fecharla, salir y volver, guardar y sincronizar conserva contenido y fecha. La fecha se presenta consistentemente en lista, lector y Constelaciones. Un error de validación o guardado conserva el borrador.

## 3. Tu material, lectura y ajustes

Repositorio principal: `mirror-pwa`.

- [ ] Reemplazar el menú sobrecargado por una pantalla completa de material.
- [ ] Añadir búsqueda y filtros por texto, audio, archivo, pendientes y borradores.
- [ ] Definir explícitamente el alcance de búsqueda según los documentos cargados; no presentar búsquedas parciales como completas.
- [ ] Reunir copias locales/remotas por identificadores y vínculos conocidos, incluyendo audio y su documento derivado; no fusionar por parecido de contenido.
- [ ] Conservar elementos locales sin sincronizar y mostrar claramente su disponibilidad en el dispositivo/servidor.
- [ ] Separar visualmente guardado local, subida pendiente/en curso, procesamiento, listo y error.
- [ ] Llevar lectura, reproductor, transcripción y acciones al detalle de cada nota.
- [ ] Ofrecer descarga del audio, reintento desde la transcripción cuando corresponda, nueva subida y eliminación con confirmación.
- [ ] Actualizar material con los eventos de procesamiento existentes.
- [ ] Incorporar ajustes de invitaciones: activación, horario, zona y prueba, preservando gestión de permisos y sesión.
- [ ] Crear vistas de respaldo/importación, con límites y errores claros. El respaldo JSON no incluye archivos de audio.
- [ ] Conservar identidad, fechas, detección de conflictos y procesamiento durable de documentos importados.

Aceptación: no aparecen duplicados por la convivencia local/remota; ninguna nota pendiente desaparece al cambiar de vista; cada acción se puede usar desde mobile; fallos de sincronización/procesamiento permiten recuperación sin perder original o transcripción.

## 4. Grabación protegida y recuperable

Repositorio principal: `mirror-pwa`; cambios puntuales en `mirror-core` si la composición de segmentos lo requiere. Es la etapa de mayor riesgo funcional.

### 4.0. Validación temprana de formatos

- [ ] Validar al comienzo del trabajo los formatos producidos en Safari/iOS y Chrome/Android: entrega de fragmentos, finalización, reconstrucción y reproducción.
- [ ] Distinguir fragmentos de una misma sesión de MediaRecorder de segmentos independientes después de una interrupción.
- [ ] Resolver y documentar la composición de segmentos antes de cerrar el diseño de persistencia/subida. No asumir que concatenar Blobs independientes genera un archivo válido.
- [ ] Si se requiere ensamblado en servidor, definir su contrato, idempotencia, límites y pruebas; conservar originales y producir una única nota lógica con trazabilidad.

### 4.1. Controlador de grabación independiente de la pantalla

- [ ] Mover el dueño de grabación a un controlador compartido que sobreviva a la navegación interna.
- [ ] Incorporar estados explícitos: solicitando micrófono, grabando, pausado, finalizando, interrumpido, recuperable y error.
- [ ] Mantener una barra visible con tiempo efectivo, pausa/continuar y finalizar; el tiempo no depende del número de fragmentos ni de ticks de un intervalo.
- [ ] Mantener separación por usuario y sesión; impedir que cambios de sesión o logout mezclen o abandonen una grabación activa sin resolución.

### 4.2. Protección de pantalla

- [ ] Solicitar Screen Wake Lock durante grabación activa cuando esté disponible.
- [ ] Mostrar el estado confirmado: activo, no disponible, rechazado o liberado.
- [ ] Liberar al pausar o terminar; solicitar de nuevo al continuar o volver a primer plano si aún corresponde.
- [ ] Mantener operativa la recuperación cuando el sistema no permita o retire la protección.

### 4.3. Persistencia y recuperación

- [ ] Añadir almacenamiento de sesiones/fragmentos en IndexedDB con orden, formato, identidad y estado, mediante migración que conserve datos existentes.
- [ ] Persistir progresivamente los datos que entregue el grabador; indicar guardado sólo tras confirmar escritura.
- [ ] Esperar la entrega final y las escrituras pendientes antes de confirmar la finalización.
- [ ] Crear el documento local final de forma recuperable e idempotente; limpiar fragmentos temporales sólo cuando el resultado esté confirmado.
- [ ] Detectar sesiones incompletas al reabrir y verificar qué material puede reconstruirse realmente.
- [ ] Ofrecer escuchar, descargar, guardar o continuar en un nuevo segmento, conservando lo anterior como parte de la misma nota lógica.
- [ ] Ante falta de espacio o error de escritura, conservar el material disponible en memoria, informar la situación y ofrecer respaldo cuando sea posible.
- [ ] Conservar original y transcripción durante fallos de subida/procesamiento; reutilizar reintentos existentes.

Aceptación: navegar no detiene la grabación; pausar/continuar conserva el contenido; una interrupción permite recuperar lo efectivamente persistido; terminar o reintentar no duplica notas; los mensajes no prometen duración o material no verificados.

Límites reales: mantener la pantalla activa no garantiza grabación en segundo plano. El sistema puede retirar el wake lock y el navegador puede demorar o suspender eventos de datos al bloquear. Pedir fragmentos periódicos no garantiza persistencia cada N segundos. La protección y la recuperación deben convivir.

Referencias técnicas:

- [MDN: Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)
- [MDN: MediaRecorder dataavailable](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event)

## 5. Constelaciones con el estilo aprobado

Repositorio principal: `mirror-pwa`.

- [ ] Llevar la composición del prototipo al motor real de Cytoscape: colores, nodos, conexiones, controles y panel de evidencia.
- [ ] Definir estilos según tipo/capa y selección, conservando consistencia entre grafo, lista y detalle.
- [ ] Adaptar grafo y detalle a mobile, con gestos y lectura cómodos.
- [ ] Conservar entrada por nota/emoción, capas de la API, Lista, citas y lectura completa.
- [ ] Conservar ramas, posiciones, zoom y desplazamiento al expandir.
- [ ] Volver restaura el estado anterior sin ramas añadidas posteriormente; Ordenar redistribuye bajo acción explícita.
- [ ] Cambiar de nota abre todas las capas; actualizar conserva el filtro seleccionado.
- [ ] Preservar el contexto al abrir una nota y regresar a la exploración.

Aceptación: estética aprobada aplicada a datos reales, incluso grafos densos; filtros y navegación conservan su semántica y trazabilidad; Lista ofrece acceso por teclado.

## 6. Validación integral y publicación

Repositorios: `mirror-pwa`, `mirror-core` si cambian contratos/audio, `mirror-deploy` sólo si se requieren ajustes de despliegue.

- [ ] Ejecutar build, lint y suites existentes relevantes.
- [ ] Agregar pruebas de fecha generalizada, conservación de borradores, unificación de material, migración de almacenamiento y persistencia/recuperación del audio.
- [ ] Probar contratos e idempotencia de composición de segmentos si hay cambios backend.
- [ ] Revisar visualmente 320, 375, 390, 768, 1024 y 1440 px; textos largos, listas extensas, teclado, foco, contraste, áreas seguras, carga, vacíos y errores.
- [ ] Probar Safari/iOS y Chrome/Android reales, tanto navegador como PWA instalada cuando esté disponible.
- [ ] Audio real: bloqueo automático/manual, cambio de aplicación, llamada, permisos revocados, cierre/reapertura, falta de espacio y desconexión.
- [ ] Verificar que la migración conserva notas, audios, transcripciones, borradores y aislamiento por usuario.
- [ ] Impedir que una actualización de la PWA fuerce recarga durante grabación o finalización.
- [ ] Validar en entorno de prueba con evidencia de versión y resultados.
- [ ] Publicar sólo como paso posterior autorizado y verificar recorridos reales tras el despliegue.

Aceptación: evidencia separada de implementación, controles automáticos, revisión visual, pruebas de teléfono y publicación. Los criterios que no se puedan comprobar quedan pendientes, identificando la limitación.

## Secuencia y dependencias

Orden acordado: **1 → 2 → 3 → 4 → 5 → 6**. Ejecutar la validación temprana 4.0 al principio para descubrir necesidades del backend. Las pruebas se ejecutan durante cada etapa; la etapa 6 reúne la validación integral y publicación.

La persistencia del audio debe definirse después de validar los formatos; la recuperación debe estar operativa antes de dar por terminada la mejora de grabación. El rediseño no debe sustituir los contratos reales por las simplificaciones del prototipo.

## Historial de avance

| Fecha | Trabajo | Evidencia | Pendientes |
| --- | --- | --- | --- |
| 2026-10-14 | Diseño y ajustes del prototipo aprobados; plan registrado en rama desde origin/develop | `prototypes/app-refresh/`; verificaciones de sintaxis y recorridos JSDOM | Implementación real de etapas 1–6; revisión visual del prototipo y pruebas en dispositivos |

### Plantilla para próximas actualizaciones

- Fecha y etapa/tareas:
- Repositorio y commit/PR:
- Comportamiento implementado:
- Validación automática:
- Revisión visual:
- Pruebas en teléfono:
- Publicación y verificación posterior:
- Limitaciones, decisiones y próximos pasos:
