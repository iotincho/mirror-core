# Plan de implementación del panel administrativo

Estado: frontend, API de lectura y contenedores LAN implementados, validados e iniciados en esta máquina; publicación, despliegue en otro entorno y operaciones posteriores pendientes. Fecha: 2026-10-17.

## Ajuste de alcance aprobado el 2026-10-16

El usuario pidió posponer autenticación, sesiones y roles para simplificar la primera entrega, destinada a LAN. Se comienza por la base de `mirror-admin`: React-admin/TypeScript/Vite, tema visual, Dashboard y Usuarios de solo lectura con demo de desarrollo y contrato/adaptador para la API futura. Las etapas de autenticación descritas más abajo quedan como diseño diferido, no como requisito de esta entrega. No se requieren claves en el frontend; si se agrega una clave por entorno al conectar datos reales, su validación será del lado del servidor.

La implementación inicial no publica servicios ni modifica autenticación o datos de la plataforma. El servidor de desarrollo escucha en localhost por defecto; acceso LAN se habilita explícitamente.

## Avance de la segunda entrega

Implementados el entrypoint administrativo separado, usuarios y dashboard SQL, migración de metadatos/fecha de alta, inventario reconciliable con checkpoints por cuenta, actividad opt-in de foreground en la PWA e integración por defecto del panel con la API. La API no monta contenido privado ni tiene mutaciones administrativas. Se validó con PostgreSQL desechable y navegador; la base y el directorio de workspaces configurados localmente no estaban disponibles, por lo que no se migraron datos de la plataforma. Ver [guía LAN](admin-lan.md) para ejecutar contra el destino elegido.

## Avance de la tercera entrega

Implementada la imagen compilada de mirror-admin con Nginx sin root, proxy del mismo origen y allowlist de hosts. mirror-deploy incorpora un perfil `admin-lan` dentro del Compose principal con frontend, API y sincronizador, redes separadas y montaje de originales de solo lectura exclusivamente para el sincronizador. El gateway público bloquea el espacio administrativo y conserva API/SSE. El despliegue comprueba módulos/esquema y detiene los servicios administrativos antes de migrar. CI de imagen y publicación al merge preparados; no ejecutados en GitHub ni en registry.

Validada la ejecución con imágenes locales, PostgreSQL y una cuenta/nota desechables. Publicación, elección de versiones, DNS/interfaz y arranque contra los datos LAN siguen pendientes de configuración del destino. Ver el [runbook de contenedores](../../mirror-deploy/ADMIN-LAN.md). La autenticación y las operaciones de escritura siguen diferidas.

## Preparación de la puesta en marcha

Se agregó `mirror-deploy/scripts/check_admin_lan.py` para aceptar una instalación
mediante comprobaciones HTTP de solo lectura: frontend compilado, contratos/caché,
inventario vigente y bloqueo del espacio administrativo en el origen público.
Validado contra el stack Docker desechable con API/PostgreSQL reales. La actividad
deshabilitada y la cobertura histórica parcial no se confunden con errores de
instalación. La verificación del origen público queda explícitamente pendiente
si no se proporciona su URL.

El destino LAN todavía debe definirse. En el workspace no hay contenedores en
ejecución ni `.env` de mirror-deploy; la conexión SQL administrativa predeterminada
no está disponible. La consulta remota de variables/secrets de CI no pudo
verificarse con las credenciales GitHub disponibles (403/404). No se publicaron
imágenes, configuraron secretos ni arrancaron servicios sobre datos existentes.

## Puesta en marcha en el workspace — 2026-10-17

El usuario confirmó esta máquina como destino. Se agregó los servicios administrativos en el
Compose principal del core, con imágenes compiladas desde los repositorios hermanos y los
volúmenes existentes compartidos. PostgreSQL queda en loopback; admin-web escucha
en 127.0.0.1:8081 y 192.168.0.17:8081. La API no monta originales ni recibe claves
de proveedores, y el sincronizador usa `/data/users` en solo lectura.

Se respaldó la base y se verificó el archivo antes de aplicar únicamente la
revisión `20261016_11`. La sincronización terminó con 3 cuentas, 22 documentos y
cero fallos. Se comprobaron ambos accesos HTTP, el runtime y la interfaz en
Chrome headless en escritorio/móvil. Los servicios administrativos quedan
iniciados junto con PostgreSQL; aplicación pública, workers y túnel siguen
detenidos. No se publicaron imágenes ni se modificaron originales.

Ver [operación y respaldo del workspace](admin-workspace.md). La comprobación
desde otro dispositivo LAN sigue pendiente. Autenticación y roles permanecen
diferidos; actividad de accesos sigue deshabilitada.

## Objetivo y alcance

Primera versión: acceso administrativo separado en `admin.elespejo.app`, Dashboard de métricas y listado/detalle de Usuarios de solo lectura. Implementar con React-admin, TypeScript y Vite en el repositorio nuevo `mirror-admin`.

Procesamientos detallados, auditoría de operaciones, bloqueo/desbloqueo, edición de roles, reintentos y acciones masivas son etapas posteriores. La primera versión puede mostrar agregados de procesamientos. No publicar pantallas de ejemplo con datos ficticios en producción.

El mockup `prototypes/admin-console/index.html` es la referencia visual propuesta. Adaptar su jerarquía y paleta a componentes React-admin/MUI, sin copiar su implementación HTML como aplicación final. La elección de React-admin no implica aprobación definitiva de todos los detalles visuales.

## Evidencia del workspace

- `mirror-admin` contiene únicamente README.md y está limpio.
- `mirror-core/src/main.py` y `src/api/router.py` componen actualmente la API pública. El entrypoint público arranca reconciliación de workspaces: no reutilizar ese ciclo de vida para la API administrativa.
- `src/user_management` usa FastAPI Users/SQLAlchemy con cookies revocables y session_version. No hay roles administrativos explícitos ni ámbito administrativo de token.
- User no tiene nombre, fecha de registro ni última actividad propios. El esquema público hereda BaseUser: revisar explícitamente sus campos y asegurar que registro/perfil no puedan modificar atributos privilegiados.
- Los originales son archivos por workspace. Procesamientos e importaciones tienen registros SQL, pero no constituyen un inventario exacto de documentos.
- Las importaciones guardan la fecha original del documento. Esa fecha no equivale a la fecha en que el usuario lo incorporó a la plataforma.
- `mirror-deploy` usa Nginx y Cloudflare Tunnel. El servidor Nginx actual acepta cualquier host y usa una red Docker compartida. Adaptar esta configuración para distinguir dominios.
- Existen cambios locales en mirror-core ajenos a este plan; preservarlos durante la implementación.

## Arquitectura acordada como base

| Repo | Trabajo |
| --- | --- |
| mirror-admin | Aplicación React-admin, proveedores de datos/autenticación, tema, pruebas, imagen y CI |
| mirror-core | Roles, sesiones administrativas, API separada, índice de metadatos y métricas |
| mirror-deploy | Servicios admin-web/admin-api, redes, proxy por host, variables y runbook |
| mirror-pwa | Señal mínima de actividad humana autenticada; sin rutas ni controles administrativos |

Dos procesos FastAPI desde el mismo código/imagen. La API pública no registra rutas administrativas; un entrypoint propuesto `src.admin_main:app` registra únicamente las rutas de administración y su healthcheck. Reutilizar casos de uso y puertos de dominio, sin montar la app pública ni arrancar reconciliación de workspaces desde el servicio administrativo.

React-admin corre en el navegador y consume `/api/admin/*` en su mismo origen. Nginx encamina hacia admin-api por Docker. No se necesita un BFF adicional. Acordar y probar explícitamente cómo Nginx conserva o remueve `/api`; el root_path actual de FastAPI no agrega rutas por sí solo.

La API administrativa no monta archivos de usuarios ni recibe claves de OpenAI/ArcadeDB/workspaces. Definir configuración propia, sin heredar indiscriminadamente el env_file, volúmenes y dependencias del runtime completo. Su cuenta PostgreSQL puede consultar vistas/columnas permitidas de usuarios y métricas y administrar sus sesiones/roles según las operaciones habilitadas. No permitir lectura de tokens OAuth, hashes o secretos por endpoints de catálogo; el mecanismo de login requiere acceso de autenticación expresamente delimitado.

## Etapa 1: contratos y estructura

- Inicializar mirror-admin con React-admin Community, React, TypeScript y Vite en versiones compatibles verificadas al instalar; lockfile, lint y typecheck.
- Estructura propuesta: `src/app`, `src/providers`, `src/features/dashboard`, `src/features/users`, `src/theme`.
- Preparar tema oscuro MUI con los tokens visuales de El Espejo y traducción española; navegación y contenido adaptables a móvil.
- Definir los DTO públicos del panel, permisos, paginación, filtros y ordenamiento antes de integrar.
- Usar dataProvider y authProvider propios sobre la API; no acoplar directamente la API a un formato de query complejo específico de un proveedor externo. Listados devuelven items/total y el adaptador transforma a data/total.
- Si se necesitan fixtures para revisión visual, mantenerlos solo en pruebas/desarrollo; sin fallback a datos ficticios cuando falla la API real.

Entrega: base compilable y contrato de endpoints, sin cambiar flujos de la PWA.

## Etapa 2: identidad, sesiones y API administrativa

- Crear módulo `src/administration` con contratos, modelos, repositorios, casos de uso y rutas; mantener identidad/autenticación dentro de user_management.
- Agregar asignaciones de rol `analyst` y `admin`, con privilegios explícitos por operación. Ambos pueden leer dashboard/usuarios en V1. No usar is_superuser como autorización implícita del panel.
- CLI idempotente para asignar y revocar roles a cuentas existentes; primer administrador por CLI controlada. No crear registro público administrativo ni editor de roles en V1.
- Crear sesiones administrativas separadas, preferentemente en tabla propia: token opaco, usuario, creación/expiración y versión de revocación. El backend público solo acepta sus tokens públicos y el administrativo solo sus tokens administrativos.
- Login inicial con credenciales existentes y rol vigente. Para cuentas que solo usan Google, documentar configuración de contraseña con la recuperación existente; no modificar silenciosamente proveedores ni conceder roles por correo. OAuth administrativo queda para una etapa posterior.
- TTL administrativo configurable y propio, por defecto una hora; logout y revocación. Cookie de producción __Host-el_espejo_admin_session, Secure, HttpOnly, Path=/, sin Domain. Desarrollo usa configuración explícita sin debilitar producción.
- Protección contra intentos repetidos, errores de login genéricos y token CSRF/validación exacta de Origin para mutaciones, login y logout según el flujo. No depender de SameSite, CORS ni un secreto incluido en JavaScript para autorización.
- Consultar cuenta activa, rol y versión vigentes en cada petición. Las revocaciones aplican también a solicitudes posteriores de sesiones ya abiertas. No mantener una transacción larga para todo el servicio.
- Separar entrypoint, documentación OpenAPI, healthcheck y manejo de errores. No registrar endpoints funcionales de notas en admin-api.

Endpoints propuestos (URLs externas):

| Método/ruta | Finalidad |
| --- | --- |
| GET /api/admin/auth/csrf | Preparar protección CSRF según estrategia elegida |
| POST /api/admin/auth/login | Emitir sesión administrativa |
| POST /api/admin/auth/logout | Revocar sesión |
| GET /api/admin/auth/session | Identidad administrativa y permisos vigentes |
| GET /api/admin/dashboard/summary | Totales y métricas del período |
| GET /api/admin/dashboard/activity | Serie diaria de accesos y escritura |
| GET /api/admin/users | Listado paginado con filtros/ordenamiento permitidos |
| GET /api/admin/users/{id} | Detalle de cuenta con metadatos permitidos |

Entrega: API privada funcional, con pruebas negativas de autorización y aislamiento.

## Etapa 3: datos y métricas fiables

### Contrato de métricas

| Métrica | Definición/fuente |
| --- | --- |
| Usuarios totales/habilitados | Conteo de user; distinguir is_active del estado del workspace |
| Altas por período | created_at de usuario incorporado a partir de la migración; históricos desconocidos, no fecha de workspace |
| Usuarios que accedieron | Usuarios únicos con señal autenticada de app visible, excluyendo bots, workers y tráfico automático |
| Usuarios que escribieron | Usuarios únicos con nota nueva creada por escritura/audio; importaciones separadas |
| Notas existentes | Inventario de documentos actuales, por identidad (usuario, documento) |
| Notas creadas/importadas | Eventos separados por procedencia y fecha de incorporación; no confundir authored_at/created_at importado con fecha de importación |
| Procesamientos | Conteo separado de workflows principales y extractores; éxito = completados / (completados + fallidos), excluyendo en curso |

- Añadir User.created_at nullable para históricos y obligatorio para nuevas altas. Mostrar desconocido para cuentas anteriores sin evidencia fiable. No rellenar todo con la fecha de migración.
- Crear índice de metadatos de documentos en PostgreSQL con unicidad (user_id, document_id), fechas/procedencia conocidas, deleted_at y fecha de sincronización. Sin contenido, título, audio ni campos de metadata libres.
- Integrar altas de texto, derivación de audio, importaciones y borrados en los puntos de persistencia reales. Los reintentos o reprocesamientos no cuentan como nuevas notas.
- Diseñar recuperación explícita de la doble persistencia archivo/SQL: proyección idempotente y reconciliación periódica con checkpoints. No prometer atomicidad entre filesystem y PostgreSQL. Una falla de métricas no debe perder un original ya guardado.
- Carga inicial ejecutada por proceso de mantenimiento con acceso a originales; lectura transitoria de archivos solo para extraer los campos permitidos. API administrativa opera contra la proyección SQL.
- Si una carga está incompleta o falla una lectura, informar cobertura/última sincronización; no marcar documentos como borrados por un fallo transitorio.
- Registrar actividad con endpoint autenticado separado en la API pública, propuesto POST /api/activity. La PWA envía señal al entrar/volver al primer plano, con frecuencia acotada; no usar polling/SSE como evidencia de actividad humana.
- Deduplicar actividad por usuario/día y conservar marca de última actividad. No registrar rutas con IDs, texto, audio, IP o payloads innecesarios. Retención inicial propuesta: 90 días de agregados diarios, configurable.
- Períodos de 7/30 días, fechas almacenadas en UTC y agrupación inicial en America/Argentina/Buenos_Aires. Respuestas incluyen zona, intervalo, disponibilidad histórica y actualización.
- No calcular crecimiento porcentual sobre períodos sin cobertura; mostrar no disponible. Índices, paginación máxima 100 y ordenamientos permitidos; sin recorrer workspaces en cada petición HTTP.

Entrega: métricas verificadas contra un conjunto conocido, con backfill y reconciliación repetibles.

## Etapa 4: frontend real

- Login, sesión expirada, acceso denegado y cierre de sesión. No persistir tokens en localStorage; limpiar caché de datos al logout/cambio de identidad.
- Integrar authProvider/dataProvider, cookies y CSRF. Distinguir 401 de 403; no convertir toda denegación de permisos en bucle de login.
- Dashboard: totales, período, actividad diaria, origen de notas y estado agregado de procesamientos.
- Usuarios: correo/ID como identidad actual (no inventar nombres), estado de cuenta, fecha de alta cuando existe, última actividad, cantidad de notas y roles.
- Filtros iniciales: correo/ID, cuenta habilitada y rol; ordenamiento/paginación en backend.
- Detalle con metadatos permitidos. Sin botones operativos de bloqueo/reintento/roles en la primera entrega productiva.
- Estados de carga, vacío, error y métricas históricas parciales; encabezados claros y gráficos con alternativa accesible.
- Revisión del diseño real contra mockup en escritorio y móvil: textos largos, navegación, foco, tablas y desplazamiento interno.

Entrega: Dashboard + Usuarios integrados a datos reales y permisos vigentes.

## Etapa 5: contenedores, integración y publicación preparada

- Imagen mirror-admin con build de Vite y servidor estático; sin service worker/offline. Rutas de SPA, caché adecuada y no-store para respuestas administrativas sensibles.
- Desarrollo con proxy de Vite hacia admin-api para conservar mismo origen.
- Servicios admin-web/admin-api en mirror-deploy. admin-api utiliza la misma versión fijada de mirror-core que la API pública; imagen del panel con versión propia.
- Red administrativa separada; el gateway participa en las redes necesarias y PostgreSQL admite las conexiones explícitas. API pública no participa en la red administrativa. No publicar puertos de admin-api al host.
- Nginx con allowlist de hosts, rechazo de hosts desconocidos, bloqueo del espacio administrativo desde el dominio público y routing administrativo explícito. Conservar el comportamiento de SSE y /api de la PWA.
- No dar a admin-api el volumen core_data, credenciales ArcadeDB/OpenAI ni startup jobs del runtime público. Healthcheck independiente y migraciones como paso único previo al arranque.
- CI de PR: lint, typecheck, pruebas significativas y build. Publicación de imagen al merge según convención existente, con variables/secrets de registry documentados.
- Runbook: migración SQL, backfill, bootstrap de rol, configuración de hosts/cookies, DNS/Cloudflare Tunnel/TLS, versiones y verificación. Usar despliegue aditivo y conservar tablas en rollback; no revertir migraciones destructivamente para volver a una imagen anterior.
- Configurar DNS/túnel/secretos reales, merge y deploy son acciones posteriores separadas. No tratarlas como realizadas por validar Compose o construir imágenes.

Entrega: integración local validada y despliegue revisable; producción requiere validación posterior al despliegue autorizado.

## Validación que habilita el cierre de V1

1. API pública y su OpenAPI no contienen rutas administrativas, incluso accediendo directamente al proceso sin proxy.
2. Token público renombrado no autentica en admin-api; token administrativo tampoco autentica en API pública. Sin rol, sesión vencida o cuenta deshabilitada no hay acceso.
3. Intentos manuales de modificar roles/is_superuser por registro o perfil no elevan permisos. Rol revocado corta acceso en la siguiente petición.
4. Origen PWA/tercero no puede ejecutar login/logout administrativo; probar CSRF y cookies en hosts distintos bajo el mismo sitio y detrás del proxy real.
5. Respuestas de usuarios/métricas no incluyen hashes, OAuth tokens, secretos de workspace ni material privado. No exponer campos libres de errores/config/checkpoints de procesamientos.
6. Inventario concuerda con archivos para texto/audio/importación; soporta duplicados, reintentos, reprocesamiento, borrado y caída entre archivo y proyección SQL.
7. Actividad y tasas respetan definiciones y zona horaria; períodos desconocidos no muestran ceros ni crecimientos ficticios. Bots/workers/SSE no inflan activos.
8. Listado paginado/filtrado y dashboard con conjunto conocido; backfill repetido no duplica y reconciliación recupera fallos.
9. Proxy real rechaza host desconocido y ruta administrativa en host público, preserva acceso normal y SSE. admin-api arranca sin dependencias de contenido privado.
10. Frontend verifica carga/error/vacío/403/logout y navegación con teclado, escritorio y móvil. Pruebas locales no sustituyen comprobación de cookies/TLS/DNS en destino.

## Orden de cambios revisables

1. core: roles, sesiones y entrypoint administrativo, migraciones aditivas y CLI.
2. core: índice/actividad/métricas, carga inicial y recuperación; PWA: señal mínima de actividad.
3. admin: base React-admin, tema, login, proveedores, Dashboard y Usuarios.
4. deploy: servicios, proxy, aislamiento y runbook; admin: imagen y CI.

El frontend puede desarrollarse contra contratos/fixtures durante las primeras etapas; integrar y cerrar la entrega solo cuando la API real y los conteos hayan pasado sus validaciones.

## Etapa posterior: operaciones administrativas

Propuesta separada: bloqueo/desbloqueo con motivo, revocación de sesiones públicas/administrativas, política explícita sobre trabajos ya en cola e invitaciones, auditoría transaccional, confirmaciones, límites por rol y recuperación idempotente de procesamientos. No habilitar edición genérica de user o processing_records. Decidir MFA/step-up al incorporar acciones sensibles y evaluar acceso adicional por gateway de identidad.
