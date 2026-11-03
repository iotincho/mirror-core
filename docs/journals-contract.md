# Journals · Contratos y persistencia

Estado al 3 de noviembre de 2026: etapas 1–2 implementadas localmente. Núcleo,
aplicación, persistencia PostgreSQL y reconciliación compuestos. Requiere migración
`20261103_23`; `JOURNALS_ENABLED=false` por defecto. Sin endpoints, vínculo de notas,
integración del generador diario ni interfaz. No habilitado ni desplegado.
Ver [diseño de producto](journals-design.md) y
[plan de implementación](journals-implementation-plan.md).

## Responsabilidad y contratos ejecutables

Journals posee definiciones versionadas, recorridos, etapas y sus reglas temporales.
No crea notas, invitaciones o trabajos. Su núcleo depende sólo de biblioteca
estándar y Pydantic; no importa exteriorización, aplicación o infraestructura.

- [Modelos](../src/core/journals/models.py): `JournalTemplate`, `StageDefinition`,
  `ScheduledStage`, `JournalRun` e `IntentionVersion` inmutables.
- [Reglas](../src/core/journals/rules.py): activación, resolución de etapa,
  ajustes, pausa, reanudación, avance explícito, cierre y edición de intención.
- [Calendario](../src/core/journals/calendar.py): fronteras locales e instantes UTC.
- [Contratos de aplicación](../src/core/journals/contracts.py): entradas tipadas,
  vistas públicas/administrativas, contexto de pregunta y referencias de captura.
- [Fixture JSON](../tests/fixtures/journals_contract_v1.json): template de cuatro
  etapas, activación, fronteras esperadas, vista pública y solicitudes de ejemplo.
- [Pruebas](../tests/test_journals_contracts.py): comportamiento e incompatibilidades
  sin servicios ni proveedores. Los modelos ofrecen `model_json_schema()`.
- [Puertos](../src/core/journals/ports.py),
  [casos de uso](../src/use_cases/journals/manage.py) y
  [consultas](../src/use_cases/journals/query.py): unidades de trabajo por propietario.
- [Persistencia](../src/adapters/storage/postgres/journals.py) y
  [migración](../migrations/versions/20261103_23_journals.py): revisiones y recibos atómicos.

Los contratos de aplicación no son schemas HTTP publicados automáticamente.
Los adaptadores de acceso traducirán sus propios schemas en entregas posteriores.
`ActivateRun` no contiene propietario: la aplicación resolverá el usuario destino
desde acceso administrativo validado. Las operaciones públicas resolverán sesión
y workspace; este núcleo no autentica solicitudes.

## Definiciones y revisiones

El template identifica versión y etapas por una clave estable, con nombre,
objetivo, indicaciones y duración entera de uno a 365 días. Un template/recorrido
contiene entre una y 52 etapas, sin claves duplicadas.

Activar copia la definición. Los IDs de etapa se derivan de recorrido y clave;
dos instancias del mismo template tienen etapas con identidades distintas.
Modificar un template no modifica una instancia previa.

Cada mutación devuelve un `JournalRun` nuevo, con revisión incrementada, fecha,
tipo de cambio y origen `administration`, `user` o `calendar`. No se atribuye una
identidad ficticia a un operador LAN. El llamador debe conservar las revisiones
previas; el núcleo no mantiene una colección global ni escribe su historia.

Las mutaciones exigen `expected_revision` y rechazan reloj anterior a `updated_at`.
La escritura condicional en PostgreSQL comprueba la revisión y conserva la anterior.
Un índice parcial exige un único recorrido con estado persistido `active` por cuenta.
Si ese recorrido ya venció, la activación lo completa y libera el lugar dentro de
su misma transacción, sin esperar al próximo ciclo del dispatcher.

## Calendario adoptado para esta etapa

- El inicio es inmediato y exige fecha con zona. Se conserva una zona IANA por
  recorrido, independiente de futuros cambios de preferencias de notificación.
- La primera etapa comienza al activar y termina a medianoche local de la fecha
  de inicio más su duración. Un inicio a mitad del día deja un primer día parcial.
  Las siguientes etapas son contiguas y avanzan en días de calendario locales.
- Las fronteras incluyen inicio y excluyen fin. Una hora ambigua usa el primer
  instante; una hora inexistente avanza al primer minuto local válido. Los instantes
  se normalizan a UTC. No se equipara un día de calendario con veinticuatro horas.
- `stage_at` resuelve directamente la etapa para un instante, sin mutar el snapshot.
  Puede saltar varias etapas tras una caída del dispatcher. No depende de respuestas.
  El contexto de pregunta se resuelve para su horario programado, incluso si se
  prepara antes del inicio de esa etapa.
- Pausar congela el tiempo restante. Reanudar agrega el intervalo transcurrido
  en UTC al final de la etapa pausada y a las fronteras futuras; su inicio y las
  etapas ya completadas no cambian. Después de una pausa, las fronteras pueden
  dejar de ser medianoche. Esta política conserva el tiempo restante exacto,
  incluso si la pausa cruza un cambio estacional.
- Los ajustes se permiten en activo o pausado. En pausa, el instante de referencia
  es `paused_at`. La lista de etapas restantes comienza con la actual; se pueden
  reordenar, quitar o agregar futuras sin reintroducir una etapa completada.
- Cambiar sólo objetivos o indicaciones conserva las fechas. Cambiar duración
  agrega/resta días de calendario al final vigente y recalcula el tramo futuro
  afectado. Si el nuevo final alcanzaría o precedería el instante de referencia,
  se exige la acción explícita de avanzar.
- Avanzar termina la etapa actual en ese instante y comienza la siguiente allí;
  sus fronteras futuras se calculan por días de calendario desde ese nuevo inicio.
  No se admite avance en el instante exacto de inicio porque crearía un intervalo
  vacío. Las revisiones anteriores conservan sus fechas originales.
- Al finalizar la última etapa, `effective_status` y la vista pública muestran
  `completed` sin esperar al dispatcher. `reconcile` materializa esa finalización
  una sola vez, conservando como fin el instante programado y como `updated_at` el
  de reconciliación. Un avance explícito de la última etapa también completa.

Los estados son `active`, `paused`, `completed`, `closed`. Pausados y terminados no
conducen preguntas. Cerrar conserva todas las etapas en el snapshot. El modo libre
devuelto por el contrato es una selección de contexto, no la emisión de otra
invitación: la integración futura conservará la unicidad diaria y las preferencias.
Completar preparación no activa integración ni afirma que ocurrió una experiencia.

## Contexto público, administrativo y de generación

| Contrato | Contenido | Excluye |
| --- | --- | --- |
| `PublicRunView` | Nombre, propósito, template/versiones, revisión, zona, estado efectivo, etapas visibles y referencia de captura actual. | Propietario, indicaciones internas e intención personal. |
| `AdministrativeRunView` | Vista del recorrido y configuración de indicaciones/etapas. | Entradas e intención personal. |
| `JournalQuestionContext` | Propietario ya resuelto, referencia, propósito, indicaciones, objetivo de etapa e intención versionada. | Agregado completo, notas o referencias de evidencia no verificadas. |
| `FreeQuestionContext` | Modo libre y propietario resuelto. | Pertenencia implícita a un journal. |

La intención se representa aparte en `IntentionVersion`, con texto opcional,
versión y fecha. Borrarla crea otra versión con `text: null`. Su edición también
incrementa la revisión del recorrido para invalidar preparaciones futuras. El
contexto interno anterior conserva la intención que conocía; la configuración
administrativa no empieza a recibirla por haberse editado.

`QueryJournals.resolve` implementa el puerto `QuestionContextResolver`; todavía
no lo consume el generador de invitaciones. Los campos sensibles se
excluyen de `repr` y los errores de validación ocultan inputs en su representación
textual. Eso no vuelve seguro registrar `model_dump()`, `.errors()` o payloads;
los adaptadores deberán emitir sólo códigos y correlación técnica.

## Persistencia y garantías transaccionales de etapa 2

| Tabla | Autoridad |
| --- | --- |
| `journal_templates` | Definición inmutable por ID y versión. Instalar la misma definición es idempotente; cambiarla con la misma versión devuelve conflicto. |
| `journal_runs` | Índice actual: dueño, template/versiones, revisión vigente, estado, fecha final y actualización. |
| `journal_run_revisions` | Snapshot completo e inmutable de cada revisión, con configuración, etapas e intención versionada. |
| `journal_stage_revisions` | Pertenencia relacional por dueño/recorrido/revisión/etapa, posición e intervalos. Los textos permanecen en el snapshot. |
| `journal_mutation_receipts` | Recibo por dueño y clave idempotente: operación, hash de solicitud, revisión resultante y fecha. No guarda textos de intención o notas. |

La intención no tiene otra tabla de historia: vive en los snapshots versionados.
Así la revisión fijada por una pregunta identifica también la intención que conocía.
Las claves foráneas compuestas impiden mezclar dueños al vincular etapas o recibos.
El puntero a la revisión actual es diferido hasta commit: no se puede confirmar
un recorrido sin su snapshot. Índices, revisión y recibo se escriben juntos.
La tabla de entradas/notas y su integración de aceptación pertenecen a etapa 3.

`ManageJournals` coordina activar, ajustar, pausar, reanudar, avanzar, cerrar y
editar intención. Devuelve un recibo técnico, que se confirma después de salir
exitosamente de la unidad transaccional. No devuelve texto privado como respuesta
administrativa. Las vistas se consultan por separado. Las lecturas de intención
son una operación específica para el propietario; no se agregan a la vista admin.

Antes de operar se verifica que la cuenta exista, esté habilitada y tenga workspace
activo. La identidad entregada al caso de uso debe provenir del acceso verificado:
estos métodos no son una API para elegir libremente dueño desde el cliente público.
SQL queda acotado al propietario y sólo devuelve modelos del núcleo o hechos tipados.

El orden de mutación es: comprobar acceso, tomar el lock de la fila de preferencias
de invitación, consultar el recibo, resolver el estado vigente y aplicar la regla,
guardar revisión/índices y recibo, confirmar. Se reutiliza el lock existente de
exteriorización sin cambiar `enabled`, horario, zona ni `updated_at`. Si faltaba
la fila se crea con preferencias deshabilitadas. No se adquieren locks de recursos
o de recorrido antes del lock compartido por cuenta.

La clave idempotente es global entre operaciones de Journals para ese propietario.
El hash `journal-mutation/1` incluye acción, recorrido y comando normalizado, sin
el reloj ni IDs generados durante el intento. Un replay idéntico devuelve el
recibo original, incluso si hubo cambios posteriores; otra solicitud con esa clave
devuelve `journal_idempotency_conflict`. Los recibos no vencen independientemente
de su historia. Un fallo antes de commit deja todo en rollback; un commit confirmado
con respuesta perdida se recupera repitiendo la clave.

Errores SQL o snapshots inválidos se traducen a `JournalStorageUnavailable`
con código `journal_storage_unavailable`, sin payloads ni mensajes de base de datos.
Una revisión obsoleta devuelve `journal_revision_conflict`. No se añaden retries
automáticos: el cliente futuro conservará su clave para recuperar una respuesta
ambigua. El adaptador verifica también que la identidad dentro del snapshot coincida
con las columnas de alcance, y rechaza representaciones corruptas.

## Composición, configuración y reconciliación

`src/bootstrap/journals.py` compone repositorio, acciones y consultas. Comparte el
pool del proceso que lo llama; administración usará sus sesiones independientes
al incorporar las rutas de etapa 5. No se agrega otro proceso, broker o proveedor.
El código del dispatcher invoca reconciliación con errores técnicos seguros y
continúa el resto de sus tareas si Journals no está disponible.

`JOURNALS_ENABLED` se define en settings públicos/worker/dispatcher y administrativos,
con default `false`. Debe mantenerse consistente entre procesos al habilitar la
funcionalidad completa. Deshabilitado, el dispatcher no consulta ni escribe tablas
de Journals; las nuevas mutaciones se rechazan. Los replays de recibos confirmados,
las vistas propias y las referencias históricas se conservan si cuenta/workspace
siguen disponibles. Si se intenta resolver una pregunta para un journal todavía
activo con el flag apagado, se devuelve `journals_disabled`: no se transforma su
contexto silenciosamente en libre. Pausados y terminados sí liberan la conducción.
Todavía no hay integración del publicador que interprete esa suspensión.

Al ejecutar reconciliación habilitada se instala de forma idempotente el
[template inicial versionado](../src/core/journals/templates.py), sin crear recorridos
para usuarios. El template es contenido de producto independiente de la fixture
de pruebas. No instala todavía un catálogo de preguntas por etapa; eso queda en 4.

`ReconcileJournals` consulta como máximo cien propietarios con un activo vencido,
toma el lock de cada cuenta y aplica la regla pura. Dos dispatchers sólo materializan
una finalización. El reloj normal viene de PostgreSQL; pruebas inyectan reloj sin
reescribir reglas. El cambio ordinario entre etapas se resuelve por intervalos,
sin crear una revisión diaria ni generar preguntas atrasadas. Consultar contexto
o estado no requiere que el dispatcher ya haya materializado la finalización.

La migración es aditiva: no modifica cuentas, sesiones, preferencias, invitaciones
u originales anteriores, no activa recorridos ni hace backfill. Aplicar esquema
antes de iniciar una versión con Journals habilitado. Un downgrade a `20261029_22`
**elimina irreversiblemente templates, recorridos, intención histórica y recibos**;
no es una estrategia de recuperación de sus datos. Las notas y sesiones existentes
no se eliminan. Upgrade/downgrade se verifican sólo en bases desechables.

## Referencia de captura y compatibilidad

`EntryReference` contiene `schema_version: "1"`, `run_id`, `stage_id` y
`run_revision`. No acepta propietario ni campos arbitrarios. Se fija al comenzar
la captura y se valida contra la revisión histórica del mismo dueño y recorrido.
Una referencia no concede acceso por sí sola; la aplicación debe recuperar el
snapshot bajo el alcance autenticado antes de llamar al validador.

`ResponseJournalContext` expresa la asociación ya resuelta desde la invitación:

- Si existe, su referencia es la autoridad. Una referencia omitida se deriva de
  ella; una explícita contradictoria produce `journal_reference_conflict`.
- Una invitación libre tiene un contexto de respuesta con referencia nula; no
  permite convertir su respuesta en journal enviando una referencia distinta.
- Sin invitación, una referencia explícita representa escritura espontánea en
  journal. Si se omite, la escritura sigue siendo libre aunque haya un activo.

Un cierre, pausa, eliminación de etapa futura o ajuste posterior no invalida una
referencia válida de un snapshot archivado. El núcleo verifica dueño, recorrido,
revisión y existencia de etapa, sin sustituirlos por la etapa actual. No prueba
que el servidor hubiera emitido previamente una referencia: la resolución y
aceptación durable deberán fijar ese contexto según el contrato de captura.

Referencias ajenas, inexistentes o con otra revisión devuelven el mismo código
seguro `journal_reference_not_found`. El esquema no modifica recibos, originales,
hashes ni respuestas existentes. La propagación por texto/audio, las versiones
de manifiesto y los replays históricos se implementarán en la etapa 3; esta entrega
no afirma compatibilidad de persistencia que todavía no se ha verificado.

## Validación y próximo paso

```sh
.venv/bin/python -m pytest tests/test_journals_contracts.py tests/test_architecture_boundaries.py
.venv/bin/python -m pytest tests/test_journals_application.py
.venv/bin/python -m ruff check src/core/journals tests/test_journals_contracts.py
python3 scripts/check_architecture.py
python3 scripts/check_repo_docs.py
git diff --check
```

Las pruebas de núcleo/aplicación incluyen fronteras exactas, días sin actividad, horarios estacionales,
pausa/reanudación, preservación de fechas tras ajustes, conflictos de revisión,
aislamiento de propietarios, referencias antiguas, proyecciones privadas/públicas
y carga del núcleo con imports de infraestructura bloqueados.

Para SQL, usar `JOURNALS_TEST_DATABASE_URL` con una base cuyo nombre comience por
`journals_test`, migrada al head. La prueba de migración crea otra base con ese
prefijo y la elimina al finalizar; necesita permiso de crear/borrar bases sólo en
esa instancia de pruebas. No apuntar estas suites a un entorno con usuarios.

```sh
.venv/bin/python -m pytest tests/integration/test_journals_postgres.py \
  tests/integration/test_journals_migration.py
```

Las integraciones cubren activaciones y replays concurrentes, índice único incluso
sin reglas de aplicación, revisiones simultáneas, rollback antes del recibo y fallo
al confirmar un FK diferido, aislamiento por dueño, snapshots corruptos, lock
compartido con preferencias, catch-up concurrente y preservación de historia.
La migración se compara con los modelos SQL y conserva cuentas/sesiones/preferencias
sintéticas anteriores. Un skip no valida estas garantías.

El próximo paso es la etapa 3: pertenencia durable de notas de texto y audio.
No hay endpoints, llamadas pagas, interfaces ni experiencia de piloto habilitada.
