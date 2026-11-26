# Administración local/LAN — API y métricas

La API administrativa se ejecuta desde `src.bootstrap.administration:app`. No está montada en `src.bootstrap.public_api:app`, no comparte su ciclo de arranque y no inicia reconciliación de workspaces, workers, proveedores ni conexiones a ArcadeDB. Esta entrega conserva la decisión de uso LAN sin autenticación administrativa.

El entrypoint expone la aplicación compuesta en `src/bootstrap/administration.py`.
Reglas y hechos tipados viven en `src/core/administration`; consultas, permisos,
actividad e inventario se coordinan en `src/use_cases/administration`.
HTTP, PostgreSQL y lectura de metadatos filesystem son adaptadores separados.
El sincronizador recibe sólo metadatos de originales y conserva `null` cuando
no puede acreditar cobertura; una lectura incompleta invalida el inventario.

Para ejecutar imágenes compiladas y los tres servicios con Docker, seguir el
runbook `mirror-deploy/ADMIN-LAN.md`. El Compose principal, con el perfil `admin-lan`, incluye redes, proxy, sincronización y migración previa; los pasos de
abajo corresponden a desarrollo sin contenedores.

## Operación con el Compose local

El helper `admin-local.sh` selecciona el proyecto `mirror-core`, el perfil
`admin-lan` y `.env` para interpolación. Configurar hosts, puertos, base e
intervalos del destino usando `.env.example`; no asumir IPs o inventarios de
sesiones anteriores. Los datos residen en los volúmenes del proyecto compartido.

```sh
./admin-local.sh status
./admin-local.sh logs
./admin-local.sh check
./admin-local.sh stop
./admin-local.sh build
./admin-local.sh start
```

`stop` detiene sólo los tres servicios administrativos. `start` espera PostgreSQL,
migraciones y healthchecks; no inicia PWA, API pública, workers o Cloudflare.
`check` requiere el script del checkout hermano `mirror-deploy` y usa el puerto
loopback efectivo. No ejecutar `down -v` sobre el proyecto con datos existentes.
Para migraciones del core completo, detener también los escritores públicos.

Laboratorio requiere el mismo `PERSONAL_AXES_ENABLED` en API pública, workers,
dispatcher y admin-api, además del permiso por cuenta. Si no aparece un control
recién implementado, verificar las versiones de las imágenes y recrear los
servicios afectados; recargar el panel no actualiza un contenedor viejo.

## Iniciar con la base de la plataforma

Desde mirror-core, configurar `DATABASE_URL` y `WORKSPACES_PATH` en el entorno o en `.env`, apuntando al volumen/base de desarrollo o LAN deseados. No colocar credenciales en variables VITE_*.

```sh
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m src.bootstrap.inventory_sync
.venv/bin/python -m uvicorn src.bootstrap.administration:app --host 127.0.0.1 --port 8001
```

En otro proceso, para mantener actualizado el inventario:

```sh
.venv/bin/python -m src.bootstrap.inventory_sync --interval 30
```

El sincronizador necesita acceso a los archivos originales. La API solo necesita PostgreSQL; el Compose principal monta el volumen de contenido únicamente en el sincronizador, en modo de solo lectura. admin-api no recibe claves de OpenAI/ArcadeDB ni se publica mediante el gateway público.

Desde mirror-admin:

```sh
npm ci
npm run dev
```

El panel usa API por defecto, en http://127.0.0.1:5176; Vite publica `/api/admin/*` hacia http://127.0.0.1:8001 manteniendo el prefijo íntegro. No hay que remover `/api` en este proceso: sus rutas reales empiezan por `/api/admin` y no usa root_path. `ADMIN_API_PROXY_TARGET` permite apuntar a otra dirección LAN sin poner secretos en el bundle. Para servir el panel en LAN, habilitar su host explícitamente con `npm run dev -- --host 0.0.0.0`; la API puede seguir escuchando solo en loopback si está en la misma máquina que Vite.

La demo sigue disponible con `VITE_DATA_MODE=demo npm run dev`, solo en desarrollo. Build/preview requieren un proxy del mismo origen hacia la API; no incluyen fixtures.

## Qué se obtiene

- Usuarios registrados/habilitados, listado paginado, filtros por correo/ID y estado, ordenamiento permitido, detalle.
- Notas existentes por cuenta y globales, con fecha de sincronización. El inventario se invalida si está incompleto o supera `ADMIN_INVENTORY_MAX_AGE_SECONDS` (300 por defecto).
- Incorporaciones por texto/audio/importación y usuarios que escribieron cuando hay evidencia completa de llegada/procedencia en los receipts. Reprocesar, importar una copia ya existente o repetir la sincronización no duplica documentos.
- Procesamientos por estado y tasa de éxito de workflows principales creados en el período. No duplica extractores hijos; pendiente agrupa queued/waiting/retrying.
- Accesos observados a la app, únicos por usuario/día en Buenos Aires, con fecha de inicio de medición.

Las fechas de creación de cuentas antiguas permanecen null; las cuentas nuevas tienen fecha de alta desde la migración. No se usa la fecha del workspace para inventar una fecha de registro.

Las importaciones conservan su fecha original, pero se cuentan por accepted_at del receipt. En audio se usa la creación efectiva del documento derivado. Archivos .md/.txt subidos (`file_upload`) se clasifican como importaciones. Los originales anteriores sin receipt permiten contar inventario, pero no reconstruir de manera fiable su llegada: las métricas de incorporación/escritura quedan null. Un borrado conserva en la proyección la evidencia de creación conocida, aunque baja el inventario actual. No se pueden reconstruir notas eliminadas antes del primer inventario si no dejaron evidencia durable de su existencia y procedencia. Las métricas de incorporación describen los registros recuperables, no una garantía de histórico completo previo a la instrumentación.

## Actividad de la PWA

Activar `PLATFORM_ACTIVITY_ENABLED=true` en la API pública cuando se despliegue la PWA actualizada. Por defecto está deshabilitado. El endpoint público `POST /activity` (externamente `/api/activity`) usa la sesión normal existente y valida el origen. No permite elegir otro usuario.

La PWA envía una observación al entrar o volver al primer plano, con un máximo de un intento cada cinco minutos por instancia. Sin heartbeat, contenido, ruta, IP ni identificador en el body. Errores, 401 o ausencia del endpoint se ignoran sin cerrar sesión, mostrar avisos o reportar telemetría. Al cerrar sesión se eliminan listeners y se cancela la petición pendiente.

La primera observación fija `activity_since`. Los días anteriores son null; el primer día puede ser parcial. El total de usuarios que accedieron expresa lo observado desde esa fecha, no actividad histórica reconstruida. Se conservan 90 días de agregados diarios; si se deshabilita o se dejan instancias sin actualizar, puede haber huecos que no se reconstruyen. La señal registra apertura/retorno al foreground y no prueba actividad continua durante toda una sesión.

## Registro de consumo de IA

La base del registro está disponible desde la revisión `20261126_28`. Mantener
`AI_USAGE_ENABLED=false` hasta instrumentar las llamadas de todos los procesos.
Al habilitarlo, el dispatcher abre un período desde el reloj de PostgreSQL. Al
deshabilitarlo, cierra el período en su siguiente ciclo de mantenimiento.
Volver a habilitarlo abre otro período. La migración deja el registro vacío y
la cobertura comienza con la activación.

Cada intento admite un recibo con ID técnico estable, cuenta beneficiaria,
funcionalidad, proveedor, modelos solicitado y efectivo, fechas y resultado.
El recibo admite tokens por categoría y duración en segundos. `NULL` conserva
la ausencia de datos y `0` representa uso medido. Se guarda sólo metadata
técnica. Repetir la escritura de un intento conserva su primera atribución y
resultado confirmado. Al cerrar un período, aún se pueden finalizar intentos
iniciados dentro de él. Al borrar una cuenta, se quita su referencia de los
recibos y se conservan sus cantidades para el total global hasta el vencimiento.

El dispatcher aplica `AI_USAGE_RETENTION_DAYS` (90 por defecto, entero positivo)
por fecha de inicio y en lotes de hasta 500, incluso con la captura deshabilitada.
Los períodos de activación se conservan como metadata operativa. En Compose local,
las variables se configuran en `.env` para la interpolación de Compose. Para
procesos ejecutados directamente, `Settings` las toma del entorno o de `.env`.
El downgrade elimina los recibos y los períodos sin recuperación posterior.

Verificación aislada con `AI_USAGE_TEST_DATABASE_URL` y
`tests/integration/test_ai_usage_postgres.py`. La URL debe identificar una base
de pruebas con prefijo `ai_usage_test` en una instancia desechable. El test crea
y elimina una base temporal en esa instancia.

## Recuperación e integridad

El sincronizador guarda un checkpoint por cuenta en PostgreSQL y tiene exclusión mutua mediante advisory lock. Solo persiste IDs, fechas, categorías y flags. No guarda título, texto, audio ni metadata libre. Fallos de lectura, JSON inválido, identidad incorrecta, symlinks o falta del volumen invalidan cobertura sin borrar el inventario previo. Reejecutar recupera las cuentas fallidas.

La lectura de originales sucede fuera del servicio administrativo. Es una proyección periódica, no una transacción conjunta con el filesystem: un cambio concurrente puede verse en el siguiente ciclo. El panel muestra la fecha del snapshot y actualiza sus consultas cada 30 segundos. Una interrupción del proceso no afecta al guardado de notas; después se reanuda desde los originales y checkpoints.

## Validación

- Migración desde esquema anterior: usuarios históricos siguen sin fecha inventada y las sesiones existentes sobreviven.
- PostgreSQL aislado: conteos, filtros booleanos, búsqueda literal con `%`, idempotencia, importación con fecha antigua, extractores hijos, borrados, lectura fallida, inventario vencido y exclusión mutua.
- API pública sin rutas administrativas; API administrativa sin rutas de contenido;
  mutaciones explícitas de Laboratorio y configuración de Journals.
- Respuestas explícitas sin hashes, OAuth, contenido o secretos; errores SQL devuelven 503 genérico y no-store.
- PWA: foreground, frecuencia acotada, limpieza al logout y fallo offline silencioso; suite completa, lint y build.
- Panel: tipos, pruebas, lint, build sin fixtures y verificación por navegador contra la API.

Las pruebas usan `ADMIN_TEST_DATABASE_URL`, que debe apuntar a una base desechable cuyo nombre empiece por `admin_test`. No se ejecutan migraciones ni cargas iniciales automáticamente contra una base existente de la plataforma.


## Permiso experimental de Laboratorio

Desde Usuarios → Ver cuenta → Laboratorio se habilita o quita el acceso de esa
cuenta. Aplicar la migración `20261021_16` antes de iniciar procesos nuevos. El
permiso inicia en `false` para todas las cuentas. El global `PERSONAL_AXES_ENABLED`
debe ser igual en API, workers, dispatcher y admin-api; con el global apagado se
puede guardar el permiso, pero la funcionalidad permanece inaccesible.

El permiso de Laboratorio usa
`PATCH /api/admin/users/{id}/laboratory` con `{"laboratory_enabled": true|false}`.
Se comprueba el origen exacto, incluidos puerto y protocolo. El proxy de mirror-admin
permite ese PATCH y las rutas declaradas de Journals, conservando el Host completo.
Las demás mutaciones permanecen bloqueadas; no se añade autenticación al panel LAN existente.

Las lecturas conservan `REPEATABLE READ READ ONLY`; la mutación usa su propia
transacción de escritura. No se conceden privilegios administrativos al usuario de
la PWA. Revocar bloquea nuevas pruebas y nuevas reservas de ejes, conserva los datos
y permite terminar los trabajos ya aceptados. Ver [contrato](personal-axes-api.md).

## Gestión de Journals

Usuarios → Cuenta → Journals permite activar un template instalado, revisar el
calendario, ajustar etapas/propósito/respaldo, pausar, reanudar, avanzar, cerrar y
consultar revisiones. El prototipo fue aprobado y la etapa 5 está implementada
localmente; no se desplegó ni habilitó. Ver la superficie y garantías completas
en [contratos de Journals](journals-contract.md#administración-lan-y-panel-etapa-5).

Aplicar hasta `20261103_25` antes de actualizar procesos. Compartir
`JOURNALS_ENABLED` con API pública, workers, dispatcher y admin-api; su default
sigue siendo `false`. El dispatcher instala templates de forma idempotente al
reconciliar; el endpoint de lectura no hace instalaciones. Los Compose local y de
distribución pasan el flag explícitamente al proceso administrativo.

No agrega volúmenes, claves de proveedores o acceso al texto de intención/notas
en admin-api. Las nuevas rutas se componen en `src.bootstrap.administration`, con
schemas HTTP específicos y comprobación de origen. Las lecturas son read-only;
las mutaciones confirman su unidad de trabajo antes de devolver recibo.
El proxy LAN debe actualizarse junto al panel para permitir las rutas declaradas.
El gateway público conserva su bloqueo de `/api/admin`.
