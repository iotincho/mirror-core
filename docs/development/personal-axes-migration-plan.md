# Migración de personal axes a arquitectura hexagonal

Estado al 2026-10-26: etapas 1–2 en commits `cd7760c` y `00f0b62`;
etapa 3 completada localmente; etapa 4 pendiente.
No se publicaron cambios ni se desplegaron entornos. Cada etapa conserva su alcance.

Referencia de responsabilidades: [arquitectura](../../ARCHITECTURE.md).
Ubicación actual: [mapa](repository-map.md). El [contrato de ejes](../personal-axes-api.md)
define el comportamiento que debe conservarse; este plan organiza su refactor.

## Objetivo y límites

Mantener `personal_axis` como extractor configurable por el usuario. Separar su
ciclo de extracción de los casos de uso de definición, evaluación, aceptación,
exploración e histórico. Laboratorio continúa siendo su superficie de acceso.

Reutilizar el ciclo `extract()`/`persist()`, artefactos, registros, puertos de
procesamiento y composición existentes. No crear otro motor de jobs, un framework
de plugins ni un contenedor global de dependencias. Crear módulos sólo cuando
tengan una responsabilidad concreta; los nombres siguientes son orientativos.

No cambiar API, funcionalidades de la PWA, prompts, reglas de voz, proveedores,
configuración, cuotas, TTL ni política de retry. No ejecutar backfills ni llamadas
LLM reales para validar. No transformar datos ni reescribir revisiones Alembic
por mover paquetes. Una incompatibilidad de datos exige revisar el alcance antes
de implementar su solución.

## Destino de responsabilidades (origen al iniciar el plan)

| Responsabilidad y origen actual | Destino |
| --- | --- |
| `contracts.py`, reglas de evidencia de `extractor.py`, construcción del perfil | `src/core/extractors/personal_axes/`: modelos, políticas, perfiles y puertos; sin HTTP, ORM ni SDK |
| `extractor.py` | `src/use_cases/extraction/personal_axis.py`: extracción, corrección recuperable y persistencia mediante puertos |
| `AxisPreviews`, `ProcessAxisPreview` | `src/use_cases/personal_axes/`: coordinación de previews, ejecución y aceptación, separadas de su almacenamiento |
| `AxisHistory`, `ProcessAxisHistory`, `expire_axis_previews` | `src/use_cases/personal_axes/`: lotes, ejecución por nota, resultados y limpieza reanudable |
| Autorización, contexto y preferencias de Laboratorio | Casos de uso con identidad verificada, configuración explícita y un puerto de acceso/preferencias |
| ORM, repositorio, cuotas, selección de versiones y metadatos de escritura | `src/adapters/storage/postgres/personal_axes/`, compartiendo transacciones con procesamiento cuando corresponda |
| `preview_store.py` y temporales | `src/adapters/storage/filesystem/personal_axes/`; reutilizar los artefactos comunes de extracción |
| `store.py` y consultas de `exploration.py`/`history.py` | `src/adapters/storage/arcadedb/personal_axes/`; aplicación coordina autorización y verificación de originales |
| `provider.py` y protocolo específico de OpenAI | `src/adapters/providers/openai/personal_axes.py`; implementación de generación, extracción y corrección |
| `routes.py`, `schemas.py`, `history_schemas.py`, estados HTTP | `src/adapters/access/api/public/personal_axes/`; routers reciben casos de uso |
| `dependencies.py`, caché/cierre de clientes y puentes concretos | `src/bootstrap/personal_axes.py`, integrado a los registros y lifespans existentes |

Las políticas de evidencia/voz y el perfil canónico pertenecen a core; la
coordinación que solicita un criterio pertenece a aplicación; mensajes y llamadas
del SDK pertenecen al proveedor. Conservar exactamente los textos serializados:
moverlos no debe modificar fingerprints ni volver obsoleta la cobertura.

## Invariantes para todas las etapas

- Resolver dueño desde sesión/job y workspace. Conservar interruptor global más
  permiso por cuenta; comprobar acceso antes de abrir recursos o reservar trabajo.
- Evaluar de 1 a 5 notas distintas. Mantener IDs/hashes, ajustes acumulativos,
  cambio de muestra explícito y detección de fuentes modificadas o eliminadas.
- La preview no escribe proyecciones activas. Aceptar conserva la especificación
  exacta evaluada, crea una versión inmutable y no llama al proveedor ni promueve
  resultados de muestra. Repetir aceptación funciona aun sin sus temporales.
- Conservar IDs, claves idempotentes, códigos de error, formatos de artefactos,
  fingerprints, `extractor_key` y nombres/versiones de workflows existentes.
- Capturar versiones habilitadas dentro de la transacción de reserva de nota/audio.
  El documento derivado del audio hereda la selección. Retry la conserva;
  reprocess captura la vigente. Importación mantiene su política actual.
- Confirmar juntos recibos, jobs, eventos y outbox cuando el contrato lo exige.
  No exponer sesiones SQL/ORM a aplicación ni separar commits de ese conjunto.
- Recuperar persistencia desde artefactos sin repetir proveedor. No prometer
  exactly-once: una respuesta no guardada puede requerir otra llamada; conservar
  la protección especial ante una corrección de evidencia interrumpida.
- Reemplazar atómicamente sólo `(document_id, axis_id)`, también con cero hallazgos.
  Conservar otros ejes/emociones, versión real y orden de escritura por versión
  y reserva original, aunque los trabajos terminen fuera de orden.
- Pausar afecta reservas nuevas; no borra resultados ni modifica trabajos aceptados.
  El análisis histórico manual conserva su posibilidad de usar un eje pausado.
- Mantener limpieza limitada, locks de workers activos, recuperación de huérfanos
  y rechazo de entregas tardías. No persistir indefinidamente iteraciones rechazadas.
- No registrar contenido, prompts privados, evidencias ni respuestas de proveedores.
  Core expresa errores semánticos; acceso decide HTTP y aplicación decide retry.

## Secuencia de ejecución

Ejecutar 1 → 2 → 3 → 4 → 5. Cada etapa deja los recorridos anteriores operativos
y puede dividirse en entregas pequeñas; no acumular toda la migración antes de validar.

### Etapa 1 — Núcleo y extractor

- [x] Al iniciar, inventariar imports/consumidores de ejes y ejecutar la regresión
  focalizada base. Revisar también Alembic, strings de monkeypatch, registros,
  integración de reservas y consumidores de configuración/orden de escritura.
- [x] Extraer modelos inmutables, validaciones, identidad, evidencia y políticas
  a core. Separar comandos/resultados internos de schemas HTTP y hechos del ORM.
- [x] Definir puertos semánticos necesarios y reutilizar contratos comunes de
  originales/artefactos. Incluir generación de criterio, extracción/corrección,
  proyección y contexto tipado de escritura; nunca `get_session` o `execute_sql`.
- [x] Migrar el extractor, el proveedor y la proyección a sus capas. Inyectar
  configuración, límites y clientes; conservar caché y cierre por proceso.
- [x] Conectar el builder al registro existente. Preview e histórico todavía no
  migrados pueden consumirlo mediante compatibilidad explícita en composición.

**Cierre:** extractor ejecutable con puertos falsos, proveedor ausente al recuperar
persistencia y mismas identidades, perfiles, textos y artefactos. Core/aplicación
canónicos no importan infraestructura ni el módulo anterior.

**Verificar:** `tests/test_personal_axis_extractor.py`,
`tests/test_personal_axis_projection.py`, `tests/integration/test_personal_axis_layer.py`
y regresión de ejecución automática en `test_personal_axis_processing.py`.
Cubrir evidencia inválida, corrección interrumpida, resultado vacío, replay y
aislamiento de otras capas. Agregar imports nuevos a la prueba de aplicación sin SDKs.

Implementación vigente: `core/extractors/personal_axes`, extractor en
`use_cases/extraction/personal_axis.py`, generación de criterio en
`use_cases/personal_axes/build_specification.py`, adaptadores OpenAI/ArcadeDB y
composición en `bootstrap/personal_axes.py`. Se retiraron los cuatro módulos
anteriores y `bootstrap/axis_provider.py`, sin duplicar sus implementaciones.

Validación: 393 pruebas locales y 41 integraciones distintas de ejes aprobadas con
PostgreSQL/ArcadeDB desechables y proveedores determinísticos. Los fixtures
sintéticos capturados antes del cambio conservan fingerprints y un artefacto de
extracción recuperable sin proveedor. La aplicación nueva importa sin SDKs ni ORM.
Se retiraron nueve excepciones obsoletas; las capas canónicas no requieren ninguna.
Alembic no detectó cambios de esquema. La imagen de producción construida desde
fuentes limpias importa todos sus módulos con Python 3.13 y conserva el hash de
especificación anterior. No se hicieron llamadas LLM reales ni despliegues.

Compatibilidad pendiente: el error HTTP anterior queda en `contracts.py`; los
setters `write_order`/`legacy_versions` traducen el binder SQL vigente a
`AxisWriteContext`. Su resolución mediante `AxisWriteContexts` corresponde a etapa 4.
Las rutas, cuotas y SQL de previews/histórico no se declararon migrados.

### Etapa 2 — Definiciones, acceso y exploración

Depende de 1. No migrar aún planificación de previews/lotes completos.

- [x] Ubicar ORM y consultas de definiciones/versiones en PostgreSQL. Devolver
  estados tipados independientes del ORM; acceso construye las respuestas HTTP.
- [x] Separar autorización, contexto y preferencias de Laboratorio del SQL de rutas.
  Reutilizar identidad/cuentas existentes, sin crear un sistema genérico de permisos.
- [x] Migrar catálogo, lectura de versiones y habilitar/pausar a casos de uso.
- [x] Separar consultas de cobertura/hallazgos/vecinos en ArcadeDB de la coordinación
  de lecturas: propiedad, originales, hashes y paginación. No devolver clientes ni
  transacciones del grafo a los casos de uso.
- [x] Conectar routers por inyección y traducir errores semánticos en acceso.
  Mantener lectores aún usados por histórico hasta migrar su último consumidor.

**Cierre:** recorridos migrados de lectura/permisos sin SQL, queries del grafo ni
factories concretas en rutas/casos. Exploración deja de obtener dependencias desde
`AxisPreviews`; histórico conserva compatibilidad hasta su migración en etapa 4.

**Verificar:** suites de acceso/contexto de Laboratorio, proyección y capa; lecturas
de `test_personal_axis_processing.py` y cobertura de `test_axis_history.py`.
Comprobar otro dueño/instancia, acceso deshabilitado, ejes pausados, versiones reales,
cursores de otro scope, evidencia vigente, truncamiento y grafo incompleto.

Implementación vigente: `use_cases/personal_axes/{definitions,laboratory,exploration}.py`
recibe puertos de definiciones, cuentas, originales y lecturas semánticas del grafo.
PostgreSQL conserva ORM/consultas en `adapters/storage/postgres/personal_axes/`;
ArcadeDB encapsula consultas y transacciones en `personal_axis_reads.py`. Acceso
HTTP contiene schemas, serialización y traducción de errores, sin SQL ni factories
concretas. Bootstrap verifica Laboratorio antes de abrir el workspace y compone
lecturas independientes de previews.

Se retiraron los anteriores `models.py` y `schemas.py`. Los archivos heredados de
repositorio/exploración/acceso sólo adaptan a sus consumidores pendientes, sin
consultas duplicadas. `AxisHistory.coverage` delega al lector semántico; su
planificación, SQL transaccional y ejecución siguen pendientes de la etapa 4.
Aceptación mantiene una sola implementación SQL detrás del puente hasta la etapa 3.

Validación: 407 pruebas locales distintas y 41 integraciones de ejes aprobadas con
PostgreSQL/ArcadeDB desechables y proveedores determinísticos. Incluye HTTP de
catálogo/versiones/pausa para otro dueño, acceso revocado antes de workspace,
preferencia monótona, evidencia/procedencia inválidas, originales modificados,
cursores, cobertura vacía, grafo incompleto y truncado. Un test local de workspace
se repitió con su configuración esperada tras detectar un valor de instancia
inyectado por el entorno de integración. No se cambió su implementación.

Alembic no detectó cambios de esquema; no se reescribieron revisiones aplicadas.
La imagen de producción se construyó desde fuentes limpias y, sin red, importó
362 módulos con Python 3.13 y verificó hashes/rutas OpenAPI. El chequeo arquitectónico
conserva 49 excepciones exactas heredadas, ninguna en los módulos canónicos nuevos.
La fixture HTTP/PWA usa la composición nueva; no se ejecutó su recorrido de navegador.
No hubo llamadas LLM reales, publicación ni despliegue.

### Etapa 3 — Previews, aceptación y limpieza

Depende de 1 y 2.

- [x] Migrar solicitud, refinamiento, repetición, progreso, resultados y retry a
  casos explícitos con puertos de temporales, originales y transacción de previews.
- [x] Mantener cuota/reserva concurrente, recibo/job/outbox y reloj autoritativo
  en la unidad de trabajo SQL. Aplicación conserva las decisiones de vigencia.
- [x] Preservar input inmutable en archivos antes del trabajo ejecutable SQL.
  Cubrir fallo entre ambos pasos y replay del huérfano, sin transacción distribuida.
- [x] Migrar `ProcessAxisPreview` y la proyección temporal usando el extractor común.
  Mantener checkpoints de criterio, respuestas y extracciones por nota.
- [x] Migrar aceptación: locks de muestra, fuentes vigentes, revisión coincidente,
  versión base actual y creación idempotente de versión inmutable en PostgreSQL.
- [x] Migrar expiración e invalidación: candidatos/locks/eliminación SQL en su
  adaptador; escaneo y borrado de temporales en filesystem; coordinación en aplicación.
- [x] Conectar sus rutas y retirar implementaciones anteriores sin consumidores.

**Cierre:** `AxisPreviews`, su worker y limpieza no necesitan sesiones, paths,
settings globales ni stores concretos. No reaparece la preview tras un mensaje tardío.

**Verificar:** `test_axis_previews.py` más suites unitarias de extractor/proyección.
Cubrir muestras de 1/3/5, cuotas concurrentes, revisión/base obsoletas, fuente cambiada,
borrado, expiración, aceptación repetida tras limpieza, crash archivo/SQL y limpieza
con worker activo. Preview completa incluye notas desconectadas o sin hallazgos.

Implementación vigente: `previews.py`, `process_preview.py`, `expire_previews.py`
y `preview_projection.py` en `use_cases/personal_axes/`. Reciben originales,
configuración, reloj, clasificación de fallos, temporales y transacciones mediante
puertos. PostgreSQL mantiene cuota concurrente, recibo/job/outbox, reintento y
selección/borrado de expirados. Filesystem conserva formatos e identidad de los
artefactos y el escaneo rotativo limitado. HTTP recibe el caso canónico y serializa
la definición aceptada; se preservan códigos y estados de error anteriores.

Se retiraron los tres casos sueltos de previews, sus archivos/rutas anteriores,
la proyección temporal anterior, dependencias y paginación sin consumidores.
`axis_preview` ya usa el contexto común del ejecutor sin repositorio SQL especial.
El único puente `personal_axes_compat.py` queda para el contexto histórico y
consumidores de pruebas pendientes; no duplica reglas ni SQL. Definiciones y sus
versiones aceptadas mantienen una sola implementación.

Validación: 415 pruebas locales distintas y 42 integraciones de ejes aprobadas con
PostgreSQL/ArcadeDB desechables. Incluye cuota concurrente (una reserva/recibo/outbox),
input previo a SQL y recuperación de huérfano sin cambiar configuración, muestras
1/3/5, generación/refinamiento/repetición, aceptación exacta/repetida tras limpieza,
versión base concurrente, fuentes cambiadas/borradas, locks de worker y notas,
interrupción SQL con checkpoint recuperable y entrega tardía sin recrear temporales.
No se hicieron llamadas a proveedores reales.

Alembic no detectó cambios de esquema. La imagen se construyó y verificó con Python 3.13 desde
fuentes limpias, junto con hashes y OpenAPI. Las 27 excepciones exactas restantes
corresponden al histórico/reservas pendientes y entrypoints externos; las capas
canónicas no requieren ninguna. La fixture HTTP/PWA usa los casos nuevos; no se
acredita aquí su recorrido de navegador. Próximo paso: etapa 4, sin ampliar esta
entrega a planificación de lotes ni cambiar configuraciones ya reservadas.

### Etapa 4 — Histórico, reservas automáticas y orden de escritura

Depende de 1–3. Es la etapa de integración transaccional con procesamiento común.

- [ ] Migrar candidatos/cobertura, planificación, estado, parada y retry de lotes.
  Inyectar definiciones, originales, cobertura y procesamiento; no recibir previews
  como contenedor de dependencias ni reutilizar un lector que exponga transacciones.
- [ ] Migrar `ProcessAxisHistory`: estados propios, fuentes/hash/perfil reservados,
  persistencia del original cuando corresponda y checkpoints sin proveedor repetido.
- [ ] Integrar selección de versiones habilitadas a los puertos transaccionales de
  procesamiento existentes. Lectura de versiones y reserva continúan en la misma
  transacción; la política de configuración aceptada es pura y conserva su formato.
- [ ] Reemplazar `bind_axis_write` por un contexto tipado obtenido mediante puerto:
  versión, reserva original y prioridad. Aplicación lo entrega a proyección; no
  mutar atributos del extractor desde un helper SQL externo.
- [ ] Reemplazar el reset con ORM de `AxisHistoryRequests` por la integración con
  el puerto transaccional común. Retirar tratamiento especial ya innecesario en
  los puentes de ejecución/fallos; conservar clasificación segura y privacidad.

**Cierre:** histórico y ejecución automática usan puertos. La selección y los jobs
ya aceptados no cambian por editar/pausar/deshabilitar ejes ni por mover módulos.

**Verificar:** `test_axis_history.py`, `test_personal_axis_processing.py`,
`test_extractor_jobs.py`, `test_reprocess_notes.py`, `test_audio_invitation_processing.py`
y las pruebas de procesamiento PostgreSQL pertinentes. Cubrir reserva interrumpida,
audio heredado, versión editada concurrentemente, cobertura válida con cero hallazgos,
fuente cambiada/borrada, trabajo activo, cancelación, lease vencido, retry del lote
y trabajo antiguo que termina después de uno nuevo (`superseded`).

### Etapa 5 — Consolidación y cierre

Depende de 1–4.

- [ ] Migrar últimos consumidores, incluido `migrations/env.py`, registros de
  workflows, tests y fixtures HTTP/PWA. No modificar revisiones SQL aplicadas.
- [ ] Eliminar `src/extractors/personal_axes/`, los cuatro casos sueltos y los
  puentes de compatibilidad que ya no se usen, incluido `bootstrap/axis_provider.py`.
- [ ] Retirar todas las excepciones específicas de ejes. Las de entrypoints
  consumidos por mirror-deploy son independientes y conservan su motivo vigente.
- [ ] Actualizar arquitectura, mapa, instrucciones del área y contrato; ejecutar
  regresión conjunta, wheel, imagen y arranque/cierre de API, worker y dispatcher.
- [ ] Contrastar decisiones estables con arquitectura y retirar este plan al
  completarlo; no conservarlo como historial de implementación.

**Cierre:** una sola implementación canónica, sin dependencias de infraestructura
en core/aplicación ni lógica de ejes dentro del ejecutor genérico. La API y sus datos
permanecen compatibles. No quedan guías o consumidores apuntando a carpetas retiradas.

**Verificar:** suite local y familias integradas anteriores con PostgreSQL/ArcadeDB/
RabbitMQ desechables; `alembic check`, recursos del wheel e imagen con Python 3.13.
La validación local con Python 3.14 no reemplaza el arranque de esa imagen. Comprobar
tarea `processing.execute`, workflows/versiones, autorización y cierre de clientes.
Si cambia exposición/contrato, añadir regresión PWA aislada; no afirmar validación
de navegador por haber comprobado sólo backend. Un skip requerido deja el cierre abierto.

## Reglas operativas para ejecutar una etapa

1. Empezar con Git, el mapa y las instrucciones del área. Leer sólo contrato/pruebas
   del recorrido. Inventariar consumidores con el chequeo; no cargar todo axes.
2. Implementar un recorrido verificable. Mantener compatibilidad sólo mientras
   exista un consumidor identificado, sin duplicar lógica. Bootstrap conecta los
   puentes; un caso canónico no importa código heredado para esconder infraestructura.
3. Retirar código y excepciones obsoletos en la misma entrega. No ampliar el
   baseline para permitir infraestructura en las capas nuevas ni exceptuar paquetes.
4. Ejecutar los controles siguientes y las pruebas del recorrido según
   [la matriz](testing.md). Usar puertos falsos en aplicación y motores desechables
   para transacciones/locks; proveedores determinísticos, sin datos personales.
5. Registrar alcance, pruebas/resultados, compatibilidad restante y próximo paso
   brevemente. Marcar casillas sólo al cumplir su cierre; no acumular transcripciones.
   Implementación, commit, publicación y despliegue son acciones distintas.

```bash
python3 scripts/check_architecture.py --inventory /tmp/mirror-axes-inventory.json
python3 scripts/check_repo_docs.py
.venv/bin/python -m ruff check <rutas_modificadas>
.venv/bin/python -m pytest <pruebas_del_recorrido> -ra
git diff --check
```

Los nombres de integración de las etapas corresponden a archivos bajo
`tests/integration/`; las suites unitarias viven en `tests/`. Consultar variables
de fixtures y [servicios aislados](architecture-checks.md) antes de ejecutarlas.

Cada entrega debe poder revertirse sobre los mismos datos/jobs: mantener formatos,
versiones, hashes y entrypoints necesarios hasta adaptar consumidores. No probar
la reversión sobre entornos con usuarios ni ejecutar migraciones operativas como
parte implícita de este refactor.
