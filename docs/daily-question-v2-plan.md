# Plan de implementación: pregunta diaria personal

Estado: etapas 1 y 2 completadas localmente, con backend curado, persistencia
y API. Resultado y límites en [contratos v2](daily-question-v2-contract.md).
Pendientes las entregas 3–5. Diseño validado en el
[prototipo](../prototypes/pregunta-diaria/index.html). El contrato implementado
está en [invitaciones](exteriorization-notifications.md).

## Propósito y decisiones acordadas

Invitar a exteriorizar algo significativo con poco esfuerzo. No buscar completar
temas, diagnosticar ni maximizar respuestas diarias.

- Personalización automática para quienes ya tienen habilitadas las invitaciones;
  no activar las invitaciones de quienes las tienen deshabilitadas.
- Una pregunta a la vista. «Suave», «Un poco más» y «Profundizar» cambian su
  profundidad dentro del mismo tema. La selección no mide el estado emocional.
- «Otra pregunta» cambia de tema. Las opciones ya están preparadas; cambiar no
  espera al LLM. El catálogo curado sigue siendo útil sin contexto y para variedad.
- El push conserva una pregunta inicial. Su texto histórico nunca cambia al
  elegir otra variante en la aplicación. No hace falta enviar todo el paquete por push.
- Invitación → respuesta → inicio. Después del guardado local de una respuesta,
  aparece un modal inferior opcional: «¿Cómo te resultó la pregunta de hoy?».
  Sin subtítulo, texto introductorio ni pantalla de felicitación.
- El modal ofrece «Me sirvió», «No conectó conmigo» y «Sobre este tema…».
  Dentro del mismo modal, esta última opción permite indicar que no era el momento,
  que el tema está cerrado por ahora o que no se quiere hablar de él.
- Cerrar con cruz, Escape, fuera del panel o «En otro momento» no es feedback
  negativo. «Hoy paso» vuelve al inicio sin modal ni nota vacía.
- No responder permite descansar un tema, pero no demuestra desinterés ni cierre.
  El descanso admite preguntas personalizadas sobre otros temas.
- Conservar límites y cierres. Una nueva nota puede habilitar reconsiderarlos si
  expresa intención de retomarlos; una mención aislada o un nuevo rechazo no bastan.
  No construir un panel de reactivación manual en esta entrega.
- La PWA requiere sesión y conexión para acceder a la experiencia. Las notas pueden
  quedar pendientes de sincronizar mediante su mecanismo local existente.

## Base actual y frontera del cambio

El selector puro de `src/core/exteriorization/engine.py` usa doce preguntas y
recencia. `GenerateInvitation` lo invoca durante la transacción del programador.
PostgreSQL garantiza una invitación programada por usuario y fecha local, y la
publica junto a su notificación y trabajos push. No incorporar llamadas LLM a esa
transacción.

`invitation_responses` ya asocia documentos con invitaciones, pero no identifica
tema ni variante. Texto y audio aceptan `invitation_id`; su propagación por
recibos, metadatos, recuperación y documento derivado debe extenderse completa.

En la PWA, `CaptureScreen` ya conserva borradores, usa el botón contextual de
voz/enviar y retorna a captura libre después del guardado local. Los puntos de
integración son `services/invitations-api.ts`, `services/documents-api.ts`,
`storage/documents.ts`, `features/capture/` y `features/voice/`.

## Entrega 1 · Contratos, identidad y políticas

Resolver primero los siguientes contratos con fixtures sintéticas, sin proveedor:

### Paquete diario inmutable

Una invitación sigue representando una ocurrencia diaria. Contiene hasta tres
grupos ordenados de preguntas; cada grupo corresponde a un tema y tiene las tres
profundidades. Cada pregunta tiene un ID estable, texto exacto, profundidad y
referencia al grupo. La opción inicial es «Un poco más» del primer grupo.

- `question` conserva el texto inicial por compatibilidad y para push/bandeja.
- Agregar `default_question_id` y `question_groups` al contrato de lectura.
- Persistir grupos/preguntas asociados a invitación y propietario; no reutilizar
  una fila mutable como pregunta histórica de varias invitaciones.
- Cada grupo conserva procedencia (`generic` o `personalized`), tema, versiones
  del motor/prompts/política y referencias a evidencia. No enviar evidencia,
  ranking o estados internos a la PWA.
- «Otra pregunta» recorre el orden preparado de los grupos, sin crear otra
  invitación diaria. Al cambiar de tema vuelve a profundidad media. Mantener
  orden estable y permitir volver a grupos anteriores.
- Invitaciones antiguas se presentan como un grupo con su única pregunta.
  Ocultar profundidades y cambio de tema cuando no hay alternativas reales.

### Respuesta y feedback

Agregar `invitation_question_id` opcional a documentos JSON y audio multipart,
validando que pertenezca a esa invitación y propietario. Propagarlo por originales,
recibos, manifest, hash idempotente, vínculo SQL y documento derivado del audio.
El texto de la pregunta sigue fuera del contenido de la nota.

Un cliente antiguo que solo envía `invitation_id` responde la pregunta inicial.
Reusar la clave idempotente con otra variante produce conflicto; los replays
válidos conservan la asociación original. Borradores locales antiguos resuelven
la variante inicial sin perder texto o audio.

Proponer `POST /exteriorization/invitations/{id}/feedback`, con pregunta, valor
tipado e `Idempotency-Key`. El endpoint no necesita que la nota ya haya llegado:
la pregunta existe en el servidor, aunque la respuesta esté pendiente de subir.
Usar propiedad y protección de origen del área existente.

Guardar eventos de feedback, separados del estado derivado del tema. Valores:
`helpful`, `unrelated`, `not_now`, `closed`, `do_not_prompt`. Repetir una petición
no duplica sus efectos. Ante eventos de distintos dispositivos, usar orden del
servidor; un evento positivo no revoca un límite explícito. Dismiss y «Hoy paso»
no se traducen automáticamente en esos valores.

Agregar un registro acotado de preguntas efectivamente mostradas mediante
`POST /exteriorization/invitations/{id}/interactions`, con eventos idempotentes
por pregunta. Enviar en segundo plano, sin esperar confirmación para cambiar de
opción. Distinguir pregunta enviada por push, pregunta mostrada y pregunta
respondida; no tratar todas las alternativas del paquete como vistas. Los cambios
de profundidad no deben multiplicar contadores por cada render. «Otra pregunta»
y «Hoy paso» pueden registrarse como navegación, sin interpretarlos como cierre.

### Temas y selección

Mantener IDs de tema propios de cada usuario, evidencia referenciada y estados
derivados revisables. La identidad de tema no depende solamente de un título
generado. El proponente puede vincular evidencia a IDs existentes, y el caso de
uso valida referencias y propiedad; si la correspondencia es dudosa, no fusionar
ni reabrir un tema cerrado.

Definir el tema con alcance concreto: cerrar «los cambios de este trabajo» no
prohíbe cualquier pregunta laboral. En grupos curados sin evidencia personal,
el límite recae sobre ese grupo, sin inventar un tema biográfico del usuario.

Aplicar primero exclusiones y luego selección:

1. Límites explícitos, cierre, pausa y evidencia vigente.
2. Fundamento y pertinencia reciente.
3. Variedad respecto a preguntas anteriores y disponibilidad de opciones suaves.
4. Esfuerzo de respuesta y calidad de formulación.

No usar una suma de pesos inventados ni tasa de respuesta como objetivo. Un LLM
puede proponer un orden y códigos breves de criterio; las exclusiones son reglas
de aplicación que ningún ranking puede sobrepasar. No guardar razonamientos
internos extensos del modelo.

Hipótesis iniciales, configurables y evaluables con ejemplos: una continuación
como máximo antes de pausar siete días; considerar silencio solo después de
48 horas desde una pregunta mostrada sin respuesta aceptada en servidor;
descanso de siete días para
`not_now`; una invitación inicial general al menos cada cuatro ocurrencias.
La ausencia puede incluir notas aún sin sincronizar: solo permite una pausa
temporal. `closed` y `do_not_prompt` no vencen por calendario; requieren nueva
evidencia de intención. Conservar el evento y registrar qué nota motivó reabrir.
Estas cifras no representan medidas psicológicas y pueden ajustarse en evaluación.

**Salida de la entrega:** schemas propuestos, ejemplos JSON, política versionada
y casos esperados. Revisarlos antes de fijar migraciones o prompts definitivos.

Implementado en esta etapa: modelos inmutables y adaptación v1, resolución de
referencias de respuesta, contratos de feedback/interacciones, política pura
`daily-question-policy-v1` y casos sintéticos verificables. Ver
[especificación y ejemplos](daily-question-v2-contract.md). No se agregaron rutas,
migraciones o llamadas a modelos en la etapa 1; la conexión se realizó en la entrega 2.

## Entrega 2 · Backend completo con preguntas curadas

Implementar almacenamiento y API anteriores sin generación de IA todavía:

- Nueva revisión Alembic aditiva para grupos, preguntas, temas y feedback, y
  extensión del vínculo de respuestas. Conservar las filas históricas y su
  pregunta exacta; no inventar retrospectivamente temas o niveles.
- Extender contratos de `core/exteriorization`, casos de uso en
  `use_cases/exteriorization`, adaptadores PostgreSQL/HTTP y composición en
  `bootstrap/invitations.py`. Mantener modelos ORM fuera del núcleo.
- Curar grupos generales con tres preguntas realmente distintas por profundidad.
  El paquete sirve sin contexto personal y como fallback permanente.
- Extender la aceptación/reconciliación de texto y audio con la variante concreta.
- Registrar feedback y aplicar su política. Un límite afecta a todas las
  profundidades del tema, no solo al texto de una pregunta.
- Registrar interacciones mostradas con validación de propietario y pertenencia,
  sin permitir que eventos de cliente cambien fechas del servidor o el paquete.
- Mantener horarios, DST, pruebas push, unicidad diaria, workspace activo y
  atomicidad invitación/notificación/outbox. Las pruebas manuales no consumen
  historial ni lanzan generación paga por defecto.

**Validación:** compatibilidad de clientes antiguos, propiedad cruzada,
pregunta ajena, claves repetidas/conflictivas, respuestas tardías, documentos
borrados, replays de audio sin retranscripción, feedback anterior a sincronizar
la nota, y upgrade sobre una base aislada con invitaciones v1. Si downgrade
elimina historia nueva, documentar esa pérdida; preferir rollback de aplicación
conservando el esquema aditivo.

Implementado en la entrega 2: migración `20261029_18`, snapshot de paquete y
política, índice de preguntas, temas/actividad/reservas, endpoints y trazabilidad
completa en texto/audio. El catálogo es curado; no hay LLM ni cambios PWA. Ver
[contrato operativo y verificaciones](daily-question-v2-contract.md#persistencia-y-validación-de-la-entrega-2).

## Entrega 3 · Flujo real de PWA con catálogo

Llevar las dos primeras vistas y el modal validados a componentes de la PWA,
apoyados en el contrato anterior. No rediseñar toda la pantalla de inicio.

- Estado explícito de invitación y composición; una pregunta visible y selector
  corto. Cambiar profundidad o grupo actúa sobre el paquete ya cargado.
- Separar componentes de invitación y feedback de la coordinación de captura;
  reutilizar tokens, navegación y controlador de voz existentes.
- Persistir en borrador/documento/sesión de voz IDs de invitación, grupo y pregunta,
  más el texto histórico necesario para mostrar la pregunta durante recuperación.
  Conservar borradores de captura libre y respuesta sin mezclarlos.
- Al iniciar voz, fijar la pregunta. Bloquear cambio de profundidad/tema durante
  grabación, finalización o recuperación activa; no perder audio por navegar.
- Volver al inicio y ofrecer el modal únicamente después de confirmar el guardado
  local de texto o audio. No esperar upload, transcripción o extracción. Si falla
  el guardado, mantener la composición y no abrir feedback.
- Mantener el título único del modal y sus opciones. Cerrar no envía feedback ni
  muestra otra pantalla. Responder cierra el panel; como máximo, un aviso breve.
- Guardar una oferta de feedback por respuesta, con estados mostrado/descartado/
  respondido, para no reabrirla automáticamente tras render, reload o sync.
  Persistirla junto a la nota local para recuperar un fallo entre guardado y navegación.
- Cola local de feedback separada de la nota, con identidad idempotente y ámbito
  de cuenta. Un fallo no bloquea captura; conservar la intención y explicar si no
  se pudo confirmar. Descartar resultados tardíos de otra sesión.
- Encolar interacciones al mostrar/cambiar de pregunta, con deduplicación y
  límite de volumen. La sincronización de esta actividad no bloquea el selector.
- Limitar la oferta a la cuenta/vista activa. Si la persona ya navegó, empezó otra
  nota o inició una grabación, no interrumpirla: ofrecer feedback después por una
  acción secundaria. El botón «Hoy paso» no crea notas ni abre el panel.
- Conservar estados existentes de carga, sesión vencida, invitación inexistente
  y sync pendiente. Cargar una invitación requiere red/sesión; elegir entre las
  alternativas recibidas no hace llamadas al modelo.

**Validación:** texto y voz, cambio sin pérdida de borrador, pregunta fijada en
audio, reinicio/recuperación, guardado fallido, nota pendiente de subir, modal
cerrado sin feedback y sin reapertura, escritura libre posterior sin cambiar la
asociación, logout/cambio de cuenta y migración Dexie. Revisar teclado/foco/modal,
reduced motion y pantallas desde 320 px, incluyendo teclado virtual en dispositivo.

**Resultado revisable:** experiencia completa con preguntas curadas y trazabilidad
real. Permite validar la integración antes de introducir incertidumbre del LLM.

## Entrega 4 · Personalización en dos etapas, en segundo plano

### Preparar propuestas

Caso de uso propio de exteriorización, no un extractor que se agrega a cada nota.
Leer originales mediante puertos del propietario, sin depender de capas de
emociones, ejes o disponibilidad del grafo. No introducir una lectura de todas las
notas en cada ciclo del dispatcher; usar una consulta/inventario acotado.

Contexto inicial propuesto: hasta veinte notas de los últimos treinta días,
historial de catorce invitaciones, respuestas vinculadas y estados de sus temas,
con un presupuesto total explícito de tokens. Priorizar evidencia reciente y
respuestas pertinentes; no cortar texto arbitrariamente sin indicar el recorte.
No transcribir audios de nuevo: usar el documento derivado cuando existe.
Importar notas antiguas no las convierte en intención actual de reabrir un tema.

Primera etapa LLM: proponer hasta tres temas con evidencia y tres preguntas de
distinta profundidad para cada uno. Tratar el contenido de notas como datos, no
como instrucciones. Mantener voseo/trato de la persona; evitar diagnósticos,
presuposiciones, preguntas múltiples e insistencia. Validar salida estructurada,
referencias y límites de longitud con fixtures.

### Seleccionar y publicar

Segunda etapa: considerar propuestas y grupos curados; filtrar restricciones y
ordenar por los criterios de la entrega 1. Publicar hasta tres grupos, incluyendo
una alternativa curada. La selección inicial puede ser general aunque haya notas.
No deducir disponibilidad emocional del silencio: los niveles ofrecen control a
la persona y no son un diagnóstico del selector.

Las dos responsabilidades tienen artefactos y versiones separados; no requieren
dos modelos distintos. Evaluar si la segunda etapa necesita llamada LLM o si una
política determinística alcanza con los atributos validados de los candidatos.
Fijar esa elección con los casos de evaluación, antes de habilitarla.

### Ejecución y recuperación

- Reutilizar jobs/outbox/leases/checkpoints y registro de workflows existentes.
  Registrar un workflow interno de preparación en `bootstrap/workflow_registry.py`,
  fuera del feed de procesamiento de documentos. No crear otro scheduler ni
  agregar retries del broker.
- Preparar por usuario/ocurrencia, inicialmente treinta minutos antes del horario;
  cambios de preferencias cancelan o invalidan preparaciones obsoletas.
  Activación con menos margen admite preparación inmediata sin demorar la invitación.
- Congelar versiones/configuración sin secretos y referencias/hashes del contexto
  aceptado. Guardar artefactos de propuestas y selección en almacenamiento durable.
  Si falla la persistencia, reutilizar el artefacto guardado sin otra llamada paga.
  Una caída antes de guardar la respuesta del proveedor aún puede repetir una
  llamada; medirlo y no prometer ejecución remota exactamente una vez.
- Al horario, finalizar en transacción corta: usar el paquete listo o el curado.
  Un resultado tardío nunca sustituye un paquete publicado ni origina otro push.
  Coordinar worker y finalizador con la misma identidad de ocurrencia y fencing.
- Antes de publicar, revalidar workspace, preferencias, restricciones y referencias
  de originales; descartar candidatos con evidencia borrada o límites posteriores
  al snapshot. El fallback no necesita LLM. Nuevos límites también filtran grupos
  disponibles al abrir la invitación, conservando textos históricos inmutables.
- Una respuesta voluntaria a una pregunta histórica sigue siendo aceptable aunque
  el tema haya sido cerrado después. No rechazar una nota para imponer la política
  de futuras invitaciones. La UI aplica los límites conocidos y refresca al abrir;
  dispositivos con una vista ya cargada pueden tener restricciones desactualizadas.
- Acotar tiempo, tokens, llamadas, concurrencia y vigencia de artefactos. No
  registrar notas, preguntas privadas, transcripciones ni payloads del proveedor.
  No conservar copias completas del contexto fuera del original; almacenar solo
  referencias y los artefactos mínimos para recuperación.

**Validación:** dos workers/dispatchers, jobs duplicados, broker caído, fallos tras
cada checkpoint, proveedor lento/fallido/salida inválida, carrera fallback/resultado,
notas borradas, cierre posterior a preparación y preferencia desactivada. Verificar
que no se modifica una invitación publicada ni se repite una etapa ya guardada.

## Entrega 5 · Evaluación y habilitación operativa

1. Dataset sintético de temas abiertos, cierre explícito, rechazo, silencio,
   contradicciones, reaparición con y sin intención, poca evidencia y variedad.
   Evaluar fundamento, respeto de límites, esfuerzo, progresión de profundidad y
   decisión de usar catálogo; no solo si la pregunta suena bien.
2. Evaluación del proveedor real solo con contenido sintético y autorización
   específica para llamadas pagas. Una suite con proveedor simulado no valida
   calidad del LLM real. Las notas/audio privados necesitan autorización separada.
3. Configuración operativa tipada: modo de motor, modelos/prompts/versiones,
   límites de contexto/costo, anticipación, pausas y frecuencia general. Documentar
   valores en `.env.example` y contrato, propagados a API/worker/dispatcher cuando
   correspondan. Flag operativo para volver al catálogo sin borrar historial;
   no es un opt-in adicional del usuario.
4. Orden de entrega: esquema/API compatibles → PWA → worker de personalización
   → habilitación operativa. Backend nuevo admite PWA antigua; PWA nueva adapta
   invitaciones históricas. Validar transición del service worker sin recargar
   grabaciones y rollback a catálogo manteniendo respuestas/feedback.
5. Observar preparación a tiempo, fallback por código seguro, latencia/costo,
   recuperación y feedback explícito. Consultar solo agregados y correlación
   técnica; no publicar contenido personal en observabilidad.
6. Probar push y recorrido completo en dispositivo con sesión real, texto y voz,
   sync diferida y recuperación. Aprobación posterior para migrar entornos con
   datos y desplegar; este plan no autoriza esas acciones.

## Verificaciones y documentación durante la ejecución

Backend: suites enfocadas de exteriorización/canales/ingestión/audio y OpenAPI;
integración PostgreSQL, Alembic y runtime con servicios aislados. Usar
`.venv/bin/python -m pytest` y `.venv/bin/python -m ruff check <rutas>` según
[la matriz de pruebas](development/testing.md). Un skip no acredita integración.

PWA: pruebas de contratos, almacenamiento, sincronizador, voz y navegación
afectadas; `npm run lint`, `npm run build` y `npm run verify:build` si cambia
worker/caché/build. Verificar visualmente vistas y modal en navegador, y distinguir
esa evidencia de teclado virtual, micrófono y comportamiento en dispositivo.

Cada entrega actualiza el contrato vigente: invitaciones, respuestas de audio,
runtime y configuración en core; invitaciones, captura/voz y almacenamiento en
PWA. Arquitectura solo cuando cambien responsabilidades o dependencias.
Ejecutar los verificadores documentales de ambos repositorios cuando correspondan.
Al terminar, trasladar decisiones al contrato y retirar este plan resuelto.
