# Invitaciones para escribir: cierre de la etapa 3

Fecha: 2026-10-14. Rama coordinada: `feat/exteriorization-notifications` en
`mirror-core`, `mirror-pwa` y `mirror-deploy`. Validación local; sin publicación,
merge, despliegue ni cambios sobre datos de usuarios.

Las etapas anteriores quedaron guardadas en los commits de backend `338183f` y
`6d29b04`, PWA `db253b0`, y despliegue `5828d56` y `75f210a`. Esta etapa agrega un
recorrido reproducible entre repositorios, corrige una carrera del editor y deja
las instrucciones para validar push real posteriormente.

## Arquitectura verificada

La PWA obtiene permiso mediante una acción explícita, registra la suscripción y
configura horario/zona contra la API autenticada. PostgreSQL conserva la ocurrencia,
la pregunta exacta, los envíos por dispositivo, los jobs y el outbox en una misma
transacción. El programador y `SendInvitation` conservan sus decisiones en casos
de uso; dispatcher, RabbitMQ y Taskiq transportan/ejecutan el trabajo durable.

El payload usa el binding opaco vigente. El service worker lo compara con el
estado local antes de mostrar la pregunta y conserva el ID al abrir. El editor
resuelve la invitación autenticada, muestra pregunta y fecha fuera del texto y
conserva el borrador previo por separado. Guardar usa el alta normal de documentos:
original con `metadata.invitation_id`, vínculo SQL y job habitual de extractores.
El motor de preguntas no lee notas, no consulta el grafo y no invoca modelos.

## Entorno y alcance

- PostgreSQL 16 y RabbitMQ 4.3.6 en contenedores temporales, puertos loopback
  55439/55679; base vacía migrada a `20261013_09`.
- API HTTP real, cookies/sesiones reales y dos procesos de workers Taskiq;
  mensajes publicados por duplicado, leases/outbox y persistencia reales.
- React, Dexie y scripts de worker de producción ejecutados con DOM/IndexedDB,
  PushManager y permisos simulados. El proveedor push es un transporte de prueba.
- Reloj de negocio inyectado por archivo exclusivamente en fixtures. Se pasa del
  13 de octubre 10:00 UTC a 23:30:01 UTC para las 20:30 de Buenos Aires y se avanzan
  once segundos para el retry. El reloj del sistema y la sesión no se modifican.
- Workspace de prueba con almacenamiento real de originales; no se provisiona
  ArcadeDB ni se ejecutan extractores/proveedores. Se verifica su aceptación durable.
- Los endpoints `/__tests__` pertenecen a una aplicación fixture separada; no se
  agregan a la API de producción.

## Resultados

| Comprobación | Evidencia |
| --- | --- |
| Activación y horario | Sin permiso automático; activación explícita, zona elegida y ocurrencia UTC correcta. |
| Duplicados y retries | Dos workers/mensajes duplicados; una invitación diaria, primer fallo transitorio y segundo intento aceptado con la misma pregunta y binding. |
| Apertura y respuesta | Payload capturado ejecuta push/click; borrador previo preservado, fecha histórica, pregunta fuera del textarea; original y vínculo SQL correctos. |
| Flujo existente | Nota aceptada con job `document` y extractores `emotions`, `document_embeddings`, sin ejecutar proveedores. |
| Cambio horario y prueba | Hora actualizada; no segunda ocurrencia para la fecha ya reservada; prueba manual reintentada con envío diario apagado. |
| Aislamiento | Logout revoca sesión/suscripción; push anterior suprimido; otra cuenta recibe 404 sin pregunta; logout offline se reconcilia antes del siguiente login. |
| Adjuntos y captura | Dos casos UI nuevos: no iniciar adjunto/grabación durante apertura y no perder un archivo cuya validación está en curso. |
| Regresión backend | **176 passed, 79 skipped** con PostgreSQL/RabbitMQ opt-in; Ruff sin errores. Omitidos: otras integraciones que requieren servicios no habilitados. |
| Regresión PWA | **74 casos aprobados en 11 archivos**, build producción/desarrollo y lint aprobados. |
| Integración entre repositorios | **1 recorrido aprobado** mediante `npm run test:integration`, con las comprobaciones anteriores. |

La carrera corregida permitía iniciar adjuntos o grabación mientras la invitación
reemplazaba el editor. Ahora esos controles se bloquean durante la apertura, y una
validación de archivo en curso posterga la apertura hasta poder conservarlo.

## Reproducción

Instalar las dependencias de ambos proyectos. Crear exclusivamente servicios
**descartables y aislados**; la prueba puede reclamar outbox y publicar mensajes,
por lo que no debe apuntar a bases/vhosts de usuarios ni compartidos con otro runner.

En backend, migrar esa base y ejecutar la regresión:

```sh
DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:55439/invitation_test' \
python -m alembic upgrade head
python -m ruff check src tests migrations
INVITATIONS_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:55439/invitation_test' \
INVITATIONS_TEST_RABBITMQ_URL='amqp://user:password@127.0.0.1:55679/' \
python -m pytest
```

La suite habitual también requiere las variables de configuración usadas por el
repositorio (incluido un token Cloudflare ficticio para validar Compose localmente).
Las variables de opt-in no habilitan otras suites de servicios externos.

En PWA, después de terminar la suite backend, usando los mismos servicios aislados:

```sh
npm test
npm run lint
npm run build
npm run build -- --mode development
INVITATIONS_TEST_DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:55439/invitation_test' \
INVITATIONS_TEST_RABBITMQ_URL='amqp://user:password@127.0.0.1:55679/' \
INVITATIONS_CORE_PATH='/ruta/a/mirror-core' \
INVITATIONS_PYTHON='/ruta/al/venv/bin/python' \
npm run test:integration
```

El runner genera claves efímeras privadas con permisos 0600, cola única y un
directorio temporal. Imprime la ruta de `evidence.json` y `processes.log`; termina
sus procesos y elimina los usuarios de prueba. Los servicios externos se eliminan
al finalizar la validación. No se versionan claves, cookies ni endpoints de usuarios.

## Pendiente para validar un dispositivo real

El navegador integrado no estuvo disponible y no se utilizó una suscripción real.
No se acredita entrega, visualización, lectura, comportamiento visual ni soporte
real de IndexedDB mediante las pruebas simuladas. `accepted` significa aceptación
del transporte; la apertura es un evento separado.

Con imágenes publicadas posteriormente, configurar VAPID persistente y origen
HTTPS exacto, aplicar ambas migraciones y arrancar API/dispatcher/workers. Seguir
`mirror-pwa/docs/invitations.md`, sección «Recorrido manual pendiente», en Android
y en iOS compatible desde pantalla de inicio. Verificar app abierta/cerrada, permiso
denegado, sesión vencida, borradores/adjuntos, red interrumpida, horario, logout y
cambio de cuenta. Registrar la recepción y la apertura observadas, además del estado
SQL. Las variables y el orden de arranque están en `mirror-deploy/README.md`.
