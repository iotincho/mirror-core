# Invitaciones para escribir — backend curado

> Actualización: [Centro de notificaciones](notification-center.md) incorpora la bandeja
> y separa habilitación diaria de push. Aplicar `20261020_12`. La descripción histórica
> de v1 que exigía suscripciones para habilitar/generar cambió:
> hoy se genera una invitación y su aviso aun sin suscripciones; VAPID sólo es necesario
> para registrar dispositivos y enviar push. Los demás contratos se conservan.

El motor prepara paquetes curados (`generic-v2`, catálogo `2`): hasta tres temas
con tres profundidades cada uno. Las preguntas medias conservan las doce preguntas
del catálogo anterior. No lee notas, no consulta ArcadeDB y no invoca modelos.
Una respuesta entra por el alta normal de documentos y conserva su variante exacta.
Aplicar la migración `20261029_18` antes de iniciar los procesos actualizados.
El formato, feedback, interacciones y compatibilidad están en el
[contrato v2](daily-question-v2-contract.md).

## Arquitectura y persistencia

`src/core/exteriorization` contiene contratos, banco, selector y cálculo horario.
`src/use_cases/exteriorization` coordina mediante puertos transaccionales; SQL y
sus locks viven en `src/adapters/storage/postgres/invitation*.py`, y Web Push en
`src/adapters/providers/web_push`. Bootstrap inyecta configuración y compone
servicios y rutas públicas por separado. Los casos de uso
`ConfigureInvitations`, `GenerateInvitation`, `ScheduleInvitations` y
`SendInvitation` poseen las decisiones y transiciones del flujo.

PostgreSQL conserva preferencias, suscripciones, invitaciones, envíos por
dispositivo y vínculos con documentos. Alembic `20261013_08` agrega las tablas y `20261013_09` agrega el binding opaco por suscripción.
Cada invitación contiene la pregunta exacta, origen, candidato, categoría,
versiones, fecha local, zona, hora programada, vencimiento y primera apertura.
Las invitaciones históricas no cambian al actualizar el banco ni las preferencias.
El paquete y la política aceptada se congelan en columnas JSONB de la invitación;
los IDs de preguntas se indexan con pertenencia a invitación/propietario/tema.
Una lectura histórica sin paquete proyecta una única pregunta `legacy` con IDs
deterministas. No se atribuyen retrospectivamente temas personales.

La programación reserva por usuario/fecha local mediante lock de preferencias y
restricción única parcial para `scheduled`. La invitación, los envíos por dispositivo,
los jobs `invitation_push` y su outbox se confirman en la misma transacción.
No se genera una pregunta distinta por dispositivo. Los jobs internos quedan
fuera de `/processing` y de los eventos de documentos de la PWA.
Una ocurrencia sin opciones elegibles se reserva como omitida sin crear pregunta,
notificación ni push; no se relajan cierres para forzar un envío.

El dispatcher existente ejecuta el programador cada ciclo (aproximadamente cinco
segundos). Taskiq ejecuta los envíos; PostgreSQL conserva leases, generaciones,
recuperación e intención de envío si RabbitMQ está caído. Los IDs de mensajes no
incluyen preguntas, endpoints ni claves. Se reutiliza la comprobación existente de
workspace activo; un workspace suspendido no genera ni envía invitaciones.

## Horarios y reintentos

- Habilitación inicial: desactivada. Hora sugerida: `20:30`; la PWA debe proponer
  la zona del dispositivo y permitir corregirla. El servidor nunca la cambia por viajes.
- Hora inexistente por cambio de verano: primer minuto local válido posterior.
- Hora repetida: primera ocurrencia. No se vuelve a enviar durante la segunda.
- Activación/cambio horario: siguiente ocurrencia futura; no hay envío retroactivo.
- Ventana: hasta dos horas después del horario, limitada por medianoche local.
- Tras una caída prolongada se omiten días anteriores y se considera la ocurrencia
  de hoy solamente si su horario pasó y sigue dentro de la ventana.
- Cambiar horario/zona no reabre una fecha local ya reservada.
- Sin suscripciones vigentes se genera igualmente la invitación y su aviso en la bandeja;
  no se crean trabajos de envío push.
- Hasta cuatro intentos por dispositivo, con demoras 10/30/120 segundos y sin
  sobrepasar vencimiento ni los límites de recuperación del runtime.
- 404/410 invalidan esa suscripción. 408/429/5xx y fallos de transporte admiten retry.
  Los demás rechazos son definitivos; los errores se guardan como códigos sanitizados.
- Cada intento revalida preferencia, suscripción, propietario y vencimiento.
- Desactivar cancela envíos pendientes/reintentables, incluidas pruebas ya pendientes.
  Puede pedirse una nueva prueba manual estando desactivada la programación.
- La prueba tiene cinco minutos de vigencia, se dirige al dispositivo actual,
  exige `Idempotency-Key` y limita nuevas solicitudes a una por minuto/usuario.
  Repetir una solicitud aceptada no genera otro envío ni consume la rotación diaria.

Los estados de envío son `pending`, `retrying`, `accepted`, `expired`, `cancelled`
y `failed`. `accepted` significa aceptación del servicio push, no recepción,
visualización ni lectura humana. La primera apertura es un evento separado.
Los fallos terminales del runner y los envíos vencidos se reconcilian periódicamente.

No se promete exactamente una entrega: una caída entre aceptación remota y
commit local puede repetir un envío. El payload lleva un `tag` estable por invitación
para que el service worker reduzca duplicados. TTL se limita al tiempo restante.

## Configuración

VAPID identifica a esta aplicación ante el servicio push del navegador. Son dos
claves del mismo par: la pública se usa al suscribir el dispositivo y la privada
firma los envíos desde el backend. No son claves de Google/OpenAI ni hace falta
crear una cuenta en un proveedor para generarlas.

**No se autogeneran al iniciar API o Compose.** El comando siguiente genera archivos
una sola vez, cuando se lo ejecuta explícitamente. Después hay que configurar las
variables de entorno con esos valores. Las claves efímeras autogeneradas por el
runner de integración son exclusivamente para pruebas simuladas.

Instalar dependencias y migrar antes de iniciar el runtime:

```sh
python -m pip install -e '.[dev]'
python -m alembic upgrade head
python -m src.bootstrap.vapid /private/path/vapid
```

El generador crea `private.pem` con permiso 0600 y `public.txt` con la clave pública
base64url del punto P-256. No imprime claves ni sobrescribe archivos existentes.
Generar el par una sola vez y conservarlo entre reinicios.

Variables nuevas:

| Variable | Uso |
| --- | --- |
| `WEB_PUSH_PUBLIC_KEY` | Contenido de `public.txt`, entregado a la PWA autenticada. |
| `WEB_PUSH_PRIVATE_KEY` | Ruta PEM accesible al worker, o clave privada DER base64. |
| `WEB_PUSH_SUBJECT` | Contacto VAPID, por ejemplo `mailto:admin@example.com`. |
| `WEB_PUSH_ALLOWED_ORIGINS` | Array JSON de orígenes públicos exactos, por ejemplo `["https://espejo.example.com"]`. |
| `WEB_PUSH_ALLOWED_HOSTS` | Array JSON opcional de sufijos de proveedores confiables. |

La clave privada queda exclusivamente en el servidor. Si se configura una ruta,
montar el archivo en los contenedores con permisos para su usuario de ejecución.
El deploy también admite DER base64 en su entorno privado sin mounts adicionales.
API, workers y dispatcher deben tener la misma configuración VAPID. Para convertir
un PEM generado en un archivo DER base64 sin imprimirlo:

```sh
openssl pkey -in /private/path/vapid/private.pem -outform DER \
  | openssl base64 -A > /private/path/vapid/private-der-base64.txt
chmod 600 /private/path/vapid/private-der-base64.txt
```

Para Compose local, el archivo que cargan API/worker/dispatcher es `.env.local`.
Se puede usar una carpeta ignorada como `.env.vapid` para conservar los archivos:

```sh
.venv/bin/python -m src.bootstrap.vapid .env.vapid
openssl pkey -in .env.vapid/private.pem -outform DER \
  | openssl base64 -A > .env.vapid/private-der-base64.txt
chmod 600 .env.vapid/private-der-base64.txt
```

Configurar en `.env.local` (los textos entre `<...>` se reemplazan por el contenido,
no por el nombre de archivo):

```dotenv
WEB_PUSH_PUBLIC_KEY=<contenido de .env.vapid/public.txt>
WEB_PUSH_PRIVATE_KEY=<contenido de .env.vapid/private-der-base64.txt>
WEB_PUSH_SUBJECT=https://mind.elespejo.app
WEB_PUSH_ALLOWED_ORIGINS=["https://mind.elespejo.app"]
```

`SUBJECT` es una URL de contacto o `mailto:tu-correo`; no es una clave ni una
credencial. `ALLOWED_ORIGINS` debe contener el origen exacto desde donde abrís la
PWA (protocolo, host y puerto si corresponde), sin rutas. Adaptar ambos ejemplos al
entorno real. Usar DER base64 evita tener que montar el archivo PEM en contenedores:
una ruta del host no existe automáticamente dentro del worker.

El par se conserva entre reinicios. Cambiar `.env.local` requiere recrear los
contenedores que consumen esas variables; el reload de Uvicorn no recarga el
entorno del contenedor. Desde `mirror-core`:

```sh
docker compose up -d --build
```

Compose usa `../mirror-pwa` como contexto y volumen: las dos ramas deben estar
activas en esos directorios habituales. Aplica Alembic antes de API/worker/dispatcher.
Luego abrir la PWA → menú → Invitaciones para escribir → **Enviar prueba** y
conceder permiso. No hace falta habilitar el horario diario para una prueba.

No copiar archivos de claves al repositorio. Rotar el par exige renovar las
suscripciones del navegador; la v1 no implementa rotación automática.
Las claves vacías hacen que alta/prueba de push respondan 503
`web_push_not_configured`; la captura normal continúa disponible.

En desarrollo `docker-compose.yml` ya carga `.env.local` para API/worker/dispatcher.
En `mirror-deploy`, el bloque compartido `x-core-runtime` propaga las variables
nuevas. No hace falta otro contenedor ni un timer dentro del proceso web.

Arranque fuera de Compose, con PostgreSQL migrado y RabbitMQ disponibles:

```sh
python -m taskiq worker src.bootstrap.messaging:broker src.bootstrap.worker \
  --workers 1 --max-async-tasks 4 --max-prefetch 0 --ack-type manual
python -m src.bootstrap.dispatcher
```

`DATABASE_URL`, `RABBITMQ_URL` y `PROCESSING_QUEUE_NAME` deben corresponder al
mismo entorno. No se aplican migraciones ni se despliega desde las pruebas.

## Contrato HTTP para la PWA

Todas las rutas requieren cookie autenticada y se publican bajo `/api`.
No se acepta `user_id` del cliente. Mutaciones de exteriorización verifican
`Origin`/`Sec-Fetch-Site`, además de la cookie SameSite=Strict existente; configurar
el origen público detrás de Nginx/HTTPS. No se habilita CORS con credenciales.

| Método/ruta interna | Entrada/salida |
| --- | --- |
| `GET /exteriorization/preferences` | `enabled`, `local_time`, `timezone`, `next_due_at`. |
| `PUT /exteriorization/preferences` | JSON completo `{ "enabled": true, "local_time": "20:30", "timezone": "America/Argentina/Buenos_Aires" }`. Habilitar no requiere suscripción ni VAPID. |
| `GET /exteriorization/push/public-key` | `{ "public_key": "…" }`. |
| `POST /exteriorization/push/subscriptions` | Objeto PushSubscription `{ "endpoint": "…", "keys": { "p256dh": "…", "auth": "…" }, "expirationTime": null }`; devuelve solo `{ "id": "UUID", "active": true, "binding_id": "UUID" }`. |
| `DELETE /exteriorization/push/subscriptions/{id}` | 204 idempotente, solo propietario y sesión actuales. |
| `POST /exteriorization/invitations/test` | `{ "subscription_id": "UUID" }` + `Idempotency-Key: UUID`; 202 con invitación persistida. |
| `GET /exteriorization/invitations/{id}` | Pregunta exacta y metadatos históricos. |
| `POST /exteriorization/invitations/{id}/opened` | Registra primera apertura una sola vez; devuelve invitación. |
| `POST /exteriorization/invitations/{id}/feedback` | Opinión sobre una variante, con `Idempotency-Key`; no necesita que la nota ya haya subido. |
| `POST /exteriorization/invitations/{id}/interactions` | Batch idempotente de hasta 32 observaciones/navegaciones. |
| `POST /v2/documents` | `invitation_id` e `invitation_question_id` opcionales, con su `Idempotency-Key` habitual. |

La invitación pública incluye `id`, `question`, `candidate_id`, `category`, `source`,
`engine_version`, `catalog_version`, `kind`, `local_date`, `timezone`, `scheduled_at`,
`expires_at`, `created_at` y `first_opened_at`. Agrega `question_schema_version`,
`default_question_id` y `question_groups`; no incluye políticas, temas internos,
evidencia o datos de suscripciones. El campo `question` sigue siendo la inicial.
Propiedad incorrecta o recurso inexistente devuelve 404. Conflictos de cuenta,
idempotencia o falta de suscripción activa devuelven 409; límite de prueba 429 con
`Retry-After: 60`; fecha/zona/keys inválidas 422. El 202 no acredita entrega push.

Alta de suscripción idempotente por endpoint. No se transfiere un endpoint entre
cuentas: 409 `subscription_account_conflict` exige reconciliar, desuscribir y crear
una nueva suscripción local antes del alta autenticada en otra cuenta. La misma
cuenta puede registrar de nuevo su endpoint tras login. El servidor guarda un hash
del token de sesión para asociar dispositivos; nunca persiste otra copia de la cookie.

`POST /auth/logout` desactiva las suscripciones asociadas a esa sesión antes de
revocarla, cancelando sus envíos pendientes. Otros dispositivos siguen activos.
La PWA debe retirar también su suscripción local. En logout offline, debe conservar
el estado local de logout, suprimir notificaciones y reconciliar antes de otra cuenta.

Payload push:

```json
{
  "binding_id": "UUID-opaco-de-la-suscripción",
  "title": "Un momento para vos",
  "question": "¿Cómo estuvo tu día?",
  "invitation_id": "UUID",
  "url": "/?invitation_id=UUID",
  "tag": "invitation:UUID"
}
```

La ruta de apertura acordada usa el parámetro `invitation_id`; el service worker
existente deberá enfocar/abrir esa URL y el editor resolver el ID después de login.
Mostrar la pregunta fuera del texto, preservar borradores y no crear una nota por
abrir. Consultar la invitación autenticada para resolver propietario/fecha original.
El backend permite responder invitaciones históricas o vencidas.

El `invitation_id` tipado del alta se valida y persiste en `document.metadata.invitation_id`,
preservando el formato actual de originales/archivos. El recibo durable incluye el
vínculo; la aceptación SQL crea `invitation_responses` junto al job de la nota.
La reconciliación completa el vínculo si el original se escribió antes de un fallo SQL.
El vínculo integra el hash de idempotencia. Borrar una nota retira su vínculo al marcar
su recurso como eliminado. Importar un archivo conserva sus metadatos históricos,
pero no crea relaciones contra invitaciones de otra base o cuenta.

`invitation_question_id` se normaliza a la pregunta inicial cuando se omite, y viaja
por los mismos recibos/manifests/metadatos y por el audio derivado. Los recibos v1
conservan su identidad: un replay no agrega metadatos al original ni recalcula su
hash con el formato nuevo. Elegir otra variante con la misma clave es conflicto.
El feedback se conserva aparte del documento y restringe las futuras propuestas
del tema; no impide responder voluntariamente una invitación histórica.

## Actualización y rollback de v2

`20261029_18` es aditiva, sin backfill semántico. Actualizar API, worker y dispatcher
antes de habilitar una PWA que envíe variantes; los workers anteriores no conservan
ese campo. Seguir el procedimiento de escritores detenidos de la
[guía de implementación](development/implementation.md). Clientes PWA anteriores
pueden seguir enviando solo `invitation_id` y reciben la pregunta inicial.

El downgrade elimina paquetes/políticas, índices de variantes, actividad y límites
v2. Conserva las preguntas originales y los documentos/audio, pero pierde esa
historia SQL. Preferir mantener el esquema y el runtime que entiende los recibos
aceptados; no hacer rollback de workers mientras haya audio v2 pendiente.

## Verificación

Suite habitual y lint:

```sh
python -m ruff check src tests migrations
python -m pytest
```

Pruebas opt-in, exclusivamente contra servicios aislados previamente migrados:

```sh
INVITATIONS_TEST_DATABASE_URL='postgresql+asyncpg://.../isolated_test' \
INVITATIONS_TEST_RABBITMQ_URL='amqp://.../isolated_test' \
python -m pytest tests/test_exteriorization.py \
  tests/integration/test_exteriorization_postgres.py
```

El transporte simulado cubre rotación, DST, concurrencia, rollback, múltiples
dispositivos, retries, baja 404/410, desactivación, logout autenticado, propiedad,
apertura idempotente y recuperación de respuestas. La prueba Taskiq usa dos procesos
reales y mensajes duplicados; sustituye solamente Web Push por aceptación simulada.

Prueba real pendiente de la PWA y un dispositivo compatible: configurar VAPID/origen,
registrar una suscripción real, solicitar prueba, verificar notificación, tocarla,
consultar pregunta persistida y guardar respuesta vinculada. Después comprobar horario,
cambio de hora, desactivación y logout/cambio de cuenta. Aceptación del proveedor no
sustituye observar el dispositivo. El service worker/editor está implementado en la rama correspondiente de `mirror-pwa`.

## Evidencia local — 2026-10-13

- Ruff (`src tests migrations`) y `git diff --check`: sin errores.
- Suite completa con `INVITATIONS_TEST_DATABASE_URL` y
  `INVITATIONS_TEST_RABBITMQ_URL` habilitados: **175 passed, 79 skipped**.
- Regresión opt-in de `test_processing_postgres.py`, `test_processing_events.py`
  y `test_deferred_ingestion.py`: **38 passed, 2 skipped**. Los dos casos omitidos
  requieren ArcadeDB aislado; no se utilizó un grafo de usuarios.
- Migración `upgrade → downgrade 20261007_07 → upgrade`, seguida de
  `alembic check`: correcta, sin operaciones pendientes.
- `mirror-deploy`: `docker compose --env-file .env.example config --quiet` correcto.
- Dos workers Taskiq reales y RabbitMQ temporal: mensajes duplicados produjeron
  un solo intento aceptado por dispositivo.
- Cifrado del payload y firma VAPID reales, HTTP del proveedor simulado: correcto.
  No se verificó push en dispositivo ni se aplicaron cambios a producción.

PostgreSQL y RabbitMQ fueron temporales. Las suites de invitaciones y del runtime
usaron bases separadas porque reclaman outbox globalmente. No ejecutar suites
paralelas sobre la misma base de pruebas. La suite completa también necesitó
archivos de entorno de ejemplo y un token Cloudflare ficticio para renderizar
Compose; no se inició ningún túnel.

## Ajuste de contrato para la etapa PWA

`binding_id` es un UUID aleatorio de destino, no una credencial ni un ID de usuario.
Se devuelve al registrar la suscripción y se incluye en el payload cifrado de cada
envío. Un alta repetida con la misma sesión lo conserva; otra sesión lo renueva y
cancela entregas pendientes de la asociación anterior. El service worker compara
el binding persistido localmente antes de mostrar el push. Así puede notificar
sin una cookie vigente o sin conexión HTTP, y descartar un push demorado de otra
sesión/cuenta. No habilita acceso a APIs: consultar o responder sigue requiriendo
autenticación y propiedad. Aplicar `20261013_09` antes de usar esta PWA.

## Validaciones abiertas

Las comprobaciones manuales y con dispositivos reales se consolidan en
[pendientes](pending.md). Las pruebas determinísticas no acreditan entrega push real.
