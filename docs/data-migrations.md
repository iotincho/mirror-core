# Migraciones de datos y recuperación

Procedimiento para el mantenimiento que sigue integrado al arranque. No describe
un plan de nuevas funcionalidades ni acredita el estado de una base desplegada.
Contratos actuales: [ingestión](deferred-ingestion.md) y
[trabajos por extractor](extractor-jobs.md).

## Responsables

- Alembic (`migrations/`) actualiza PostgreSQL.
- `src.graph.arcadedb.schema` prepara el esquema base del grafo.
- `src.maintenance.data_migrations` coordina SQL, grafo y archivos.
  La revisión `20261006_06` crea su registro `data_migrations`.

El migrador conserva `20261006-retire-exploratory-extraction` para instalaciones
que aún tengan ese estado de datos. Descubre workspaces de `ARCADEDB_INSTANCE_KEY`,
incluidos suspendidos y pendientes; usa credenciales administrativas del grafo.
No alcanza directorios globales antiguos fuera de los workspaces registrados.

## Actualización de instalaciones existentes

Revisar el `deploy.sh` del repositorio correspondiente: el de `mirror-core`
construye imágenes locales; el de `mirror-deploy` usa imágenes publicadas.
Retirar escritores de la versión anterior antes de aplicar cambios. No usar
`docker compose up -d` como sustituto del corte: sus dependencias no detienen
procesos viejos que ya están ejecutándose.

El orden es: preparar imágenes, detener escritores públicos y administrativos,
mantener motores disponibles, migrar SQL, preparar esquema ArcadeDB, ejecutar
migraciones de datos y arrancar la aplicación sólo si todo terminó bien.
Detener también escritores externos al Compose. No borrar volúmenes para resolver
un error de migración.

## Inspección y aplicación

Con la revisión SQL aplicada y el servicio configurado, el modo predeterminado
inspecciona sin aplicar la migración:

```sh
docker compose run --rm --no-deps --entrypoint python data-migrations \
  -m src.maintenance.data_migrations
```

Aplicar requiere `--apply --services-stopped`; el servicio de migración de Compose
ya los usa dentro del corte. El flag declara que se retiraron los escritores;
no los detiene por sí mismo. No aplicar para verificar documentación o una suite.

## Garantías y recuperación

El bloqueo PostgreSQL impide dos migradores simultáneos. Se registra avance por
instancia/workspace; otra ejecución omite lo completado y retoma lo interrumpido.
Antes de borrar derivados se inventarían originales/grafo/historial y se publica
un respaldo lógico verificado por hash en `migration-backups/`. Se rechazan
fuentes ausentes, symlinks e inventarios inconsistentes o truncados.
Los originales, audio y transcripciones se conservan.

Esta migración elimina derivados del pipeline retirado, invalida ejecuciones
antiguas y reconstruye documentos base. No es una limpieza rutinaria para ejecutar
de nuevo sobre capas actuales. La utilidad por workspace
`src.maintenance.cleanup_extractions` tiene alcance distinto y no sustituye al
migrador del despliegue.

No existe una transacción conjunta SQL/ArcadeDB/filesystem. Respaldo y checkpoints
permiten recuperar commits ambiguos y cortes parciales; no sustituyen los backups
completos de motores y volúmenes. Un downgrade SQL no restaura derivados borrados.
Si el corte falla, resolver la causa y retomar con las mismas opciones; no marcar
manualmente la migración como aplicada.

## Diagnóstico y validación

Si falta `data_migrations`, comprobar revisión Alembic e imagen del migrador. Montar
`src` no actualiza las revisiones empaquetadas; reconstruir las imágenes locales.
Ante HTTP 403 del grafo, comprobar coherencia de usuario/contraseña entre motores
y servicios sin imprimir secretos.

Pruebas: `tests/integration/test_data_migrations.py`,
`tests/integration/test_extraction_cleanup.py` y `tests/test_local_deploy.py`.
Usar motores desechables; comprobar conservación de fuentes, interrupción/replay,
exclusión y arranque bloqueado ante fallo. Tras un despliegue autorizado, verificar
nota, audio y recuperación por snapshots/SSE.
