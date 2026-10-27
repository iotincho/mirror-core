# Recuperación de contraseña con código y Resend

La pantalla de ingreso ofrece `Olvidé mi contraseña`. El usuario solicita un
código por email e ingresa sus seis dígitos junto con la nueva contraseña y su
confirmación. Puede pegar el código o usar el autocompletado del navegador.
El cambio exitoso vuelve al ingreso, sin iniciar sesión automáticamente.

Sólo son elegibles usuarios activos con `password_login_enabled = true`.
Las cuentas creadas exclusivamente con Google continúan recuperando su acceso
mediante Google. Una cuenta local que posteriormente vincula Google conserva
su contraseña local y su elegibilidad. No se fusionan cuentas por email.

## Contrato y límites

- `POST /api/auth/forgot-password`: JSON `{ "email": "..." }`. Responde `202`
  con el mismo mensaje y `retry_after_seconds: 60` para cuentas elegibles,
  inexistentes, sólo Google o que agotaron el presupuesto por email.
- `POST /api/auth/reset-password`: JSON `{ "email": "...", "code": "012345",
  "password": "..." }`. Responde `204` al completar el cambio.
- Código incorrecto, vencido, consumido o agotado: `400 recovery_invalid_code`.
  Contraseña inválida: `400 recovery_invalid_password`.
- Presupuesto por IP agotado: `429 recovery_rate_limited` y `Retry-After`.
- Configuración de correo ausente/inválida: `503 recovery_not_configured`.

| Control | Política |
|---|---|
| Separación entre envíos por email | 60 segundos |
| Envíos por email | 3 en una hora y 10 en 24 horas, ventanas móviles |
| Solicitudes por IP | 10 en 10 minutos, compartidas por solicitud y cambio |
| Intentos incorrectos por código | 5 |
| Vencimiento del código | 10 minutos desde su primera emisión |

Reenviar conserva código, vencimiento e intentos. Agotar intentos no bloquea la
cuenta ni el login; el desafío agotado se reemplaza después de su vencimiento,
respetando los presupuestos de envío. Los límites por email también se aplican
a direcciones sin cuenta, sin exponer la elegibilidad en la respuesta.
El contador visual ayuda al usuario; el servidor siempre aplica los límites.
No se incorporan presupuesto global ni alertas en esta etapa.

## Persistencia, sesión y entrega

`src/use_cases/auth/recover_password.py` decide estados y abre el puerto de
transacción de cambio, sin recibir sesiones SQL ni depender de FastAPI Users.
Tipos y contratos viven en `src/core/auth/`; acceso traduce sus errores al HTTP
anterior. `src/bootstrap/recovery.py` conecta hashing, protección de credenciales
y correo. `RecoveryRepository` en `src/adapters/storage/postgres/` persiste
historiales acotados y serializa las
operaciones por IP y dirección con bloqueos de fila. Los identificadores de email
/IP y el código se protegen con HMAC; el código necesario para reenvíos queda
cifrado con una clave de dominio separado. No se escribe en claro en la base,
la cola ni los logs de la aplicación.

Consumo del código, contraseña hasheada, incremento de `session_version`,
revocación de sesiones y desactivación de destinos push se confirman juntos.
La validación y el hashing reutilizan la política y el helper de FastAPI Users.
Los cambios de contraseña deben pasar por este caso de uso e incrementar la
versión; no se expone el router JWT de recuperación del framework.

`recovery_transaction.py` mantiene copias desacopladas del ORM y aplica cambios,
revocación y outbox en el mismo commit. El enlace SQL con invitaciones/push conserva
su orden de locks hasta migrar esa capacidad. Cifrado y Resend viven en
`src/adapters/providers/{security,email}/`; no cambian claves, HMAC ni idempotencia.

Los tokens guardan la versión de sesión con la que se autenticaron: un login que
termina después del reset no puede emitir una sesión válida basada en credenciales
anteriores. La autenticación serializa la verificación y la actualización de hashes
con el cambio de contraseña. Rehashear la misma contraseña no invalida un código.

El alta de un envío y su outbox se confirman en la misma transacción. Taskiq recibe
solamente identificador y generación; `SendRecoveryEmail` carga el estado actual,
controla vencimiento/consumo, registra el resultado y decide sus reintentos.
Hay hasta cuatro intentos, con esperas de 10, 30 y 120 segundos; se respeta un
`Retry-After` mayor del proveedor si el código seguirá vigente. Se reutiliza la
misma clave Resend `password-recovery/<delivery UUID>` ante respuestas ambiguas.
Un reenvío explícito autorizado tiene otro UUID, conservando el código vigente.
La idempotencia del proveedor cubre reintentos de una entrega, y no reemplaza
los límites de solicitudes de nuestra API.

El workflow usa el runtime existente sin exigir un workspace activo. La FK de
`processing_records.user_id` pasa a `user.id`; los workflows de documentos
siguen exigiendo workspace por defecto. Estos trabajos internos no aparecen en
listados/SSE de documentos ni admiten reintentos desde las rutas de documentos.

El dispatcher borra el material cifrado vencido en lotes, conserva como máximo
un día de filas IP inactivas y elimina direcciones inactivas por dos días con
sus entregas. El éxito o quinto intento incorrecto borra inmediatamente el código.

## Configuración y publicación

API, workers y dispatcher necesitan la misma configuración:

```dotenv
RESEND_API_KEY=<clave de envío del servidor>
AUTH_EMAIL_FROM=El Espejo <acceso@dominio-verificado.example>
PASSWORD_RECOVERY_SECRET=<secreto aleatorio independiente de al menos 32 caracteres>
PASSWORD_RECOVERY_TRUSTED_PROXY_CIDRS=[]
```

Generar el secreto una vez con `openssl rand -hex 32` y conservarlo entre
reinicios. No cambiarlo entre réplicas. Resend requiere un remitente de un dominio
verificado. Las claves permanecen en configuración del servidor, nunca en Vite.
El adaptador utiliza HTTPX; no agrega un SDK del proveedor.

`PASSWORD_RECOVERY_TRUSTED_PROXY_CIDRS` es un array JSON de las redes de los proxies
confiables. Vacío usa la IP del socket e ignora `X-Forwarded-For`. Detrás de
Cloudflare Tunnel/Nginx, configurar la red real del gateway y del túnel: el código
recorre la cadena desde el extremo confiable y toma la primera IP no confiable.
No configurar `0.0.0.0/0` ni `::/0`; se rechazan. Si se deja vacío detrás del proxy,
los clientes compartirán el presupuesto de la IP del gateway.

1. Configurar el dominio/remitente en Resend y las variables del servidor.
2. Aplicar `alembic upgrade head` con la nueva imagen de migraciones.
3. Actualizar API, workers y dispatcher a la misma versión; luego la PWA.
4. Probar con una cuenta local controlada que llegue el código y cierre las sesiones
   anteriores. Confirmar la IP efectiva detrás del proxy y sus límites.

La migración `20261015_10` conserva sesiones anteriores con versión cero.
El dueño confirmó que las cuentas existentes con Google se crearon con Google:
se marcan sin contraseña local, y las demás con contraseña local. Los registros
nuevos guardan su método desde el alta, antes de cualquier asociación posterior.
Evitar mezclar APIs antiguas que ignoren la versión de sesión con APIs nuevas
que ya permitan recuperar contraseñas.

## Validación

Las pruebas unitarias cubren protección de secretos, confianza de proxies,
contenido del email, idempotencia y clasificación de fallos de Resend.
Las pruebas PostgreSQL cubren rutas reales, sesiones, límites concurrentes,
consumo único, hash upgrades, expiración, outbox, replay del worker, aislamiento
entre usuarios y migración de cuentas/sesiones anteriores.

```sh
RECOVERY_TEST_DATABASE_URL=postgresql+asyncpg://.../recovery_test \
  python -m pytest tests/integration/test_password_recovery_postgres.py \
  tests/integration/test_password_recovery_migration.py
```

Usar exclusivamente una base descartable cuyo nombre empiece con `recovery_test`:
la fixture de recuperación limpia sus tablas, y el test de migración crea y elimina
su propia base temporal en ese mismo servidor. Las pruebas no llaman a Resend real.

La PWA agrega `tests/password-recovery.test.mjs`. La revisión de Chromium usa la
compilación real con API simulada: 1440 px, 390 px y 320 px, sin desbordamiento y
con controles de al menos 44 px. Entrega real del email y operación desplegada
quedan pendientes de la configuración y publicación.

Referencias del proveedor: [envío](https://resend.com/docs/api-reference/emails/send-email)
y [claves de idempotencia](https://resend.com/docs/dashboard/emails/idempotency-keys).

Resultado local del 15-10-2026: 41 pruebas enfocadas de auth/recuperación en verde;
suite ampliada del backend con 312 aprobadas, 72 omitidas y un fallo anterior en
`test_archive_import_queues_v4_children_and_replays_without_duplicates` (espera
sólo dos extractores aunque la configuración también encola `document_title`).
Se reprodujo ese mismo fallo en una copia de HEAD anterior a esta implementación.
La PWA pasó sus 20 archivos de pruebas, build y lint; Ruff de los archivos
modificados y `docker compose --env-file .env.example config --quiet` pasaron.
