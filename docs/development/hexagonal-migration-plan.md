# Plan de migración a arquitectura hexagonal

Estado al 2026-10-26: etapas 0–5 completadas localmente; etapa 6 pendiente.
Se implementaron controles, documentos/títulos, procesamiento durable y separación
de audio, emociones, embeddings, grafo, respaldos, identidad, recuperación, workspaces,
invitaciones, notificaciones y administración.
No se publicaron
cambios ni se desplegaron entornos. Revalidar el árbol y las pruebas al iniciar
cada etapa; la ejecución de etapas siguientes requiere su alcance autorizado.

Las reglas y estructura objetivo se mantienen en [ARCHITECTURE.md](../../ARCHITECTURE.md).
El [mapa](repository-map.md) identifica el código actual. Los contratos funcionales
del [índice](../README.md) siguen vigentes durante toda la migración.

## Resultado esperado y alcance

Distinguir físicamente núcleo, casos de uso, adaptadores y composición, y hacer
verificable la dirección de sus dependencias. Reorganizar las capacidades existentes
sin cambiar sus contratos HTTP, datos persistidos ni semántica de recuperación.

Ejes personales continúa siendo un extractor definido por el usuario. Su refactor
interno se pospone: no mover sus rutas, modelos, previews, versiones o histórico
como parte de estas etapas. Los cambios compartidos deben mantener su integración.
Una reorganización posterior de ejes requiere un alcance propio sobre esta base.

No incorporar funcionalidades de [pendientes](../pending.md), cambiar proveedores,
prompts, política de retry o formatos de artefactos para aprovechar el refactor.
No introducir una transacción distribuida entre SQL, archivos y ArcadeDB.

## Referencia arquitectónica

[ARCHITECTURE.md](../../ARCHITECTURE.md) define el interior del hexágono, puertos,
adaptadores, composición, dependencias permitidas y criterios para nuevos módulos.
Este plan mantiene sólo correspondencias, secuencia y aceptación de la migración.
Las decisiones estables se actualizan en esa referencia, sin duplicarlas aquí.

## Correspondencia del código actual

Los destinos indican responsabilidades; no son órdenes de mover archivos completos.

| Origen | Destino y separación |
| --- | --- |
| `src/domain/` | `core/domain/`; preservar modelos canónicos y serialización |
| `src/services/document_store.py`, `audio_note_store.py`, `graph_store.py` | Puertos/errores en `core` del área; implementaciones en `adapters/storage` |
| `src/services/durable_files.py`, `audio_transcoding.py` | Adaptadores filesystem/audio; política de preparación en aplicación |
| `src/extractors/base.py`, `contracts.py`, `registry.py` | Contratos/reglas en `core/extractors`; ciclo de ejecución en aplicación; registro concreto en bootstrap |
| `src/extractors/artifacts.py`, `src/processing/artifacts.py` | Puerto de artefactos en core e implementación filesystem |
| `src/extractors/emotions.py`, `document_title.py`, `document_embeddings.py` | Modelos/reglas en core; coordinación en aplicación; extraer I/O que quede mezclado |
| `src/extractors/*_store.py`, `src/graph/arcadedb/` | Adaptadores ArcadeDB por capacidad; contratos de lectura en core |
| `src/extractors/openai_*.py`, `src/services/openai_transcription_provider.py` | `adapters/providers/openai/`, implementando puertos de cada capacidad |
| `src/processing/` | Separar contratos en core, coordinación en use_cases, modelos/repositorios SQL, transporte y composición |
| `src/use_cases/*.py` | Agrupar por área; retirar SQL, construcción de stores y configuración global |
| `src/api/`, rutas/schemas de otras familias | `adapters/access/api/`; separar público y administración |
| `src/user_management/`, `src/auth/`, `src/workspaces/` | Reglas/identidad/contexto en core, acciones en use_cases, framework/ORM/cifrado/provisión remota en adaptadores |
| `src/exteriorization/`, `src/notifications/` | Reglas de invitaciones/notificaciones en core; coordinación en use_cases; SQL, email y push en adaptadores |
| `src/administration/` | Reglas/contratos en core, inventario/métricas/permisos en aplicación, SQL/filesystem/HTTP en adaptadores |
| `src/config.py`, dependencias, `src/processing/workflows.py` | Configuración de entorno y composición en bootstrap; separar políticas de configuración aceptada |
| `src/main.py`, `src/admin_main.py`, comandos de procesos | Entrypoints en bootstrap; mantener compatibilidad con comandos de Docker y scripts durante el cambio |
| `src/maintenance/`, Alembic, inicialización de esquema | Comandos en acceso CLI, coordinación en aplicación y operaciones concretas en storage; mantener revisiones aplicadas |
| `src/extractors/personal_axes/` y sus casos de uso | Sin migración interna en este plan; compatibilidad puntual documentada |

## Secuencia de entregas

Cada etapa puede dividirse en entregas por recorrido; evitar una rama con todos
los movimientos acumulados. Registrar en su entrega contratos tocados, comandos,
resultados y compatibilidad pendiente. Mantener aquí sólo estado y decisiones.

### Etapa 0 — Línea de base y control de fronteras

- [x] Inventariar imports, puntos de composición, comandos de proceso y usos de
  las rutas que se moverán: tests, Alembic, empaquetado, Docker y scripts incluidos.
- [x] Seleccionar y ejecutar la regresión base del primer recorrido, con servicios
  aislados cuando corresponda; registrar skips y limitaciones.
- [x] Incorporar un chequeo de dependencias para las rutas migradas: prohibir
  imports de infraestructura desde core/aplicación y de bootstrap desde otras capas.
  Contemplar imports relativos y locales; revisar aparte carga dinámica.
- [x] Registrar excepciones heredadas por archivo/arista y motivo, sin permitir
  un paquete entero. El chequeo debe impedir nuevas violaciones y acompañar CI.

Salida: inventario verificable y controles que pueden aplicarse gradualmente.
No crear toda la estructura vacía ni declarar limpio el código todavía heredado.

Implementación: `scripts/check_architecture.py`, política de excepciones exactas
en `config/architecture-exceptions.json` y workflow independiente de CI.
Inventario reproducible y puntos de composición/consumo en la
[guía del chequeo](architecture-checks.md). El inventario inicial comprende
186 módulos y 1.764 imports; registra 211 aristas heredadas y 159 ubicaciones
preexistentes, sin desactivar las reglas para paquetes enteros. La búsqueda de
carga dinámica en `src/` no encontró llamadas que requieran excepción.

Validación local: 45 pruebas focalizadas del recorrido, 41 integraciones verificadas
con PostgreSQL 17/ArcadeDB 26.9.1 desechables y 28 pruebas del chequeo. Una integración
opcional de worker real quedó omitida por no configurar RabbitMQ; no se acredita
ese transporte. El caso de grafo inmediato pasó tras preparar su base de prueba
`processing_test`. Los motores desechables se eliminaron al finalizar. No se
movió código funcional ni se cambiaron datos de usuarios; CI remoto no ejecutado.
Ruff aprueba `src`, tests y el chequeo nuevo. El comando global sobre todos los
scripts conserva un E501 preexistente en `scripts/ingest_alex_diary_resumable.py:24`,
verificado contra `HEAD` y fuera de este alcance.

### Etapa 1 — Recorrido piloto: documentos y títulos

Depende de etapa 0. Títulos es el primer extractor por contar ya con un puerto de
persistencia separado. Emociones y embeddings mantienen su ejecución actual.

- [x] Ubicar Document/AudioNote y puertos mínimos de documentos, proyección base
  y artefactos, con adaptadores filesystem/ArcadeDB.
- [x] Migrar lectura/ingestión básica y extracción/persistencia de títulos a las
  nuevas fronteras. Inyectar dependencias y configuración, sin leer settings globales.
- [x] Componer el recorrido desde bootstrap y conectarlo a los entrypoints vigentes.
  Un wrapper temporal puede conservar un import; no duplicar implementación.
- [x] Mantener la selección de capas y el coordinador actuales mediante compatibilidad
  hasta etapa 2. No cambiar los snapshots de jobs ya aceptados.

Salida: recorrido HTTP → aplicación → puertos → adaptadores, con pruebas de core
y aplicación sin motores/proveedores reales, más integración de persistencia real.
Validar títulos existentes, originales sin título, lectura con generación diferida,
retry sin repetir proveedor y aislamiento de usuario.

Pruebas de referencia: `test_ingest_document.py`, `test_documents_route.py`,
`test_document_title_extractor.py`, `test_lazy_document_titles.py` y las integraciones
`test_deferred_ingestion.py`, `test_document_title_processing.py`,
`test_document_titles_on_read.py`. Reevaluar selección al fijar cada entrega.

Implementación canónica y compatibilidad:

| Responsabilidad | Ubicación vigente |
| --- | --- |
| Originales Document/AudioNote | `src/core/domain/` |
| DocumentStore, proyección base y política/puerto de programación de títulos | `src/core/documents/` |
| Contratos de extracción, títulos y artefactos | `src/core/extractors/` |
| Ingestión de texto/archivo, listado y programación acotada al leer | `src/use_cases/documents/` |
| Ciclo común y extracción/persistencia de títulos | `src/use_cases/extraction/` |
| JSON, publicación durable y artefactos inmutables | `src/adapters/storage/filesystem/` |
| Proyección base y actualización del título | `src/adapters/storage/arcadedb/` |
| Proveedor de títulos y ciclo de vida de clientes OpenAI | `src/adapters/providers/openai/` |
| Configuración inyectada y conexión al runtime vigente | `src/bootstrap/documents.py` |

Los imports anteriores reexportan la misma implementación/modelos/errores o adaptan
argumentos en un constructor de compatibilidad. El store de grafo heredado delega
la escritura base al adaptador nuevo; sus lecturas/borrado siguen para la etapa 3.
Audio sólo mueve su modelo, no su procesamiento ni almacenamiento.

Transición resuelta en etapa 2: `TitleScheduling` conserva el mismo comportamiento
de backfill, ahora mediante un caso canónico sin SQL y un puerto transaccional.
Locks/recibo/job/outbox siguen juntos en PostgreSQL; se retiraron sus cinco
excepciones de infraestructura. Los constructores anteriores siguen como puentes
de import hasta migrar consumidores. El cierre del piloto registró 223 módulos,
1.834 imports y 203 aristas heredadas; el estado actual está en la etapa siguiente.

Validación: 343 pruebas sin integraciones aprobadas; seis omitidas de Web Push por
`pywebpush` ausente. 83 integraciones aprobadas con PostgreSQL 17/ArcadeDB 26.9.1
desechables: aceptación/replay, títulos, programación concurrente al leer, backfill,
jobs, emociones, embeddings y compatibilidad de ejes. Se corrigió la configuración
de la ejecución de embeddings y sus tres casos inicialmente omitidos pasaron.
Permanece omitido un caso de worker RabbitMQ real. Las nuevas pruebas de aplicación
usan sólo puertos en memoria; las del proveedor verifican configuración explícita,
propiedad/cierre de clientes y errores recuperables con SDK simulado. Sin LLM real,
evaluación editorial, publicación ni despliegue. Servicios desechables eliminados
al finalizar; no se requieren migraciones de esquema nuevas.

### Etapa 2 — Procesamiento durable y aceptación transaccional

Depende de etapa 1. Es la etapa de mayor sensibilidad por concurrencia y recuperación.

- [x] Separar registros de aplicación de modelos ORM; extraer puertos para estado,
  transacciones, recursos, leases, checkpoints y outbox sin exponer sesiones.
- [x] Migrar aceptación/retry/reprocess y coordinación padre/hijos. Desacoplar el
  runner de repositorios concretos y errores SQL; conservar clasificación de fallos.
- [x] Separar recepción Taskiq, publicación RabbitMQ, dispatcher y composición.
- [x] Registrar workflows/extractores y construir especificaciones desde bootstrap
  o políticas explícitas; preservar la configuración fijada al aceptar cada trabajo.
- [x] Encapsular las extensiones de ejes que hoy aparecen en el procesador común.
  Conservar su orden de escritura y privacidad; no refactorizar sus internals.

Salida: misma semántica de ACK, fencing, locks, retries y workflow histórico;
la aplicación no importa SQLAlchemy/Taskiq ni construye almacenamiento de artefactos.
Probar duplicado, respuesta perdida, rollback, lease vencido, cancelación,
publicación ambigua y fallo parcial con motores aislados.

Pruebas: transporte/artefactos y las integraciones `test_processing_postgres.py`,
`test_processing_events.py`, `test_extractor_jobs.py`, `test_reprocess_notes.py`.
Ejecutar regresión de ejes afectada por los contratos compartidos.

Implementación:

| Responsabilidad | Ubicación vigente |
| --- | --- |
| Estado desacoplado, errores seguros, especificación de workflows y puertos | `src/core/processing/` |
| Ejecución/heartbeat, aceptación, retry, reprocess, coordinación y publicación de outbox | `src/use_cases/processing/` |
| Backfill sin SQL, conectado a transacciones de procesamiento | `src/use_cases/documents/backfill_document_titles.py` |
| ORM, consultas, locks, leases, feed, recibos y adaptación de estados/transacciones | `src/adapters/storage/postgres/` |
| Recepción/ACK de Taskiq | `src/adapters/access/workers/processing.py` |
| Configuración técnica del broker durable | `src/adapters/messaging/rabbitmq/broker.py` |
| Factories, registro y snapshots de configuración, ciclo de procesos y compatibilidad | `src/bootstrap/{processing,acceptance,processing_configuration,workflows,worker,messaging,dispatcher}.py` |

Los estados entregados a la aplicación son copias independientes. Avanzar un
checkpoint no puede sobrescribir la configuración aceptada por mutar una copia.
El adaptador mantiene la identidad ORM internamente, aplica las mutaciones del
caso y confirma recibo/trabajos/eventos/outbox juntos; no expone una sesión SQL.
Eventos y envíos sincronizan sólo el trabajo afectado, sin volver a copiar el
lote completo por cada elemento. La lectura de un replay conserva sus lecturas
sin locks adicionales de filas; los locks de recursos y de mutaciones no cambian.

`StorageUnavailable` conserva los fallos SQL sin resolver el lease ni confirmar
el mensaje. La API lo traduce al mismo HTTP 503 y pide reutilizar la clave
idempotente. Los workflows históricos de documento v2/v3 y los coordinadores
v4/v5 conservan transiciones, IDs determinísticos y especificaciones aceptadas.
La clasificación de proveedores vigente se inyecta desde composición hasta migrar
sus adaptadores en etapa 3. No se agregaron retries al broker ni un segundo registro.

Compatibilidad acotada: los nombres anteriores importan o construyen componentes
canónicos. Ejes mantiene en bootstrap los hooks de orden de escritura/privacidad,
el contexto de sus workflows experimentales y una fachada para su llamada existente
`reset(session, row, now)`. Esa fachada traduce al puerto transaccional y usa la
transacción del histórico; no modifica sus internals ni abre otro commit.
Seis aristas exactas del adaptador PostgreSQL siguen apuntando a Base/workspace e
invitaciones heredados, hasta etapas 4/5. Los casos canónicos y core no tienen
excepciones; los shims tienen retiro indicado en la política. El workflow específico
de audio conserva diez imports heredados hasta la etapa 3, junto con preparación,
transcripción y artefactos; su handoff ya usa el motor/puerto durable migrado.
Inventario al cerrar etapa 2:
268 módulos, 1.989 imports y 162 aristas heredadas.

Validación: 351 pruebas sin servicios aprobadas; seis pruebas de Web Push omitidas
por `pywebpush` ausente. 133 integraciones aprobadas con PostgreSQL 17, ArcadeDB
26.9.1 y RabbitMQ 4.3.6 desechables, sin skips en esa selección. Incluyen workers
Taskiq reales, escalado, ACK, cancelación, entrega perdida/duplicada, leases/fencing,
publicación ambigua, rollback, feed, aceptación/replay/reprocess, títulos y ejes.
La aplicación se prueba con puertos en memoria y con imports de SQLAlchemy, Taskiq,
FastAPI, OpenAI y HTTPX bloqueados. Alembic confirmó `No new upgrade operations
detected`; no hay revisiones de esquema nuevas. Tras el ajuste final de sincronización,
40 casos focalizados de aplicación/lotes/jobs/backfill/histórico volvieron a pasar.
Ruff, fronteras y enlaces pasan.
Sin proveedores reales, publicación ni despliegue; servicios desechables eliminados
al finalizar. El commit `452f005` conserva etapas 0/1; `2515bb6` conserva etapa 2
en la misma rama, sin push.

### Etapa 3 — Audio, demás extractores, grafo y respaldos

Depende de etapa 2; dividir por capacidad.

- [x] Extraer esquema, queries y transacciones de emociones a su adaptador ArcadeDB.
- [x] Ubicar contratos/reglas de embeddings y proveedores en sus capas definitivas.
- [x] Migrar transcripción y preparación de audio por puertos; cerrar clientes y
  temporales en adaptadores conservando artefactos y originales.
- [x] Migrar navegación/proyecciones, borrado y exportación/importación de archivos.
  No alterar evidencia, IDs, paginación, truncamiento o formato de respaldos.

Salida: ningún extractor migrado ejecuta consultas del motor ni construye archivos;
cada adaptador conserva reemplazo atómico sólo de su capa. Audio deriva documento
sin retranscribir al recuperar fallos posteriores.

Pruebas: suites de emociones, embeddings, transcripción, archivo y navegación;
integraciones de capas, `test_emotion_processing.py`,
`test_document_embedding_processing.py` y `test_audio_invitation_processing.py`.

Implementación canónica:

| Responsabilidad | Ubicación vigente |
| --- | --- |
| Puertos de audio y preparación/transcripción | `src/core/audio/` |
| Evidencia, perfiles, configuración y reglas de emociones/embeddings | `src/core/extractors/` |
| Contratos de navegación y respaldo | `src/core/graph/`, `src/core/documents/archive.py` |
| Audio, extracción, navegación, borrado y respaldo por puertos | `src/use_cases/{audio,extraction,graph,documents}/` |
| Esquema, consultas, navegación y proyecciones atómicas | `src/adapters/storage/arcadedb/` |
| Originales de audio, preparación ffmpeg y temporales | `src/adapters/storage/filesystem/{audio_notes,audio_transcoding}.py` |
| Clientes OpenAI y conteo tiktoken | `src/adapters/providers/openai/` |
| Normalización técnica y política de fallos | `src/adapters/providers/http/failures.py`, `src/core/processing/failures.py` |
| Composición y registro concreto | `src/bootstrap/{audio,extraction,extractor_registry,graph,graph_schema,archives,failures}.py` |

Las reglas de evidencia y perfiles permanecen iguales. La persistencia de emociones
posee su transacción de reemplazo/verificación; el algoritmo sólo llama a su puerto.
Embeddings recibe el contador de tokens, sin cargar tiktoken en aplicación. Audio
recibe una fuente preparable y un puerto de artefactos: no usa paths, ffmpeg,
SDK ni configuración global. Los adaptadores conservan original, cierre de clientes
y limpieza por fallo/cancelación; recuperar escritura no vuelve a transcribir.

Los hashes de procesamiento mantienen su serialización histórica, distinta del
digest compacto de extracción. Los respaldos preservan formato v1, IDs, fechas,
títulos canónicos y el snapshot de aceptación anterior, sin resolver configuración
adicional de ejes. Los errores SQL se convierten en `StorageUnavailable`, que la
ruta traduce al mismo 503. Navegación verifica el original antes de leer su grafo;
conserva evidencia, límites, truncamiento y precedencia del título canónico.

Los nombres anteriores delegan en la implementación canónica o adaptan constructores
en bootstrap. Los consumidores HTTP/workspace/CLI pendientes conservan puentes
exactos hasta su migración y consolidación; no hay excepciones de core ni aplicación
canónicos. Ejes conserva internals y sus hooks previos. El inventario registra
309 módulos, 2.141 imports y 153 aristas heredadas exactas; no se agregan
frameworks, proveedores ni revisiones de esquema.

Validación: 354 pruebas sin servicios aprobadas; seis de Web Push omitidas por
`pywebpush` ausente. Los nuevos casos con puertos en memoria recuperan emociones,
embeddings y audio sin repetir proveedor; el control de imports también bloquea
tiktoken. 156 integraciones aprobadas, sin skips en esa selección, con PostgreSQL 17,
ArcadeDB 26.9.1 y RabbitMQ desechables: capas, navegación, audio/invitación,
aceptación/replay de respaldos, títulos, jobs, reprocess, feed, backfill y ejes,
incluidos workers reales. Alembic confirmó `No new upgrade operations detected`.
La fixture histórica de exploración fallaba también contra el commit `2515bb6`:
esperaba dos ejecuciones aunque la extracción reemplaza la anterior. Ahora inserta
el escenario histórico explícitamente y conserva la prueba de deduplicación y
proveniencia, sin modificar el reemplazo de producción. Ruff, fronteras y enlaces
pasan. Los servicios desechables se eliminaron al finalizar. El commit `01339cd`
conserva etapa 3 en la misma rama; no hay publicación ni despliegue.

### Etapa 4 — Identidad, recuperación y workspaces

Depende de la base de transacciones de etapa 2. Puede avanzar después por separado
de etapa 3; el piloto usa la composición de workspace existente como puente.

- [x] Definir identidad/contexto y políticas sin FastAPI Users ni modelos ORM.
- [x] Separar login, recuperación y revocación de SQL, hashing, cifrado y correo.
- [x] Mantener provisión, reconciliación y acceso por workspace mediante puertos.
  No ampliar acceso root ni introducir stores globales para simplificar inyección.
- [x] Conservar protección de origen, cookies, sesiones, límites de recuperación,
  suspensión y efectos transaccionales sobre invitaciones/jobs.

Salida: mismas garantías de cuenta/propietario y recuperación, con pruebas de
aplicación sin frameworks HTTP/ORM. Integraciones de alta, recuperación PostgreSQL,
OAuth y aislamiento de workspaces según las fronteras modificadas.

Implementación canónica:

| Responsabilidad | Ubicación vigente |
| --- | --- |
| Identidad verificada, contraseña, versión de sesión y estados/puertos de recuperación | `src/core/auth/` |
| Estado, contexto, credenciales técnicas protegidas y puertos de workspace | `src/core/workspaces/` |
| Autenticar, solicitar/consumir código y coordinar entrega durable | `src/use_cases/auth/` |
| Resolver dueño, consultar/preparar, provisionar y reconciliar | `src/use_cases/workspaces/` |
| Cookies, registro/OAuth, errores HTTP/IP confiable y rutas de setup | `src/adapters/access/api/public/{auth,workspaces}/` |
| Metadatos ORM compartidos, cuentas, asignación, snapshots y transacciones | `src/adapters/storage/postgres/{base,accounts,authentication,workspace_models,workspace_repository,workspaces,recovery_models,recovery_repository,recovery_transaction,snapshots}.py` |
| Cifrado/HMAC y entrega de correo | `src/adapters/providers/{security,email}/` |
| Operaciones root de provisión y permisos restringidos | `src/adapters/storage/arcadedb/{administration,provisioning}.py` |
| Configuración, dependencias, registro de routers y ciclo de vida | `src/bootstrap/{auth,database,oauth,recovery,workspaces}.py` |

Se eliminaron `src/user_management/`, `src/workspaces/` y `src/auth/`, los casos
sueltos anteriores de recuperación y los métodos de transición duplicados del
repositorio. Sus consumidores, scripts, tests y registro de modelos Alembic
importan las ubicaciones canónicas; no quedaron shims en esas carpetas. Los ejes
conservan sus internals: sólo se actualizaron imports de identidad/SQL/composición.
Los wrappers anteriores de otras etapas se retiran cuando migra su último consumidor.

La aplicación recibe copias desacopladas y operaciones semánticas. Un solo commit
conserva presupuestos/desafío/cambio de contraseña/versión/revocación/push y outbox.
Se mantiene el lock de usuario compartido entre login, upgrade de hash y reset,
además del orden dirección/entrega/preferencias para no cambiar la concurrencia.
Core no importa HTTP, SQLAlchemy, FastAPI Users ni cryptography; los códigos y
esperas se traducen a HTTP en acceso. La entrega usa el mismo workflow sin workspace.

Provisión conserva estado/asignación/secretos y no reactiva suspendidos. El puerto
remoto prepara esquema/grupo/principal; resolver un runtime usa el dueño verificado
y credenciales restringidas. API y worker comparten la resolución: errores públicos
seguros y fallo de cifrado recuperable como antes. No se cambian claves, esquemas,
prompts, cookies, exposición de rutas ni revisiones aplicadas.

Excepciones exactas: tres imports SQL de invitaciones/push en el adaptador de
recuperación, con retiro en etapa 5, y consumidores de composición HTTP/CLI todavía
heredados hasta sus etapas. Inventario: 327 módulos, 2.167 imports, 158 aristas
heredadas y 131 ubicaciones anteriores. El aumento de aristas refleja imports de
composición ahora explícitos al retirar módulos viejos; no habilita nuevas
dependencias de infraestructura en core/aplicación canónicos.

Validación: 361 pruebas locales aprobadas, seis Web Push omitidas por `pywebpush`
ausente. 152 integraciones distintas aprobadas: 17 de recuperación/migración,
133 de regresión durable y dos nuevas de provisión real. Usan PostgreSQL 17,
ArcadeDB 26.9.1 y RabbitMQ desechables, proveedores determinísticos y workers reales.
Las nuevas pruebas comprueban principales limitados por cuenta, originales aislados,
provisión concurrente y suspensión. La fixture remota usa sólo configuración explícita,
sin cargar `.env`. Tras ubicar acceso bajo `api/public`, 42 casos focalizados
aprobaron; los dos casos de límite IP volvieron a confirmar HTTP 429 y `Retry-After`.
Alembic confirmó `No new upgrade operations detected`. Ruff, fronteras y documentación
pasan; no se acredita Google OAuth remoto ni entrega real de correo/push.
Los servicios desechables se eliminaron al finalizar. Etapa 4 quedó en `447a072`,
sin publicación ni despliegue. La etapa 5 preserva la revocación compartida y los
puentes de ejes.

### Etapa 5 — Invitaciones, notificaciones y administración

Depende de etapas 2 y 4. Dividir por recorrido, conservando atomicidad entre capacidades.

- [x] Separar programación/selección de invitaciones, consentimiento, vigencia y
  lectura de notificaciones de consultas y transporte push.
- [x] Migrar inventario administrativo, actividad, métricas y permisos a sus capas.
- [x] Ubicar rutas públicas/admin, schemas, CLI y procesos de sincronización en
  adaptadores de acceso; mantener aplicaciones y exposición independientes.
- [x] Ubicar bootstrap específico de cada proceso, preservando configuración
  compartida donde intervienen API, workers, dispatcher y admin-api.

Salida: sin SQL de negocio en rutas/casos de uso, sin contenido privado en métricas
o notificaciones y sin registro administrativo en la API pública. Probar horarios,
revocación, cambio de cuenta, idempotencia, inventario incompleto y permisos.

Pruebas: suites de exteriorización/notificaciones/admin y sus integraciones SQL;
Google, email y push reales siguen siendo validaciones externas independientes.

Implementación: reglas y puertos en `core/{exteriorization,notifications,administration}`,
coordinación en los casos agrupados, transacciones/consultas en PostgreSQL,
metadatos en filesystem, Web Push como proveedor y rutas/CLIs como acceso.
Bootstrap compone los servicios y cada proceso. Se eliminaron las tres carpetas
anteriores y los casos sueltos de invitaciones; `src.admin_main:app` conserva sólo
el entrypoint externo del proceso administrativo independiente.

Validación local: 373 pruebas sin integraciones y 187 integraciones distintas
aprobadas, sin skips en esos conjuntos. PostgreSQL, ArcadeDB y RabbitMQ desechables
cubrieron canales, revocación, recuperación, inventario, permisos y regresión durable
con workers reales y proveedores simulados. Alembic no detectó cambios de esquema.
El wheel construido desde fuentes limpias incluye el catálogo movido y excluye las
carpetas retiradas. Ruff, documentación y fronteras aprobados. No se acredita envío
externo, build de imagen, publicación ni despliegue. Inventario actual: 364 módulos,
2.264 imports, 101 ubicaciones heredadas y 104 aristas exactas exceptuadas; son
contadores de transición, no porcentajes de avance.

### Etapa 6 — Consolidación del alcance migrado

Depende del cierre de etapas anteriores.

Análisis del árbol al cerrar etapa 5: las capacidades principales ya tienen núcleo
y aplicación separados. Aún hay trabajo funcional de frontera en HTTP/SSE y
mantenimiento, además de retirar compatibilidad. No basta con renombrar carpetas.

Orden propuesto para las entregas pendientes:

| Entrega | Evidencia actual | Trabajo y salida verificable |
| --- | --- | --- |
| 6.1 Acceso público | `src/api/routes/events.py` consulta cuentas/sesiones/workspaces con SQL; `document_archive.py` resuelve repositorio, settings y paths; `processing.py` construye fachadas antiguas | Separar autorización renovable del stream, resolución de respaldos y construcción de casos mediante puertos y bootstrap. Mover rutas/schemas/middleware a acceso público; preservar SSE, cookies, ownership y errores |
| 6.2 Arranque y configuración | `src/main.py`, `src/dependencies.py` y `src/config.py` conservan composición/configuración fuera de bootstrap | Componer API y dependencias en bootstrap; llevar settings a esa capa sin cambiar alias/defaults ni valores aceptados. Ubicar logging/observabilidad según su responsabilidad y mantener el arranque administrativo independiente |
| 6.3 Mantenimiento | `src/maintenance/data_migrations.py` mezcla CLI, SQL, archivos y clientes; `cleanup_extractions.py` accede a sesiones y `_client`; `models.py` aún está allí | Separar CLI, coordinación por puertos y adaptadores concretos. Preservar inventario previo, backups, locks, fingerprints, reanudación e IDs de migración. No ejecutar contra entornos con datos |
| 6.4 Retiro de compatibilidad | `src/domain/`, `src/services/`, `src/graph/`, `src/processing/`, extractores migrados y casos sueltos reexportan o construyen implementaciones canónicas | Migrar últimos consumidores, incluidos tests/scripts/comandos, y eliminar cada wrapper innecesario. Corregir etapas de retiro vencidas en la política; conservar sólo entrypoints requeridos y puentes documentados de ejes |
| 6.5 Verificación de procesos | Dockerfiles/Compose todavía usan `src.main`, `src.processing.*`, `src.graph.arcadedb.schema` y `src.maintenance.data_migrations`; Alembic importa modelos heredados | Actualizar consumidores o justificar compatibilidad. Ejecutar regresión, wheel e imagen desde fuentes limpias, e inicio/cierre aislado de API pública/admin, worker y dispatcher |

Las 104 aristas exceptuadas no representan 104 responsabilidades por migrar:
incluyen wrappers y dependencias internas de ejes pospuesto. Revisarlas por
consumidor y condición de retiro; no buscar cero excepciones eliminando el alcance
excluido ni ampliando el baseline. Los casos canónicos migrados no tienen excepciones.

El refactor interno de `src/extractors/personal_axes/` y sus casos experimentales
queda fuera de etapa 6. Sus puentes compartidos deben seguir funcionando y quedar
identificados para un plan posterior.

- [ ] Migrar comandos de mantenimiento, arranque y settings restantes; actualizar
  Dockerfiles, Compose, scripts, Alembic y package-data cuando cambien imports/rutas.
  No reescribir revisiones aplicadas; preservar módulos de compatibilidad si las usan.
- [ ] Actualizar mapa, guías de área y documentación operativa. Retirar wrappers y
  excepciones ya innecesarios, verificando importadores y procesos consumidores.
- [ ] Conservar sólo los puentes estrictamente necesarios para ejes pospuesto,
  con ubicación, motivo, consumidor y condición de retiro explícitos.
- [ ] Completar regresión del alcance, chequeos arquitectónicos, build de imagen
  e inicio aislado de API pública/admin, worker y dispatcher.

Salida: estructura efectiva del backend migrado coincide con el objetivo; excepciones
residuales de ejes están identificadas. No declarar el repositorio entero migrado
ni desplegado mientras ese trabajo o una validación requerida sigan pendientes.

## Criterios comunes de aceptación y recuperación

1. Misma API, cookies, errores seguros, identidad y ownership. Misma configuración
   serializada, formatos de originales/artefactos y nombres/versiones de workflows.
2. Las pruebas de aplicación usan puertos falsos; SQL/grafo/filesystem/proveedores
   se comprueban en tests de adaptadores. No perder cobertura de transacciones reales.
3. Ninguna sesión SQL, cliente o excepción tecnológica cruza el puerto de aplicación.
4. Atomicidad recibo/job/evento/outbox y orden de persistencia del original intactos;
   replay y recovery no repiten proveedor ni capas completadas.
5. Checks de imports, Ruff, documentación y pruebas pertinentes pasan. Un skip
   requerido deja la entrega pendiente de esa validación, no acreditada por mocks.
6. Las entregas no necesitan transformar datos por un movimiento de paquetes.
   Si aparece esa necesidad, separar el cambio y revisar compatibilidad antes de seguir.
7. Revertir una entrega debe permitir volver a los imports/entrypoints anteriores
   sobre los mismos datos y jobs. Antes de publicar, comprobar referencias de clases
   o módulos serializadas y recursos empaquetados; no asumir que un rename es inocuo.

Al concluir el plan, verificar las decisiones estables en [ARCHITECTURE.md](../../ARCHITECTURE.md)
y retirar este plan cuando deje de tener trabajo pendiente. No conservarlo
como historia de implementación.
