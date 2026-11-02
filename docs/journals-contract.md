# Journals · Contratos del núcleo, etapa 1

Estado: núcleo y contratos implementados localmente. Sin persistencia, endpoints,
integración con pregunta diaria ni interfaz. El contenido de preparación es una
fixture sintética; todavía no se instala un template en la plataforma.
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
Esto expresa control optimista; la escritura condicional atómica y los recibos
idempotentes se implementarán en PostgreSQL en la etapa 2. La regla de un recorrido
activo verifica las instancias suministradas por el llamador; no acredita exclusión
concurrente entre procesos. No debe usarse como sustituto de la restricción SQL.

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

`QuestionContextResolver` es el puerto de resolución para exteriorización; todavía
no tiene implementación ni consumidores en producción. Los campos sensibles se
excluyen de `repr` y los errores de validación ocultan inputs en su representación
textual. Eso no vuelve seguro registrar `model_dump()`, `.errors()` o payloads;
los adaptadores deberán emitir sólo códigos y correlación técnica.

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
.venv/bin/python -m ruff check src/core/journals tests/test_journals_contracts.py
python3 scripts/check_architecture.py
python3 scripts/check_repo_docs.py
git diff --check
```

Las pruebas incluyen fronteras exactas, días sin actividad, horarios estacionales,
pausa/reanudación, preservación de fechas tras ajustes, conflictos de revisión,
aislamiento de propietarios, referencias antiguas, proyecciones privadas/públicas
y carga del núcleo con imports de infraestructura bloqueados.

El próximo paso es la etapa 2: puertos de persistencia y transacciones, snapshots
archivados, recibos e índices SQL y reconciliación en el dispatcher existente.
La garantía de concurrencia requiere PostgreSQL aislado. No hay migraciones,
llamadas pagas, API o interfaces verificadas en esta etapa.
