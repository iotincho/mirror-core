# Registro con email y contraseña

La política y la identidad viven en `src/core/auth/`; el login usa
`src/use_cases/auth/authenticate.py`. FastAPI Users adapta registro, cookies y OAuth
en `src/adapters/access/api/public/auth/`, conectado por `src/bootstrap/auth.py`.
La contraseña se verifica bajo el mismo lock de cuenta que utiliza recuperación;
un upgrade del hash conserva la versión de sesión y no puede restaurar la contraseña anterior.

La PWA ofrece `Ingresar`, `Crear cuenta` y `Continuar con Google` en la pantalla
de acceso. El email es el identificador; no se incorpora un nombre de usuario.
La contraseña requiere al menos 12 caracteres y no puede contener el email.
La confirmación se comprueba en la PWA y no se envía al servidor.

El recorrido es `POST /api/auth/register` → `POST /api/auth/login` →
`GET /api/auth/session` → activación del almacenamiento local del usuario →
`GET /api/workspace/status`. El registro no crea una sesión por sí mismo.
Si el alta se completa y el ingreso falla, la interfaz vuelve a ingresar con
un aviso de cuenta creada, conservando el email y borrando las contraseñas.
Si la respuesta del alta se pierde, pide probar el ingreso antes de repetirla.

Un email existente lleva a ingresar con contraseña o con Google, según cómo
se creó la cuenta. No se fusionan identidades automáticamente. La asociación
con Google conserva el flujo explícito autenticado existente.

## Preparación del espacio

Estados, contexto y puertos: `src/core/workspaces/`. Coordinación de acceso,
provisión/reconciliación: `src/use_cases/workspaces/`. PostgreSQL mantiene asignación
y locks; `src/adapters/storage/arcadedb/provisioning.py` prepara esquema y principal
restringido. `src/bootstrap/workspaces.py` conecta cifrado, configuración y ciclo de
vida de stores; las rutas de acceso público sólo traducen entrada/resultado.

`GET /api/workspace/status` devuelve únicamente `status`: `pending`,
`provisioning`, `active`, `failed`, `suspended` o `unavailable`. Ambos endpoints
del espacio requieren la cookie y resuelven al propietario desde esa sesión;
no aceptan un identificador de usuario para seleccionar otro espacio.

La PWA abre la pantalla principal cuando el estado es `active`. Los otros
estados muestran una pantalla que conserva la cuenta y permite cerrar sesión.
Durante `provisioning`, el botón vuelve a consultar el estado. Para un espacio
pendiente, fallido o ausente, `POST /api/workspace/prepare` reintenta usando el
aprovisionador existente y conserva la asignación previa. No se fuerza un
aprovisionamiento concurrente ni se reactiva un espacio suspendido.

Si la configuración de instancia o el cifrado de un espacio activo no coinciden,
se informa `unavailable`; un reintento no cambia esa configuración. Un espacio
que queda en `provisioning` tras terminar abruptamente el proceso necesita
reconciliación operativa. No se incorporó un nuevo planificador de recuperación.

El fallo de aprovisionamiento posterior al alta no convierte una cuenta ya
persistida en un error de registro. No se exponen credenciales, nombres de bases
ni detalles internos del fallo en estas respuestas.

## Validación y publicación

`tests/test_signup_flow.py` usa SQLite temporal, las rutas reales de autenticación
y el aprovisionador real con las operaciones remotas de ArcadeDB simuladas.
Requiere las dependencias de desarrollo, incluido `aiosqlite`. Cubre alta,
contraseña hasheada, cookie, logout, duplicados, fallo y recuperación del espacio,
suspensión y aislamiento entre cuentas. La PWA agrega `tests/signup.test.mjs`.

Publicar primero el backend con los endpoints de espacio y luego la PWA.
El registro básico reutiliza el esquema existente. La recuperación de contraseña
incluida en esta entrega agrega una migración y configuración de Resend; ver
[password-recovery.md](password-recovery.md) para el orden de publicación completo.
La validación local no reemplaza probar el recorrido con PostgreSQL, ArcadeDB y
Google desplegados. La verificación de email queda para una etapa posterior;
las cuentas exclusivamente Google conservan ese método de acceso.
