# El Espejo · Propuesta integral de estilo y uso

[Plan de implementación y seguimiento](../../docs/El_Espejo_Plan_Rediseno_Usabilidad.md). Actualizar el plan a medida que se completen las etapas.

Prototipo navegable aislado, creado el 14 de octubre de 2026 a partir de las funcionalidades actuales de `mirror-pwa`. Está en `mirror-core/prototypes/app-refresh`, junto al prototipo anterior de Constelaciones. No modifica la aplicación, no llama a su API y utiliza datos ficticios. No requiere instalar dependencias.

## Abrir

Desde `mirror-core`:

```sh
python3 -m http.server 5175 --bind 127.0.0.1 --directory prototypes/app-refresh
```

Abrir http://localhost:5175. Las rutas de ejemplo son `#capture`, `#material`, `#graph`, `#settings` y `#login`. El botón **Probar estados** permite simular grabación, interrupción, procesamiento fallido, desconexión y material vacío.

## Dirección visual

Conservar la identidad oscura, íntima y tranquila. Verde petróleo en el fondo, superficies poco contrastadas, texto marfil, acento salvia y ámbar para pequeños encabezados. El color de error se reserva para fallos y acciones destructivas. Los estados tienen texto, además de color.

Tipografía de sistema para controles y lectura de listas; serif para títulos, escritura y lectura larga. Esta combinación es una decisión de la propuesta, a revisar visualmente. No se descargan fuentes externas.

En captura hay un único botón de 44 × 44 px con icono SVG: micrófono si no hay contenido; enviar/guardar cuando hay texto o archivo. Al borrar el contenido vuelve al micrófono. Tiene nombre accesible y tooltip.

Botones principales de 44 px de altura con texto de 12–13 px y relleno contenido. Los secundarios usan borde o fondo transparente. Una acción primaria por grupo. Las acciones infrecuentes viven dentro del detalle o de ajustes, en vez de competir con todas las notas.

## Navegación y material

- Desktop: barra lateral de 236 px (200 px en ventanas intermedias), con Capturar, Tu material y Constelaciones. Ajustes y cierre de sesión al pie. El contenido tiene ancho máximo.
- Mobile: desaparece el sidebar; las tres secciones principales pasan a una navegación inferior con espacio para el área segura. Ajustes se abre desde el avatar.
- Tu material es una pantalla completa, con búsqueda, filtros y una fila por documento. Las acciones de audio, lectura, reintento, subida y eliminación están en el detalle. Títulos y estados pueden envolver texto. Ninguna fila necesita acomodar todos los botones en una sola línea.
- La propuesta reúne copia local y remota por identidad. Esa unificación requiere adaptar la presentación de los dos listados actuales y sus estados; el prototipo no verifica la reconciliación real.
- Se conserva la diferencia entre guardado local, pendiente de sincronizar, procesamiento, listo y error. El respaldo JSON se presenta con su límite real: no incluye archivos de audio.

## Cobertura de funcionalidades actuales

| Funcionalidad | Recorrido en la propuesta |
| --- | --- |
| Usuario/contraseña y Google | Acceso; contraseña visible/oculta; ingreso simulado |
| Texto, Markdown/TXT, fecha y hora | Capturar; Archivo y Fecha |
| Borradores e invitaciones | Borrador de texto en sessionStorage; responder conserva el anterior en la lista de ejemplo |
| Audio | Barra persistente con tiempo, pausa y terminar; no usa el micrófono |
| Documentos locales y servidor | Tu material; filtro por tipo, pendientes y borradores; búsqueda propuesta |
| Lectura y transcripción | Detalle de nota; texto y controles ilustrativos de audio |
| Sincronización y errores | Sincronizar; escenarios sin conexión y procesamiento fallido |
| Reintento, nueva subida, descarga y eliminación | Acciones del detalle con confirmación de eliminación |
| Respaldo/importación | Diálogo propio; exportación real de textos ficticios; importación simulada |
| Constelaciones por nota/emoción | Selector de entrada, filtros por extracción, grafo/lista, evidencia y lectura |
| Expansión, volver, ordenar y actualizar | Expansión de ejemplo y restauración de ramas/filtro; ordenar y actualizar ilustrativos |
| Invitaciones diarias | Ajustes de activación, horario, zona y prueba; simulados |
| Cierre de sesión | Al pie en desktop; en ajustes en mobile; simulado |

El grafo es SVG de muestra: no implementa el motor real, arrastre, pan, zoom ni extracción. El historial restaura el estado sintético; la integración debe conservar también posiciones y cámara. Las capas mostradas son representativas; deben derivarse de las capas que entregue la API, como en la app actual. Los documentos agregados se pierden al recargar; únicamente el borrador de texto persiste durante la sesión de esta propuesta.

## Grabación: problema y propuesta

En el código actual (`CaptureScreen.tsx`, `startRecording`) los fragmentos se acumulan en `chunks` en memoria; `saveAudioRecording` se llama en `onstop`; `recorder.start()` se invoca sin intervalo. No hay una solicitud de Screen Wake Lock. Esto demuestra una ventana de pérdida; no demuestra qué evento específico interrumpe el audio en el teléfono del usuario.

La barra muestra «Pantalla activa mientras grabás» y contempla el estado «No pudimos mantener la pantalla activa». Ambos son simulados aquí; el escenario 07 permite alternarlos. Pausar y continuar conserva el recorrido. No se solicita un wake lock real en esta muestra.

El flujo propuesto combina:

1. Solicitar mantener la pantalla activa mientras se graba cuando el navegador lo permita; mostrar si esa protección está activa o no. Liberarla al terminar y revalidarla al volver a primer plano.
2. Persistir progresivamente los datos que entregue el grabador en almacenamiento local con identidad de sesión y orden de fragmentos. Sólo indicar “guardado” después de confirmar la escritura; ante error, mantener datos en memoria y ofrecer respaldo cuando sea posible.
3. Mantener la grabación bajo un dueño que sobreviva a cambios de pantalla. La barra de grabación sigue visible al navegar y permite pausar o finalizar.
4. Detectar interrupciones y reconstruir el material efectivamente conservado. Al regresar, ofrecer escuchar, descargar, guardar o continuar en un nuevo segmento. No afirmar que se recuperó una duración que no se verificó.
5. Reintentar el procesamiento desde la transcripción existente cuando sea suficiente; conservar original y transcripción durante errores de subida o procesamiento.

La prevención del bloqueo no es una garantía de grabación en segundo plano. El sistema puede liberar el wake lock; los navegadores pueden demorar o suspender la entrega de fragmentos al bloquear. Pedir fragmentos periódicos tampoco garantiza persistencia cada N segundos. La composición y reproducción de segmentos deben validarse por formato: un fragmento aislado no necesariamente es reproducible.

Fuentes técnicas consultadas:

- [MDN: Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)
- [MDN: MediaRecorder dataavailable y límites al bloquear pantalla](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event)

La implementación posterior debe probar bloqueo automático y manual, cambio de aplicación, llamada, permisos revocados, cierre/reapertura, almacenamiento insuficiente y desconexión en Safari/iOS y Chrome/Android reales. Esta propuesta sólo demuestra el recorrido de recuperación.

## Validación realizada y pendiente

Pasaron `node --check` y un recorrido con JSDOM de navegación, búsqueda, lectura, guardado, grabación/pausa/navegación, recuperación, grafo/lista/filtros/historial, ajustes, importación y contraseña. No se hicieron llamadas a la API.

El navegador integrado devolvió `Browser is not available: iab`. No se validaron capturas, layout real, scroll horizontal ni gestos. Antes de integrar: revisar a 320, 375, 390, 768, 1024 y 1440 px; teclado abierto; áreas seguras; foco; textos largos; contraste; y grabaciones reales. El CSS propone contenedores flexibles, límites de ancho y envoltura de texto, sin ocultar el overflow global para disimular problemas.
