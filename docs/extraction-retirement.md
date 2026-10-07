# Retiro de la extracción exploratoria

Fecha: 2026-10-06. Etapa 1 de [extracción por capas](extraction-layers-requirements-plan.md).
Implementación y pruebas locales preparadas; el corte sobre bases de usuario
queda para el despliegue, según lo acordado. No se ejecutó limpieza de datos de
usuario ni se desplegaron imágenes.

## Comportamiento de la etapa de retiro

La ingestión durable `/v2` conserva originales e idempotencia. El workflow de
documento versión 2 ejecuta `document_persistence → done`, sin LLM de extracción
ni embeddings. ArcadeDB guarda identidad, contenido completo, título existente,
fuente, metadatos y fechas del documento y verifica la escritura en transacción.

Audio conserva transcripción, artefactos recuperables, creación del documento
con el UUID del audio y coordinación con su procesamiento hijo. Sólo transcribir
requiere el proveedor OpenAI; guardar documentos no depende de `OPENAI_MODEL`.
El audio versión 1 puede completar este flujo y crear un hijo de documento v2.

La inicialización de workspaces nuevos crea únicamente el tipo de vértice
`Document`, sus propiedades y su índice de identidad. `SchemaMigration` permanece
como registro administrativo. Las bases existentes reciben la propiedad de
contenido cuando se aplica el esquema nuevo; no se borra nada al inicializarlo.

Se eliminaron las operaciones HTTP de extracción, búsqueda semántica,
reflexión y análisis de Constelación. Sus URLs históricas devuelven `410` autenticado y no
construyen proveedores ni dependencias de workspace. También se retiran las
mutaciones antiguas síncronas/background: los uploads y la recuperación usan
`/v2` con `Idempotency-Key`. Los GET históricos de originales y el DELETE de
documento siguen disponibles.

`POST /v2/documents/{id}/processing` solicita una nueva persistencia del original
sin reupload, extracción ni cambio de título. Reemplaza la solicitud de
reextracción en la PWA y en `scripts/reprocess_document.py`.

La PWA ofrece captura, listado, lectura, borrado y recuperación de notas/audio.
Se retiró Exploración y se conservó el visor del grafo, accesible desde captura.
`GET /documents/{id}/links` conserva su contrato de respuesta, filtros y paginación;
no ejecuta análisis ni persistencia de relaciones. Un grafo sin relaciones devuelve
un vecindario vacío. Conserva Blob y transcripción locales. La recuperación de trabajos de documento v1 convierte explícitamente
el retry a documento v2, descartando checkpoints de extracción. También admite
recuperar el padre de audio cuyo hijo v1 fue retirado, sin retranscribir.

Los mensajes de documento v1 terminan como `extraction_retired`; no pueden volver
a generar resultados exploratorios con los workers nuevos. Esto no detiene un
worker ejecutando el código viejo: el corte exige retirar esas instancias.

Los módulos históricos `extraction`, `embeddings`, `reflection` y `constellation`,
sus adaptadores, casos de uso y scripts de experimentos se eliminaron del runtime.
El contrato de presentación del visor queda en `src/graph/contracts.py`, separado
de cualquier extractor. Los campos de respuesta `source_claim_id` y
`target_claim_id` se conservan por compatibilidad del cliente; no requieren tipos
`Claim` en la base. El análisis futuro de Constelación deberá implementarse nuevamente.

El extractor de emociones permanece en `src/extractors`, con modelos y persistencia
propios.
Las notas nuevas usan ahora el workflow v3 con extracción de emociones automática;
los trabajos históricos v2 y los convertidos por la migración mantienen el flujo
de persistencia del original. Ver [procesamiento de emociones](emotion-extractor.md).
La migración conserva su inventario histórico; los esquemas antiguos necesarios
para probarla se encuentran únicamente en fixtures de integración.

## Migración masiva al desplegar

`src.maintenance.data_migrations` ejecuta la migración
`20261006-retire-exploratory-extraction`. Descubre todos los workspaces registrados
en PostgreSQL para `ARCADEDB_INSTANCE_KEY`; no requiere conocer UUIDs ni ejecutar
comandos por usuario. Incluye activos, suspendidos y registros pendientes. Usa
las credenciales administrativas de ArcadeDB y conserva el estado de cada workspace.
Los directorios globales legacy fuera de esos workspaces quedan fuera del alcance.

La revisión Alembic `20261006_06` crea `data_migrations`. Allí se registra el avance
por instancia y workspace, y una marca global sólo después de completar todos.
Un bloqueo PostgreSQL impide dos migradores simultáneos. Una ejecución posterior
omite el trabajo completado; una ejecución interrumpida retoma los pendientes.
Este registro controla migraciones de datos, sin gestionar versiones de extractores.

Por cada workspace, la migración:

1. Inventaría derivados, originales, tipos del grafo e historial de procesamiento.
   Rechaza originales ausentes, symlinks e inventarios truncados o inconsistentes.
   Una base ausente sólo se admite para registros aún sin provisionar y sin datos.
2. Prepara un respaldo lógico verificado por hash, con permisos restringidos,
   en `/data/migration-backups/20261006-retire-exploratory-extraction/…`.
   Publica el respaldo completo antes de borrar datos; conserva fuentes, derivados,
   registros del grafo e historial SQL. No sustituye los backups completos de motores.
3. Elimina registros exploratorios y vectores, incluidos vectores de documentos
   y subtipos históricos. Conserva los vértices Document y verifica la transacción.
4. Elimina archivos de extracciones/reflexiones y checkpoints de extracción.
   Conserva originales, audio, transcripciones y archivos desconocidos.
5. Invalida leases y generaciones anteriores. Los documentos pendientes o fallidos
   de workflow v1 pasan a v2, en `document_persistence`; conserva el historial y
   permite continuar audios cuyo hijo falló, sin perder su transcripción.
6. Persiste todos los documentos originales y su texto completo, sin llamar modelos.
   Verifica fuentes intactas y ausencia de derivados antes de marcar el workspace.

Los tipos e índices históricos quedan definidos pero vacíos. Los conteos de tipos
padre incluyen subtipos y no deben sumarse como conjuntos disjuntos.
No hay una transacción conjunta entre filesystem, ArcadeDB y PostgreSQL: el
respaldo publicado y los checkpoints permiten retomar después de un commit del
grafo, un borrado parcial de archivos o una persistencia parcial de documentos.
Si aparecen originales o derivados modificados durante el corte, se detiene.

## Despliegue

En `mirror-deploy`, publicar y seleccionar las imágenes nuevas y ejecutar:

```sh
./deploy.sh --env-file .env
```

El script valida Compose y descarga imágenes antes del corte. Luego detiene
la aplicación anterior (gateway, API, workers, dispatcher y PWA), mantiene los
motores disponibles, y ejecuta en orden `database-migrations`, `arcadedb-schema`
y `data-migrations`. Sólo inicia la nueva aplicación si todos terminan bien.
Si falla la migración, deja la aplicación detenida y conserva el avance para
reintentar el mismo comando tras resolver la causa.

API, workers y dispatcher también dependen de la finalización exitosa del servicio
`data-migrations` en Compose. **Para actualizar una instalación existente hay que
usar `deploy.sh`: `docker compose up -d` por sí solo no detiene los escritores
viejos antes de migrar.** Si hay procesos fuera de este Compose, también deben
estar detenidos durante el corte. Los motores y el volumen `/data` siguen accesibles.

Inventario masivo opcional, sin mutar datos, después de aplicar la revisión SQL:

```sh
docker compose run --rm --no-deps --entrypoint python data-migrations \
  -m src.maintenance.data_migrations
```

El comando por workspace `src.maintenance.cleanup_extractions` queda como utilidad
manual de alcance limitado; no forma parte del procedimiento normal de despliegue.
Tras desplegar, verificar una nota, un audio y la recuperación de procesamiento
por snapshots/SSE. El downgrade de Alembic elimina el registro administrativo;
no restaura los datos derivados borrados. Restaurar una versión anterior requiere
un estado de datos compatible, respaldado antes del corte.

## Despliegue local y revisión SQL ausente

El Compose de `mirror-core` construye imágenes localmente y monta `src` en algunos
servicios, pero Alembic y sus revisiones se empaquetan dentro de la imagen.
Su `deploy.sh` ejecuta `build --pull` para todos los servicios antes de detener
escritores. Un simple `pull` no actualiza esas imágenes locales: puede ejecutar
el migrador nuevo desde `src` mientras Alembic sigue viendo sólo revisiones viejas.

Si aparece `relation "data_migrations" does not exist`, verificar que
`database-migrations` incluya y aplique `20261006_06`. Reintentar el script local
corregido con las mismas opciones de Compose del despliegue anterior. No crear
la tabla manualmente ni marcar la migración como aplicada: Alembic debe crearla
antes del corte masivo. La revisión `20261006_06` está incluida en el Dockerfile.

## Credenciales administrativas locales

Migrador, API, workers y dispatcher reciben explícitamente el mismo usuario root
y `ARCADEDB_ROOT_PASSWORD` que el bootstrap y el servidor. Esto evita que
`env_file: .env.local` introduzca una contraseña diferente de la interpolada por
Compose. Un HTTP 403 en `/api/v1/exists` puede provenir de esa diferencia; comparar
configuraciones sin imprimir secretos antes de cambiar usuarios o permisos.

## Evidencia de validación

- Migración masiva y utilidad de limpieza: 9 pruebas pasaron con PostgreSQL y
  ArcadeDB aislados. Incluyen descubrimiento de varios workspaces, suspendidos,
  pendientes sin base y bases vacías parcialmente provisionadas; dry run sin
  mutaciones; ejecución única; exclusión concurrente; rechazo de fuentes ausentes;
  recuperación tras commit/borrado parcial/backfill; recuperación de jobs y audio.
- Despliegue: 3 pruebas con Docker simulado verifican orden de parada/migración/
  arranque, que fallar cualquiera de las migraciones impide arrancar y que una
  descarga fallida conserva la aplicación en ejecución. Ambos Compose validan.
- Suite local del backend: 122 pruebas pasaron; las integraciones quedan
  opt-in/skipped sin variables de servicios. Incluye rutas retiradas, originales, auth y regresiones.
- Pruebas aisladas PostgreSQL/ArcadeDB/RabbitMQ: 36 pruebas pasaron en conjunto
  (ingestión, limpieza y runtime SQL), incluyendo ingestión idempotente, documentos
  sin extracción/embeddings, commit ambiguo, recuperación de audio/transcript,
  jobs v1 retirados y retry convertido a v2, dispatcher y workers Taskiq reales.
- Limpieza en bases nuevas de ArcadeDB: dry run, distintas variantes de vectores,
  respaldo de datos y archivos, preservación de fuentes, rechazo de cambios de
  inventario y herramienta de corte con historial PostgreSQL y backfill.
- PWA: build, lint y suites de almacenamiento/recuperación, incluida recuperación
  de una extracción retirada sin perder audio.

Estas verificaciones usan datos de prueba. No acreditan limpieza ni operación en
producción. No se hizo validación visual en navegador durante esta etapa.

## Limpieza del código y conservación del visor — 2026-10-07

Se eliminó la implementación exploratoria y sus consumidores. La API de navegación
y el visor permanecen en modo de lectura. Las configuraciones de embeddings y
reflexión se quitaron también de Compose local y de producción. Los documentos,
audio, exportación/importación y el nuevo extractor de emociones se conservan.

Validación adicional: 100 pruebas locales del backend, 31 integraciones aisladas
con PostgreSQL/ArcadeDB (dos pruebas de broker omitidas), y build, lint y seis
suites de la PWA. Las integraciones incluyen limpieza masiva, procesamiento de
documentos/audio, escritura de emociones y navegación con extremos `Document`
sin tipos históricos `Claim`. Estas pruebas no ejecutan migraciones sobre datos
de usuario ni acreditan un despliegue de producción.
