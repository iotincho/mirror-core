# Journals · Plan de implementación

Estado: plan del 2 de noviembre de 2026. Etapas 1–5 implementadas localmente por
autorización del usuario; alcance y decisiones adoptadas en
[contratos de Journals](journals-contract.md). Etapas 6–7 pendientes.
Fuente de producto: [definición de Journals](journals-design.md).
Las decisiones de calendario y contratos de etapa 1 se concretan en esa referencia.
Las propuestas de integración restantes deben validarse antes de la entrega
que dependa de ellas.

## Resultado y alcance

Entregar un recorrido personal activado desde administración, basado en un
template versionado con etapas de avance automático. La pregunta diaria usa el
propósito general, la etapa vigente, los ajustes particulares, la intención y
las notas del recorrido. Texto y audio mantienen su pertenencia histórica.

El primer template contiene las cuatro etapas de preparación descritas en la
definición de producto. El mecanismo es general; preparación e integración no
son estados especiales del runtime. Se incluyen ajustes administrativos,
intención editable por el usuario y consulta de entradas. Se difieren biblioteca
pública, creador de templates para usuarios, integración y análisis especializados.

No se agrega un servicio desplegable, framework, motor de workflows ni extractor.
No se realizan llamadas pagas, migraciones sobre datos reales o despliegues como
parte de la ejecución de este plan sin la autorización correspondiente.

## Base comprobada y diferencias que hay que resolver

- [Arquitectura del backend](../ARCHITECTURE.md): núcleo, casos de uso,
  adaptadores y composición explícita. PostgreSQL mantiene el estado durable;
  originales y grafo conservan sus garantías de aceptación.
- [Pregunta diaria v2](daily-question-v2-contract.md): paquetes inmutables,
  variantes, feedback, límites, preparaciones durables y publicación atómica.
  `PrepareQuestions` y `SelectPreparedQuestions` ya separan generación y publicación.
- `GenerateInvitation` construye primero el catálogo general y puede terminar
  sin consultar la personalización si no encuentra catálogo. Debe elegir el
  contexto antes de construir candidatos para soportar un catálogo de journal.
- `PreparationSnapshot`, el inventario SQL y las claves de preparación actuales
  no contienen recorrido, etapa ni revisión. Hoy se usan hasta veinte notas de
  treinta días y catorce invitaciones; no basta con agregar instrucciones al prompt.
- El proveedor actual sólo se invoca si hay fuentes; las propuestas personales
  requieren evidencia de notas. Journals necesita funcionar también sin entradas.
- La [ingestión durable](deferred-ingestion.md) y la
  [respuesta por audio](audio-invitation-replies.md) ya propagan invitación y
  variante por recibos, originales y derivado. Se extenderá ese mismo camino.
- La [administración LAN](admin-lan.md) es un proceso SQL separado, sin acceso a
  originales o proveedores. Sólo existe una mutación de Laboratorio; Nginx del
  panel limita explícitamente las escrituras a esa ruta.
- La PWA ya fija pregunta y variante al comenzar captura o voz y conserva claves
  de idempotencia por cuenta. Debe fijar también el contexto de journal.

La documentación del panel contiene referencias antiguas de entrypoints. Para
planificar la composición se toma como autoridad `src/bootstrap/administration.py`
y el contrato administrativo vigente del core. Se corregirán las referencias
afectadas al entregar la integración del panel, sin refactors ajenos.

## Responsabilidades y dependencias

| Responsable | Cambio previsto | Frontera |
| --- | --- | --- |
| `src/core/journals/` | Templates, recorridos, etapas, revisiones, pertenencia y reglas temporales; errores y puertos necesarios. | Nueva capacidad justificada por ciclo de vida e invariantes propios. No replica `Document` ni conoce HTTP, ORM o proveedores. |
| `src/use_cases/journals/` | Activar, ajustar, pausar, reanudar, avanzar, cerrar, editar intención, consultar y resolver el contexto efectivo. | Coordina autorización y puertos; no construye clientes ni sesiones SQL. |
| `core/exteriorization` y `use_cases/exteriorization` | Consumir contexto tipado del recorrido; preparar, seleccionar y publicar preguntas dentro de su alcance. | Journals no genera ni publica invitaciones. Exteriorización no decide las reglas de calendario del recorrido. |
| Aceptación en `use_cases/processing`, documentos y audio | Validar y fijar la pertenencia; propagarla por aceptación, recuperación y derivación. | Continúa siendo el único camino de creación de notas y trabajos. |
| `adapters/storage/postgres` | Modelos, consultas acotadas, revisiones, restricciones, unidades transaccionales e índices de pertenencia. | No duplica la política de calendario en SQL ni entrega modelos ORM a aplicación. |
| `adapters/storage/filesystem` | Metadatos originales y artefactos de preparación compatibles con el nuevo contexto. | No sobrescribe originales históricos ni necesita otro repositorio de contenido. |
| Acceso público y administrativo | Schemas y rutas específicas que llaman casos de uso. | Las mutaciones administrativas sólo se registran en el proceso administrativo. |
| `src/bootstrap/` | Inyección y composición en API pública, admin, dispatcher y worker existentes. | Sin construcción de infraestructura desde core o casos de uso. |
| `mirror-pwa` | Feature de Journals; servicios HTTP, captura, voz, persistencia local y navegación. | Sigue su arquitectura de features, services y storage por cuenta. |
| `mirror-admin` | Configuración del recorrido en detalle de usuario y contratos del proveedor HTTP. | Configura el acompañamiento; no incorpora un lector de notas privadas. |

Los contratos de contexto y pertenencia pertenecen a `core/journals`; sus
consumidores pueden depender explícitamente de ellos. Ese núcleo no depende de
exteriorización ni procesamiento. La coordinación entre casos de uso se inyecta
desde bootstrap mediante un puerto concreto de resolución de contexto, evitando
dependencias circulares o un servicio global de contexto.

Las transacciones que cruzan capacidades se expresan mediante los puertos de
unidad de trabajo existentes, ampliados de manera acotada. No se pasan
`AsyncSession`, repositorios privados o clientes por diccionarios de aplicación.

## Decisiones propuestas para cerrar en la entrega 1

### Calendario y ciclo de vida

- Estados iniciales: `active`, `paused`, `completed`, `closed`. Inicio inmediato;
  la programación de activaciones futuras queda fuera del primer alcance.
- Duraciones enteras positivas en días de calendario de una zona IANA fijada al
  activar. Intervalos con inicio incluido y fin excluido; guardar instantes UTC
  y zona, sin asumir días de veinticuatro horas cuando cambia el horario estacional.
- El panel muestra el inicio y fin efectivos antes de activar, incluido que un
  inicio durante el día deja un primer día parcial. Cambiar la zona de notificaciones
  no reinterpreta fechas ya fijadas para el recorrido.
- La etapa se resuelve por el calendario efectivo, nunca por cantidad de respuestas
  ni por número de ejecuciones del dispatcher. Si hubo una caída se alcanza la
  etapa correspondiente, sin emitir invitaciones atrasadas por cada día perdido.
- Pausar congela el tiempo restante; reanudar desplaza las fechas pendientes por
  el intervalo pausado. No permite dos recorridos activos. Un conflicto se devuelve
  explícitamente; no se cierra ni pausa otro recorrido de forma implícita.
- Cambiar duración recalcula etapas futuras desde la frontera afectada. Un cambio
  que haría vencer inmediatamente la etapa requiere la acción explícita de avanzar.
  Las etapas completadas y sus definiciones históricas permanecen inmutables.
- Al terminar la última etapa se completa preparación y vuelve el modo habitual
  de pregunta diaria desde la próxima ocurrencia disponible. No se activa integración
  ni se infiere que ocurrió una toma. Pausar o cerrar también libera la conducción.
- Activar, ajustar, pausar o completar no habilita preferencias de invitación ni
  push deshabilitadas, ni crea una segunda ocurrencia el mismo día.

Resolver el contexto para el instante programado de la pregunta, incluido cuando
se prepara con anticipación y la etapa cambiará antes de publicarla. Revalidar al
publicar frente a pausas, cierres o ajustes. Las lecturas públicas muestran la etapa
efectiva aunque el dispatcher todavía no haya persistido una transición.

### Revisiones, historia e intención

- Versiones publicadas de template inmutables; cada activación copia la definición.
  El primer template se distribuye como contenido versionado del repositorio,
  instalado de forma idempotente. No requiere un editor general de biblioteca.
- Cada ajuste crea una revisión del recorrido y registra fecha, tipo de acción y
  procedencia administrativa. Con administración LAN sin autenticación no se
  atribuye ficticiamente la acción a una persona identificada.
- Cada preparación y pregunta publicada fija recorrido, etapa, revisión de
  configuración e intención usada. Las revisiones quedan disponibles para responder
  preguntas históricas. Cambiar un texto no actualiza una pregunta ya publicada.
- La intención se edita desde PWA, es opcional y conserva versiones anteriores.
  Las síntesis automáticas se difieren. Administración no recibe el texto de
  intención personal ni entradas por el solo permiso de configurar el recorrido.
- Las indicaciones administrativas son orientación delimitada, no instrucciones
  de sistema capaces de anular privacidad, límites o seguridad. Las notas del
  usuario siguen tratándose como datos no confiables.

### Pertenencia, autorización y compatibilidad

- Una nota pertenece como máximo a un recorrido y una etapa/revisión. Para respuestas,
  la asociación se deriva de la invitación validada por propietario; el cliente no
  puede sustituirla por otra. Para escritura espontánea se envía una referencia
  obtenida del contexto del recorrido, validada por el servidor.
- Fijar esa referencia al iniciar borrador o grabación. Permitir guardar capturas
  históricas válidas después de un avance, pausa o cierre; no moverlas a la etapa
  actual ni perder contenido por una transición. La configuración aún editable
  no invalida referencias previamente emitidas.
- Omitir pertenencia mantiene escritura libre y replay anterior. Versionar la
  identidad del manifiesto cuando haga falta; leer primero el formato del recibo
  existente y no recalcular hashes históricos con campos nuevos.
- Las consultas públicas resuelven dueño desde sesión y workspace. En administración
  el destino seleccionado se valida como cuenta real mediante el acceso LAN
  existente; no se convierte un `user_id` del cliente público en autoridad.
- Administración conserva SQL y origen exacto; no incorpora cookies públicas,
  claves de proveedor o montajes de originales. Las nuevas escrituras se habilitan
  por rutas y métodos explícitos, sin abrir un CRUD genérico en el proxy.
- Inicialmente la política de límites conserva identidad por propietario a través
  de etapas y recorridos: crear otro recorrido o cambiar etiquetas no reabre temas.
  El historial usado como contenido queda limitado al journal; los límites de
  seguridad pueden consultarse fuera de él sin incorporar notas ajenas al prompt.

## Entregas y criterios de aceptación

Las entregas son incrementos revisables. El piloto se habilita después de completar
el recorrido integrado; no basta con implementar tablas o un formulario.

### 1. Contratos y reglas puras

Implementada localmente: modelos, reglas, proyecciones, puerto de contexto y
fixtures/pruebas sintéticas. Sin adapters ni garantía SQL de concurrencia; ver
[contrato vigente](journals-contract.md). Los schemas HTTP se definirán en acceso,
sin exponer directamente modelos internos.

Definir modelos y errores en `core/journals`, fixtures sintéticas y contratos
públicos/administrativos. Cerrar las propuestas anteriores con ejemplos ejecutables
de calendario, referencias de captura, revisiones y compatibilidad.

Definir un contrato pequeño de contexto de pregunta que distinga modo habitual y
journal, sin exigir que exteriorización cargue el agregado completo. Separar la
vista pública (nombre, etapa, fechas, objetivo visible) de indicaciones internas.

Aceptación: reglas probadas sin HTTP, SQL, broker ni proveedores; fronteras exactas,
cambios estacionales, salto de varios días, pausa/reanudación, edición concurrente,
una activación por cuenta y conservación de referencias históricas.

### 2. Persistencia y casos de uso del recorrido

Implementada localmente: migración `20261103_23`, snapshots y pertenencia SQL por
etapa, recibos y casos de uso con exclusión por cuenta, consultas históricas y
reconciliación en el dispatcher existente. `JOURNALS_ENABLED` inicia en `false`.
Upgrade/downgrade, compatibilidad de esquema, carreras y rollback se verifican
en PostgreSQL desechable; límites y comandos en [el contrato](journals-contract.md).
No hay API, vínculo de notas o integración del generador en esta entrega.

Crear migraciones Alembic nuevas para templates/versiones, recorridos, etapas,
revisiones, intención y recibos administrativos. Almacenar en SQL configuración e
historia, sin duplicar notas completas. Agregar claves de pertenencia compuestas
por dueño e índices para contexto activo y consulta paginada de entradas.

Implementar activar, ajustar, pausar, reanudar, avanzar, completar y cerrar con
puertos mínimos. Restricción SQL de un activo por propietario; mutaciones con
clave idempotente y revisión esperada para evitar sobrescrituras entre sesiones
del panel. Un replay idéntico devuelve el recibo; otra intención con la misma
clave o una revisión obsoleta devuelve conflicto.

Integrar resolución/reconciliación temporal en el dispatcher existente, por lotes
acotados y con reloj inyectable. Resolver contexto también a demanda evita depender
de la puntualidad del proceso. Las reglas se ejecutan en aplicación/core.

Aceptación: upgrade sobre base aislada con datos anteriores; dos activaciones
concurrentes producen un solo activo; actualización y registro de revisión son
atómicos; repetición de reconciliación no duplica transiciones. Documentar pérdida
de datos de un eventual downgrade antes de ofrecerlo como recuperación.

### 3. Pertenencia durable de texto y audio

Implementada localmente: migración `20261103_24`, referencia opcional de captura
en HTTP, normalización e identidad `entry/1`, pertenencia SQL atómica con aceptación
y handoff de audio, replays/recuperación y borrado/importación protegidos. El
publicador de etapa 4 todavía no produce asociaciones de invitaciones. Ver
[contrato vigente](journals-contract.md#pertenencia-durable-de-originales-etapa-3).

Ampliar los contratos de aceptación y lectura existentes, no crear endpoints de
upload exclusivos de Journals. Propagar la pertenencia normalizada por reserva,
manifiesto, hash versionado, original, aceptación SQL y asociación de entrada.
En audio, conservarla en metadata, transcripción recuperada, documento derivado y
aceptación del hijo. El índice de entradas debe incorporarse al mismo commit
durable que confirma su aceptación, sin escritura posterior de mejor esfuerzo.

Usar los puertos transaccionales de procesamiento para el enlace entre capacidades.
Resolver la validación y fijación bajo las garantías de reserva existentes:
un ajuste concurrente no puede cambiar la pertenencia después de escribir el
original. La recuperación conserva el contexto fijado, sin recalcular la etapa.

Actualizar respaldo/importación y borrado según su contrato: referencias de otro
propietario no conceden pertenencia; no resucitar contenido eliminado desde el
índice. Definir cómo validar referencias en una restauración antes de habilitarla.

Aceptación: texto y voz espontáneos o en respuesta; referencia ajena; contradicción
entre invitación y journal; replay v1/v2; misma clave con otra pertenencia; caída
entre filesystem/grafo/SQL; sincronización después de transición; audio recuperado
sin retranscripción ni extracción repetida. La escritura libre mantiene su contrato.

### 4. Pregunta diaria contextualizada

Implementada localmente el 3 de noviembre de 2026; contrato vigente en
[pregunta diaria de Journals](journals-contract.md#pregunta-diaria-contextualizada-etapa-4).
Incluye migración `20261103_25`, template v2 con catálogo, workflow `/2` y
publicación atómica. Probada con PostgreSQL desechable y proveedores sintéticos;
sin habilitación, llamadas reales ni despliegue. La integración administrativa
se completó en la etapa 5.

Extender el workflow de preparación existente con una nueva versión y contratos
compatibles. Conservar el handler anterior mientras haya trabajos aceptados de esa
versión; no reescribir sus configuraciones ni crear un registro paralelo.

1. Resolver y fijar el contexto para la ocurrencia antes de construir candidatos.
2. Incluir recorrido, etapa y revisión en identidad y vigencia de la preparación,
   además de propietario, horario y versión de preferencias. Cambiar intención o
   configuración invalida preparaciones sin publicar; la nueva revisión puede
   reservar una preparación nueva dentro de las cuotas existentes.
3. Filtrar inventario SQL e historial por recorrido. Incluir entradas de etapas
   anteriores, con prioridad de la actual y límites de cantidad/tamaño. Revisar
   el corte de treinta días para soportar recorridos más largos sin perder el
   propósito ni volcar toda su historia. Leer originales por dueño, sin grafo.
4. Versionar prompt y snapshot para propósito, objetivo, indicaciones e intención.
   Guardar referencias a revisiones inmutables y hashes; no copiar notas completas
   a jobs o logs. Restaurar el mismo input en retry.
5. Incorporar catálogo curado por etapa y revisión, con las tres profundidades.
   Sin notas, usar ese catálogo: no inventar evidencia ni debilitar el contrato
   de propuestas personales. En modo `curated` no se invoca al proveedor.
6. Adaptar la cadencia de alternativa general para que signifique alternativa
   curada del journal. Las identidades de catálogo serán estables por tema y
   propietario; una nueva etapa/revisión no debe evadir un límite anterior.
7. Revalidar contexto, fuentes, límites y preferencias al aceptar preparación y
   al publicar. Una preparación obsoleta no se convierte en pregunta libre.
   Si falla el proveedor, usar catálogo elegible del contexto actual; si falta,
   omitir la ocurrencia con código seguro, conservando la reserva diaria.
8. Guardar contexto histórico junto a invitación, procedencia, índices, bandeja y
   outbox en la transacción existente. Un resultado tardío no reemplaza la pregunta
   publicada ni dispara otro push.

Al cambiar propósito/objetivo se debe revisar la compatibilidad del catálogo
curado del recorrido. El panel debe permitir ajustarlo o marcarlo no utilizable;
no prometer que el catálogo original sirve para cualquier objetivo personalizado.
No se genera un fallback mediante LLM dentro de la transacción de publicación.

Conservar los locks existentes de preferencias y recursos, revisar el orden de
adquisición para las nuevas operaciones y probarlo con concurrencia real. Usar
exclusión por cuenta compartida entre activación, ajustes y publicación; no tomar
locks en orden inverso desde administración. Las llamadas al proveedor quedan
fuera de transacciones SQL y los conflictos de recursos respetan el mecanismo
no bloqueante existente.

Aceptación: primer día sin notas; exclusión de notas libres/otros recorridos;
curado y personalizado; cruce de etapa durante anticipación; ajuste durante llamada;
cierre antes de publicación; borrado de evidencia; caída tras artefacto durable;
límites persistentes; dos dispatchers; una única ocurrencia por día; modo habitual
sin recorrido. Las pruebas no consumen proveedores reales.

### 5. API y panel administrativo

Prototipo diseñado y **aprobado por el usuario** el 3 de noviembre de 2026.
En el repositorio `mirror-admin`: `docs/prototypes/journals/index.html` contiene el
HTML navegable; `docs/prototypes/journals/README.md` registra decisiones, capturas
y revisión técnica. Las referencias entre repositorios se conservan como rutas.
Incluye activación, calendario, edición de etapas futuras, revisión del respaldo,
ciclo de vida, historial y errores/conflictos; revisado en Chrome a 320/390/768/1440 px.
Etapa implementada localmente: API administrativa dedicada, panel conectado,
previsualización autoritativa de calendario, revisión parcial del respaldo,
historial, conflictos y recuperación idempotente de guardados. Se conservó el
alcance completo aprobado, con los ajustes avanzados dentro del editor.
Ver [contrato vigente](journals-contract.md#administración-lan-y-panel-etapa-5).
Validada con PostgreSQL temporal, Chrome y proxies Nginx aislados; sin migrar
datos reales, habilitar el flag o desplegar. El próximo paso es el prototipo PWA
de etapa 6, antes de implementar su interfaz.

Antes de implementar el código de interfaz, diseñar un prototipo navegable con
datos sintéticos y revisarlo con el usuario. Debe cubrir activación desde un
template, calendario y avance automático, edición de etapas, ajustes opcionales,
pausa/reanudación/cierre y estados de carga, error y conflicto de revisión.
Reutilizar el lenguaje visual y los patrones del panel, contemplando móvil y
escritorio. Registrar la referencia al prototipo y las decisiones de la revisión;
el diseño validado es requisito previo al código de interfaz de esta entrega.

Agregar rutas dedicadas bajo `/api/admin`, compuestas en
`src/bootstrap/administration.py`, que llamen casos de uso de Journals. Propuesta
de superficie: listar templates/versiones, listar recorridos de una cuenta,
activar, consultar configuración, ajustar y ejecutar acciones de ciclo de vida.
No registrar esas rutas en el router público ni ampliar el servicio general de
métricas con toda la lógica del journal.

En `mirror-admin`, ampliar `src/providers/contracts.ts`, el adaptador HTTP y
`src/features/users/` para configuración y calendario. Separar tipos de lectura y
mutación; mantener validación, cancelación, no-store y errores seguros. Mostrar
template/versiones, etapa, fechas, avance automático y conflictos de revisión.
Los cambios opcionales se aplican a la instancia y la interfaz lo hace explícito.

Ampliar la lista de métodos/rutas permitidos en
`mirror-admin/nginx/default.conf.template`, con prueba HTTP de su comportamiento.
Actualizar contrato administrativo y runbook; verificar en `mirror-deploy` que
el origen público sigue bloqueando `/api/admin`. No agregar volúmenes de contenido
ni claves del proveedor a admin-api. Configuración del recorrido es el límite
de esta entrega; leer notas privadas requiere un diseño de permisos independiente.

Aceptación: activar y ajustar un usuario sintético; replay de activación tras
respuesta perdida; revisión obsoleta sin pérdida de cambios; cuenta inexistente;
origen cruzado rechazado; error de commit nunca informado como guardado; proxy
permite sólo acciones declaradas. El bundle no incluye fixtures ni secretos.

### 6. API pública y experiencia PWA

Antes de implementar el código de interfaz, diseñar un prototipo navegable con
datos sintéticos y revisarlo con el usuario. Debe cubrir acceso al recorrido,
pregunta diaria contextualizada, etapa y propósito, edición de intención,
historial de entradas, escritura espontánea dentro del journal y acceso a
escritura libre. Incluir estados vacío, pausado, completo, carga, error y captura
en curso durante un cambio de etapa. Seguir la guía visual de la PWA y revisar
navegación, accesibilidad y adaptación móvil/escritorio. Registrar la referencia
al prototipo y las decisiones; el diseño validado es requisito previo al código
de interfaz de esta entrega.

Exponer bajo sesión actual: recorrido activo, listado/detalle de recorridos propios,
etapas, entradas paginadas e intención/versiones. La intención admite edición
idempotente con control de revisión. Las vistas históricas siguen disponibles;
la activación y configuración administrativa no se exponen al usuario público.
Extender la lectura de invitaciones con un contexto público opcional compatible
con paquetes históricos. La pregunta exacta y su identidad no cambian.

En `mirror-pwa`, crear `features/journals/` y el servicio HTTP correspondiente.
Reutilizar componentes, tokens y lector existentes. Integrar con captura e
invitaciones: pregunta de hoy identificada, etapa/propósito visibles, intención
editable, entradas y acción de escritura espontánea. Mantener acceso a escritura
libre sin pertenencia implícita por el solo hecho de haber un journal activo.

Versionar Dexie si los cambios lo requieren y propagar referencias por borradores,
documentos, sincronización y voz. Fijar contexto al comenzar; una actualización
remota no cambia una captura en curso. Proteger datos por cuenta, descartar respuestas
tardías de otra sesión y conservar claves de idempotencia. No activar un service
worker pendiente durante grabación o recuperación.

Aceptación: capturas históricas después de avance/cierre; borrador y audio recuperado;
fallo de upload y replay; cambio de cuenta; conflicto al editar intención; permisos
revocados; journal vacío/pausado/completo; backend antiguo sin campos de journal;
vista móvil y escritorio, foco y lector accesibles. Offline conserva lo capturado;
no se promete navegación remota de Journals sin conexión.

### 7. Validación integrada y preparación del piloto

Con datos sintéticos, recorrer activación → primera pregunta → texto/audio →
adaptación al contexto → ajuste administrativo → cambio automático de etapa →
sincronización tardía → pausa/reanudación → cierre y retorno al modo habitual.
Usar reloj controlado para los cambios temporales. Incluir fallos y concurrencia;
no usar notas privadas para evaluar ni llamar al proveedor real sin autorización.

La evaluación semántica utiliza el marco sintético existente de pregunta diaria:
alineación con objetivo, continuidad sin insistencia, ausencia de preguntas
inductivas y respeto de límites. Una suite con dobles no acredita calidad de un
LLM; la revisión humana del contenido y la aceptación en dispositivo son pasos
separados antes de usarlo con la persona del piloto.

Preparar orden de actualización compatible: esquema aditivo, core capaz de leer
formatos anteriores, panel/PWA y habilitación controlada. La capacidad nueva debe
tener un control de habilitación explícito, apagado por defecto y coherente en
API, admin, worker y dispatcher. Apagarlo impide nuevas activaciones/publicaciones
de journal, conserva lecturas y aceptación de capturas históricas, y no convierte
silenciosamente su contexto en libre. Documentar qué verá el usuario durante esa
suspensión; no reescribir trabajos aceptados ni borrar recorridos.

No marcar el piloto como operativo hasta contar con migración verificada en base
aislada, controles de fronteras, integración completa y aceptación de experiencia.
Aplicar migraciones, publicar o desplegar sobre el entorno real es una acción
posterior que requiere autorización específica. El plan no la concede.

## Verificaciones por responsabilidad

Durante la implementación, ejecutar las pruebas nuevas y las regresiones afectadas
según [la matriz del backend](development/testing.md). No repetir suites ya
aprobadas sin cambios o dudas concretas. Referencias actuales:

| Cambio | Verificación |
| --- | --- |
| Núcleo y casos de uso | Nuevas pruebas de Journals con reloj y puertos falsos; `tests/test_architecture_boundaries.py`; `python3 scripts/check_architecture.py`. |
| Preparación, selección y feedback | `tests/test_daily_question_contracts.py`, `tests/test_daily_question_preparation.py`, `tests/test_channels_application.py` y regresión de exteriorización. |
| SQL y concurrencia de preguntas | `tests/integration/test_question_preparations.py`, `tests/integration/test_daily_question_packages.py` y nuevas integraciones de Journals en bases aisladas. |
| Texto/audio y recuperación | `tests/integration/test_daily_question_ingestion.py`, `tests/integration/test_audio_invitation_processing.py`, pruebas de aceptación/runtime afectadas y nuevos casos de pertenencia. |
| Administración | `tests/test_administration_api.py`, `tests/integration/test_administration.py`, aislamiento de routers y pruebas nuevas de rutas/mutaciones. |
| PWA | Pruebas focalizadas de borradores, voz, actividad y preguntas; `npm run lint`, `npm run build` y pruebas pertinentes. Si cambia almacenamiento/build/worker, `npm run verify:build` y aceptación del escenario afectado. |
| Panel | `npm run check`, `npm run verify:build`, contratos de proveedor y revisión de formularios/conflictos en navegador; proxy en contenedor aislado. |
| Documentación | `python3 scripts/check_repo_docs.py`; chequeo documental de PWA al modificar sus guías; `git diff --check`. |

En backend se usa `.venv/bin/python -m pytest <rutas>` y
`.venv/bin/python -m ruff check <rutas>`. Las integraciones requieren los servicios
y variables opt-in de cada fixture; un skip se informa como límite, no como éxito.
No ejecutar una suite completa con acceso accidental a servicios usados por personas.

Al implementar cada entrega se actualizan los contratos vigentes afectados
(pregunta diaria, ingestión/audio, administración y PWA). La nueva responsabilidad
Journals y sus dependencias se incorporan a arquitectura cuando existan. El plan
no reemplaza esos contratos: al completarlo, consolidar lo implementado y conservar
sólo pendientes que sigan vigentes.

## Orden de trabajo y punto de partida

Secuencia base: **1 → 2 → 3 → 4 → 5 → 6 → 7**. Los contratos de API se fijan en
la entrega 1 para que panel y PWA compartan fixtures. La API pública necesaria
para probar pertenencia puede entregarse junto con 3; no obliga a habilitar aún
la interfaz ni el piloto. En las entregas 5 y 6, la secuencia de interfaz es
**prototipo → revisión y validación con el usuario → implementación → verificación
contra el diseño validado**. Los prototipos pueden prepararse con los contratos
de la entrega 1, sin esperar al backend completo. Cada entrega mantiene funcional
la escritura existente.

El próximo trabajo implementable, cuando se autorice, es la entrega 4 sobre los
contratos y persistencia de etapas 1–3. No comenzar por añadir campos sueltos al
prompt, tablas sin invariantes o una pantalla que gestione el calendario localmente.
