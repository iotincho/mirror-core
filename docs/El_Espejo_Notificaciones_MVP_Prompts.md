# El Espejo — Notificaciones y motor de exteriorización v1

Definición propuesta y prompts de implementación. Fecha: 2026-10-13.

Este documento define el comportamiento deseado. No presupone una inspección del estado actual de los repositorios: el agente debe adaptar nombres, rutas y persistencia a la implementación real.

## 1. Objetivo y alcance

Permitir que el usuario elija recibir una invitación diaria a escribir. El servidor selecciona una pregunta general, la envía por Web Push y la PWA abre el editor con esa misma pregunta al tocar la notificación. La respuesta se guarda como una nota normal y conserva su vínculo con la invitación.

La primera versión prueba el recorrido completo. El motor usa un banco curado de preguntas y selección sencilla, sin invocar un LLM ni leer las notas. Esta es una decisión propuesta para el MVP, no una limitación del motor futuro.

No se agregan nuevos extractores, personalización por notas, chat, repreguntas automáticas, rachas, adaptación automática del horario ni infraestructura analítica adicional. El procesamiento actual de las notas continúa funcionando.

## 2. Experiencia del usuario

1. En ajustes aparece «Invitaciones para escribir», inicialmente desactivado.
2. El usuario elige un horario local. Puede ofrecerse 20:30 como valor inicial editable; no se habilita automáticamente.
3. Al tocar «Activar notificaciones», la app solicita permiso y registra la suscripción push. No pedir permiso al cargar la aplicación.
4. Tras completar permiso, suscripción y configuración, el servidor programa una invitación diaria.
5. La notificación tiene título «Un momento para vos» y muestra una pregunta general breve.
6. Al tocarla, se abre el editor con la pregunta en un encabezado separado del contenido. No insertar la pregunta dentro del texto de la nota.
7. El usuario puede escribir y guardar, o salir sin responder. No se crea una nota vacía al abrir.
8. Puede cambiar el horario, desactivar las invitaciones y usar «Enviar prueba» para comprobar la configuración.

La falta de respuesta no aumenta la frecuencia. No bloquear la captura libre ni exigir responder una invitación para usar la aplicación.

## 3. Banco inicial

IDs y categorías estables. Banco versionado en código o configuración del servidor, sin interfaz administrativa nueva.

| ID | Categoría | Pregunta |
| --- | --- | --- |
| daily_01 | registro | ¿Cómo estuvo tu día? |
| daily_02 | registro | ¿Qué momento de hoy te gustaría dejar escrito? |
| daily_03 | registro | ¿Qué te sorprendió hoy? |
| pleasant_01 | agradable | ¿Qué te hizo sentir bien hoy? |
| pleasant_02 | agradable | ¿Qué disfrutaste hoy, aunque haya sido algo pequeño? |
| pleasant_03 | agradable | ¿Qué te gustaría recordar de hoy? |
| friction_01 | dificultad | ¿Hubo algo que te incomodó hoy y quieras contar? |
| friction_02 | dificultad | ¿Qué fue difícil hoy para vos? |
| friction_03 | dificultad | ¿Hay algo de hoy que todavía te esté dando vueltas? |
| explore_01 | exploración | ¿Qué ocupa tu cabeza en este momento? |
| explore_02 | exploración | ¿Hay alguna idea que quieras poner en palabras? |
| explore_03 | exploración | ¿Qué te gustaría entender un poco mejor de tu día? |

Selección: evitar preguntas usadas en las últimas siete invitaciones programadas; entre las restantes, preferir una categoría distinta a la anterior y luego elegir aleatoriamente. Si un filtro vacía el conjunto, relajarlo de forma explícita; nunca impedir una selección. La primera invitación puede usar daily_01. Una prueba manual no modifica esta rotación ni consume la cuota diaria.

Las preguntas no afirman conocer cómo se siente la persona ni presuponen que tuvo un buen o mal día.

## 4. Separación de responsabilidades

- **Motor:** recibe contexto mínimo —momento, zona horaria e historial de invitaciones— y devuelve un disparador estructurado. En v1 usa únicamente el banco general.
- **Servicio de invitaciones:** persiste la pregunta elegida, registra su procedencia y controla el ciclo de vida.
- **Programador:** determina quién tiene una invitación pendiente según horario y zona horaria. Ejecuta el motor en el servidor.
- **Transporte:** envía la invitación ya persistida mediante Web Push a las suscripciones activas del usuario.
- **PWA:** muestra la notificación y abre la invitación por su ID, conservando la pregunta original.

El motor no envía push ni depende del service worker. En el futuro podrá recibir candidatos de otros proveedores y usar un modelo, conservando el contrato de salida.

## 5. Datos mínimos y contrato

Adaptar estos nombres al repositorio. No crear un framework genérico de proveedores para una sola implementación.

**Preferencia por usuario:** habilitación, hora local HH:mm, zona horaria IANA y próximo vencimiento en UTC. Proponer la zona del dispositivo al configurar y permitir corregirla. No modificarla silenciosamente al viajar. Guardar instantes operativos en UTC y calcular el horario según la zona elegida.

**Suscripción por navegador/dispositivo:** usuario propietario, endpoint push, claves de suscripción, estado activo y fechas. Alta idempotente por endpoint. La suscripción no es la preferencia global. Admitir varias suscripciones por usuario.

**Invitación:** ID, usuario, pregunta exacta, ID y categoría del candidato, origen `generic`, versión del banco/motor, fecha de creación, vencimiento, tipo `scheduled` o `test`, clave de ocurrencia y primera apertura.

**Envío por suscripción:** invitación, suscripción, estado, intentos, próxima reejecución y error sanitizado. Distinguir aceptación por el servicio push de entrega o lectura en el dispositivo: la aceptación no prueba que la persona recibió o vio la notificación.

**Vínculo de respuesta:** nota e invitación. Validar que ambas pertenezcan al usuario autenticado. Conservar la extracción actual; no interpretar la pregunta como texto del usuario.

Salida orientativa del motor:

```json
{
  "source": "generic",
  "candidate_id": "pleasant_01",
  "category": "agradable",
  "question": "¿Qué te hizo sentir bien hoy?",
  "engine_version": "generic-v1",
  "catalog_version": "1"
}
```

El servicio añade ID y metadatos persistentes. El payload push lleva título, pregunta, invitation_id y ruta interna; no lleva credenciales, textos de notas ni información personal adicional.

## 6. Programación y confiabilidad

- Una invitación programada por usuario y fecha local. Reservar esa ocurrencia de forma atómica; evitar duplicados si hay varios workers o ejecuciones repetidas.
- La misma invitación se distribuye a los dispositivos suscritos; no generar una pregunta distinta por dispositivo.
- Mantener banco y selección independientes del envío. Reintentar siempre la misma pregunta.
- Propuesta de ventana de envío: hasta dos horas después del horario elegido. Tras esa ventana, omitir la ocurrencia; no enviar al día siguiente una pregunta sobre «hoy» generada el día anterior.
- Reintentos transitorios acotados dentro de esa ventana. Invalidar suscripciones con respuestas 404/410. Revalidar preferencias y suscripción antes de un reintento.
- No prometer entrega exactamente una vez: puede haber incertidumbre si el proveedor aceptó el envío antes de un fallo local. Usar reservation/idempotencia en el servidor y un tag estable por invitación en la notificación para reducir duplicados.
- «Enviar prueba» usa el mismo recorrido, exige suscripción activa y tiene un límite razonable —por ejemplo, una solicitud por minuto por usuario—. No requiere habilitar la programación diaria.
- Desactivar invitaciones detiene nuevas ocurrencias y reintentos pendientes. Una notificación ya enviada puede seguir visible.
- En logout desasociar/desactivar la suscripción de esa sesión/dispositivo en el servidor y desuscribir localmente; no retirar los demás dispositivos del usuario. Si el logout fue offline, reconciliar antes de asociar otra cuenta y no mostrar notificaciones si el dispositivo conserva un estado local de logout. No transferir una suscripción entre cuentas sin un alta autenticada explícita.
- Usar el mecanismo existente de jobs si lo hay. Si no existe, implementar el worker periódico durable más sencillo compatible con el despliegue real. No usar timers en memoria de un proceso web como único mecanismo.

## 7. Contrato funcional de API

Rutas ilustrativas; adaptarlas al estilo real de la aplicación:

- Consultar y modificar preferencias de exteriorización.
- Registrar/actualizar y retirar la suscripción del dispositivo autenticado.
- Obtener la clave pública VAPID, si se usa VAPID; mantener la privada exclusivamente en el servidor.
- Solicitar una invitación de prueba para el dispositivo actual.
- Consultar una invitación propia por ID.
- Registrar su primera apertura de forma idempotente.
- Guardar una nota con un invitation_id opcional, respetando el flujo actual.

Aplicar autenticación, aislamiento multiusuario, validación, límites y protección CSRF conforme al proyecto. Nunca aceptar user_id del cliente como autoridad. No exponer endpoints privados de suscripción ni claves en respuestas o logs innecesarios.

## 8. PWA y apertura

- Integrar push y notificationclick en el service worker existente. No reemplazar su lógica de caché/offline ni registrar un service worker competidor.
- Detectar APIs y permisos; explicar estados no disponible, permiso denegado y falta de instalación cuando corresponda. No afirmar compatibilidad sin comprobar el entorno.
- iOS/iPadOS: Web Push está disponible desde 16.4 para web apps añadidas a la pantalla de inicio; el permiso se solicita mediante interacción explícita. Verificar documentación actual al implementar.
- Al tocar la notificación, enfocar una ventana existente o abrir una nueva con ruta de invitación. No perder un borrador abierto: ofrecer acceso a la invitación preservándolo o confirmar el cambio de editor.
- Si requiere login, conservar la ruta y resolverla después de autenticarse; validar propiedad antes de mostrar contenido. Una cuenta distinta no puede consultar la invitación.
- Si la invitación no existe o no es accesible, ofrecer captura libre con mensaje claro.
- Si no hay conexión, conservar el ID pendiente y reintentar la carga. No inventar otra pregunta ni perder texto ya escrito. No extender el alcance a una arquitectura offline completa si no existe.
- Si la invitación es de otra fecha local, mostrar su fecha de origen y el texto original, sin presentarlo como una pregunta nueva de hoy.

## 9. Prompts para el agente

Ejecutar en este orden. Adjuntar este documento completo en cada etapa para que no se pierdan los contratos. Trabajar en ramas nuevas desde develop en los repositorios involucrados, sin sobrescribir cambios locales ni mezclar trabajo ajeno. No publicar, desplegar ni hacer merge como parte de estos prompts.

### Prompt 1 — Backend y motor general

Implementá en el backend de El Espejo la v1 de notificaciones y motor de exteriorización definida en el documento adjunto. El objetivo es una invitación diaria voluntaria con una pregunta general, sin leer notas ni usar un LLM.

Primero inspeccioná AGENTS.md, autenticación multiusuario, persistencia/migraciones, creación de notas, configuración y despliegue/jobs existentes. Trabajá en una rama nueva desde develop. Resolvé decisiones rutinarias con las convenciones del repo; no inventes rutas ni agregues infraestructura si ya hay un equivalente. Si una decisión depende de un dato realmente ausente, señalá ese bloqueo y continuá con las partes independientes.

Implementá el banco de doce preguntas, selector con rotación, contrato del motor, preferencias con zona horaria, suscripciones, invitaciones persistentes, vínculos con notas, APIs autenticadas, programación durable, Web Push, prueba manual, idempotencia por ocurrencia y envío por dispositivo, reintentos acotados e invalidación de endpoints. Usá aislamiento por usuario en todas las lecturas/escrituras. El worker y el endpoint de prueba deben usar el mismo servicio de generación y envío.

Conservá la extracción actual y los contratos de notas existentes. Usá comentarios en inglés y funciones tipadas cuando el lenguaje lo permita. Documentá variables nuevas —incluyendo generación/configuración de VAPID si corresponde—, migraciones, arranque del worker y contrato API necesario para la PWA. No incluyas secretos ni datos de notas en logs.

Probá comportamiento significativo: horario local/UTC, bordes de fecha y horario de verano con una zona que lo use, concurrencia de ocurrencias, exclusión multiusuario, retry sin reselección, suscripción expirada, desactivación y vínculo de respuesta. Ejecutá los checks requeridos del repo.

Entregá cambios reales, resumen del contrato final y evidencia de pruebas. Diferenciá lo probado con transporte simulado de lo verificado con push real. Si falta configuración para una prueba real, dejá la implementación completa y explicá el dato faltante; no digas que funcionó en dispositivo.

### Prompt 2 — PWA y experiencia de escritura

Implementá en mirror-pwa la experiencia de notificaciones de exteriorización descrita en el documento adjunto, usando el contrato real del backend implementado en la etapa anterior. Trabajá en una rama nueva desde develop y leé AGENTS.md antes de editar.

Inspeccioná service worker, manifest, router, autenticación, ajustes, manejo de borradores y editor/guardado de notas. Reutilizá su estructura y diseño mobile-first actual. Agregá el control voluntario de invitaciones, horario local y zona horaria editable, habilitación con gesto explícito, estados de permiso/compatibilidad, registro de suscripción y botón «Enviar prueba». Separá errores de permiso, alta de suscripción y preferencias; no mostrar éxito si el backend no confirmó la configuración.

Integrá push y notificationclick en el service worker existente. La notificación debe usar el payload persistido y abrir el editor con invitation_id. Mostrá la pregunta aparte del contenido y guardá el vínculo al guardar una nota normal; no crear notas por apertura ni enviar la pregunta como contenido del usuario. Respetá borradores y el flujo de captura libre.

Manejá apertura con app cerrada o abierta, retorno tras login, ausencia temporal de conexión, invitación de otra fecha, inaccesible o inexistente y cambio de cuenta. Implementá la limpieza de suscripción al cerrar sesión en coordinación con el backend. Evitá exponer preguntas de una sesión anterior en el dispositivo tras un logout local.

Verificá build/checks existentes y pruebas significativas del flujo. Documentá requisitos reales para Android/Chrome e iOS instalado; no afirmar soporte universal. Entregá cambios funcionales y un recorrido manual para probar activación, push, apertura, respuesta, cambio de horario y desactivación.

### Prompt 3 — Integración y cierre

Verificá y corregí la integración entre backend y PWA para la v1 definida en el documento adjunto. Usá las ramas de las dos etapas anteriores, sin rehacer el trabajo ni agregar extractores o LLMs.

Confirmá que variables/configuración, API, modelos, ruta de apertura y metadatos de notas coincidan. Probá el recorrido activar → programar/generar → enviar push → abrir → guardar nota vinculada. Verificá ejecución duplicada del worker, fallos transitorios, permisos denegados, cierre de sesión/cambio de cuenta, invitaciones de otra fecha y preservación de borradores.

Usá reloj controlado para la programación; no esperes un día para probarla ni cambies el reloj del sistema. Verificá push real en un dispositivo compatible cuando exista acceso y configuración; en caso contrario, completá pruebas automatizadas y dejá una guía explícita de la comprobación pendiente.

El criterio de cierre es un flujo funcional con preguntas generales, activación voluntaria, horario local, pregunta estable entre envío y apertura, respuesta como nota normal vinculada y aislamiento multiusuario. Documentá comandos ejecutados, resultados, limitaciones observadas y pasos de configuración. No reportes aceptación del proveedor como lectura o recepción humana. No hagas merge ni despliegue.

## 10. Criterios de aceptación resumidos

- Funciona para un usuario sin notas previas.
- No requiere ni modifica extracciones, embeddings ni llamadas LLM.
- No envía invitaciones sin habilitación voluntaria y suscripción vigente.
- El horario corresponde a la zona elegida, no a la del servidor.
- Reinicios/ejecuciones concurrentes no crean varias invitaciones diarias para la misma ocurrencia.
- La pregunta que se abre es exactamente la persistida para la notificación.
- Abrir o descartar no crea una nota; guardar conserva el vínculo opcional.
- Acceso a preferencias, suscripciones, invitaciones y respuestas aislado por usuario.
- Se pueden cambiar el horario, desactivar y enviar una prueba.
- La app explica los estados de permiso y compatibilidad sin romper la captura normal.

## Referencias técnicas

- Push API: https://developer.mozilla.org/en-US/docs/Web/API/Push_API
- Permisos de notificaciones: https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API/Using_the_Notifications_API
- Web Push en iOS/iPadOS: https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
- Apple, envío de Web Push: https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers

La entrega de push depende del navegador, sistema operativo y conectividad. El horario es una intención de envío del servidor, no una garantía de visualización exacta en el dispositivo.
