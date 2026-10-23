# Plan de migración a arquitectura hexagonal

Estado: arquitectura y organización acordadas el 2026-10-23; migración funcional
no iniciada. Este documento planifica el trabajo; no autoriza su ejecución,
publicación ni despliegue. Revalidar el árbol y las pruebas al iniciar cada etapa.

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

- [ ] Inventariar imports, puntos de composición, comandos de proceso y usos de
  las rutas que se moverán: tests, Alembic, empaquetado, Docker y scripts incluidos.
- [ ] Seleccionar y ejecutar la regresión base del primer recorrido, con servicios
  aislados cuando corresponda; registrar skips y limitaciones.
- [ ] Incorporar un chequeo de dependencias para las rutas migradas: prohibir
  imports de infraestructura desde core/aplicación y de bootstrap desde otras capas.
  Contemplar imports relativos y locales; revisar aparte carga dinámica.
- [ ] Registrar excepciones heredadas por archivo/arista y motivo, sin permitir
  un paquete entero. El chequeo debe impedir nuevas violaciones y acompañar CI.

Salida: inventario verificable y controles que pueden aplicarse gradualmente.
No crear toda la estructura vacía ni declarar limpio el código todavía heredado.

### Etapa 1 — Recorrido piloto: documentos y títulos

Depende de etapa 0. Títulos es el primer extractor por contar ya con un puerto de
persistencia separado. Emociones y embeddings mantienen su ejecución actual.

- [ ] Ubicar Document/AudioNote y puertos mínimos de documentos, proyección base
  y artefactos, con adaptadores filesystem/ArcadeDB.
- [ ] Migrar lectura/ingestión básica y extracción/persistencia de títulos a las
  nuevas fronteras. Inyectar dependencias y configuración, sin leer settings globales.
- [ ] Componer el recorrido desde bootstrap y conectarlo a los entrypoints vigentes.
  Un wrapper temporal puede conservar un import; no duplicar implementación.
- [ ] Mantener la selección de capas y el coordinador actuales mediante compatibilidad
  hasta etapa 2. No cambiar los snapshots de jobs ya aceptados.

Salida: recorrido HTTP → aplicación → puertos → adaptadores, con pruebas de core
y aplicación sin motores/proveedores reales, más integración de persistencia real.
Validar títulos existentes, originales sin título, lectura con generación diferida,
retry sin repetir proveedor y aislamiento de usuario.

Pruebas de referencia: `test_ingest_document.py`, `test_documents_route.py`,
`test_document_title_extractor.py`, `test_lazy_document_titles.py` y las integraciones
`test_deferred_ingestion.py`, `test_document_title_processing.py`,
`test_document_titles_on_read.py`. Reevaluar selección al fijar cada entrega.

### Etapa 2 — Procesamiento durable y aceptación transaccional

Depende de etapa 1. Es la etapa de mayor sensibilidad por concurrencia y recuperación.

- [ ] Separar registros de aplicación de modelos ORM; extraer puertos para estado,
  transacciones, recursos, leases, checkpoints y outbox sin exponer sesiones.
- [ ] Migrar aceptación/retry/reprocess y coordinación padre/hijos. Desacoplar el
  runner de repositorios concretos y errores SQL; conservar clasificación de fallos.
- [ ] Separar recepción Taskiq, publicación RabbitMQ, dispatcher y composición.
- [ ] Registrar workflows/extractores y construir especificaciones desde bootstrap
  o políticas explícitas; preservar la configuración fijada al aceptar cada trabajo.
- [ ] Encapsular las extensiones de ejes que hoy aparecen en el procesador común.
  Conservar su orden de escritura y privacidad; no refactorizar sus internals.

Salida: misma semántica de ACK, fencing, locks, retries y workflow histórico;
la aplicación no importa SQLAlchemy/Taskiq ni construye almacenamiento de artefactos.
Probar duplicado, respuesta perdida, rollback, lease vencido, cancelación,
publicación ambigua y fallo parcial con motores aislados.

Pruebas: transporte/artefactos y las integraciones `test_processing_postgres.py`,
`test_processing_events.py`, `test_extractor_jobs.py`, `test_reprocess_notes.py`.
Ejecutar regresión de ejes afectada por los contratos compartidos.

### Etapa 3 — Audio, demás extractores, grafo y respaldos

Depende de etapa 2; dividir por capacidad.

- [ ] Extraer esquema, queries y transacciones de emociones a su adaptador ArcadeDB.
- [ ] Ubicar contratos/reglas de embeddings y proveedores en sus capas definitivas.
- [ ] Migrar transcripción y preparación de audio por puertos; cerrar clientes y
  temporales en adaptadores conservando artefactos y originales.
- [ ] Migrar navegación/proyecciones, borrado y exportación/importación de archivos.
  No alterar evidencia, IDs, paginación, truncamiento o formato de respaldos.

Salida: ningún extractor migrado ejecuta consultas del motor ni construye archivos;
cada adaptador conserva reemplazo atómico sólo de su capa. Audio deriva documento
sin retranscribir al recuperar fallos posteriores.

Pruebas: suites de emociones, embeddings, transcripción, archivo y navegación;
integraciones de capas, `test_emotion_processing.py`,
`test_document_embedding_processing.py` y `test_audio_invitation_processing.py`.

### Etapa 4 — Identidad, recuperación y workspaces

Depende de la base de transacciones de etapa 2. Puede avanzar después por separado
de etapa 3; el piloto usa la composición de workspace existente como puente.

- [ ] Definir identidad/contexto y políticas sin FastAPI Users ni modelos ORM.
- [ ] Separar login, recuperación y revocación de SQL, hashing, cifrado y correo.
- [ ] Mantener provisión, reconciliación y acceso por workspace mediante puertos.
  No ampliar acceso root ni introducir stores globales para simplificar inyección.
- [ ] Conservar protección de origen, cookies, sesiones, límites de recuperación,
  suspensión y efectos transaccionales sobre invitaciones/jobs.

Salida: mismas garantías de cuenta/propietario y recuperación, con pruebas de
aplicación sin frameworks HTTP/ORM. Integraciones de alta, recuperación PostgreSQL,
OAuth y aislamiento de workspaces según las fronteras modificadas.

### Etapa 5 — Invitaciones, notificaciones y administración

Depende de etapas 2 y 4. Dividir por recorrido, conservando atomicidad entre capacidades.

- [ ] Separar programación/selección de invitaciones, consentimiento, vigencia y
  lectura de notificaciones de consultas y transporte push.
- [ ] Migrar inventario administrativo, actividad, métricas y permisos a sus capas.
- [ ] Ubicar rutas públicas/admin, schemas, CLI y procesos de sincronización en
  adaptadores de acceso; mantener aplicaciones y exposición independientes.
- [ ] Ubicar bootstrap específico de cada proceso, preservando configuración
  compartida donde intervienen API, workers, dispatcher y admin-api.

Salida: sin SQL de negocio en rutas/casos de uso, sin contenido privado en métricas
o notificaciones y sin registro administrativo en la API pública. Probar horarios,
revocación, cambio de cuenta, idempotencia, inventario incompleto y permisos.

Pruebas: suites de exteriorización/notificaciones/admin y sus integraciones SQL;
Google, email y push reales siguen siendo validaciones externas independientes.

### Etapa 6 — Consolidación del alcance migrado

Depende del cierre de etapas anteriores.

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
