# Requisitos multiusuario

Estado: arquitectura inicial acordada
Fecha: 2026-09-30

Este documento registra las definiciones acordadas y las decisiones pendientes para convertir El
Espejo en una aplicación multiusuario. No describe una implementación terminada.

## Objetivos

- Permitir registro e inicio de sesión local.
- Permitir inicio de sesión y asociación de cuenta con proveedores externos, inicialmente Google.
- Evitar implementar desde cero los flujos genéricos de gestión de usuarios.
- Mantener la gestión de identidad encapsulada para poder reemplazar FastAPI Users por otro
  proveedor o tecnología en el futuro.
- Aislar documentos, audios, extracciones, reflexiones, embeddings y grafo entre usuarios.
- Utilizar ArcadeDB como graph store, con una base independiente por usuario.
- Comenzar la etapa multiusuario sin migrar usuarios, bases ni archivos preexistentes: el entorno
  actual no contiene datos que deban conservarse.

## Invariantes de seguridad

1. El identificador de usuario siempre proviene de una sesión validada por el backend.
2. Ningún endpoint acepta `user_id`, nombre de base o nombre de grafo desde el cliente para decidir
   qué datos consultar.
3. Conocer un UUID de otro usuario no permite leer, modificar, reprocesar ni eliminar su recurso.
4. Los procesos en background reciben explícitamente el `user_id` que originó el trabajo.
5. La falta de acceso a un recurso se responde igual que su inexistencia, normalmente con `404`.
6. Una búsqueda semántica o reflexión sólo puede usar embeddings, claims, relaciones y documentos
   del usuario autenticado.
7. La separación del grafo no reemplaza el aislamiento de archivos ni el almacenamiento offline de
   la PWA.

## Límite del módulo de gestión de usuarios

FastAPI Users se adopta inicialmente como implementación interna del módulo de gestión de usuarios.
La aplicación no debe depender directamente de sus modelos, estrategias o clases fuera de ese
módulo.

Estructura conceptual:

```text
src/user_management/
├── models.py              # modelos SQLAlchemy exigidos por FastAPI Users
├── schemas.py             # contratos HTTP propios del módulo
├── database.py            # adaptador PostgreSQL
├── manager.py             # configuración y hooks de FastAPI Users
├── authentication.py      # cookie y estrategia de sesión
├── oauth.py               # Google y futuras identidades externas
├── routes.py              # /auth/*
└── dependencies.py        # adaptación a AuthenticatedUser
```

El único contrato que consume el resto de la aplicación es propio:

```python
class AuthenticatedUser:
    id: UUID
```

Podrá incorporar email, nombre o permisos en el futuro, pero los casos de uso actuales sólo deben
depender del identificador estable. El objeto de FastAPI Users se transforma a
`AuthenticatedUser` dentro de `src/user_management`.

La identidad UUID pertenece a El Espejo y se mantiene estable aunque se reemplace FastAPI Users.
Una futura migración de proveedor debe preservar o mapear ese identificador interno.

## Límite del módulo de workspaces

La asignación y el aprovisionamiento de recursos no forman parte de `user_management`. Se aíslan en
un módulo propio para que cambiar el proveedor de identidad no modifique bases, archivos o backups:

```text
src/workspaces/
├── models.py             # UserWorkspace y estados
├── repository.py         # acceso a user_graphs en PostgreSQL
├── context.py            # resolución del workspace autenticado
├── provisioning.py       # alta y reconciliación idempotentes
├── arcade_admin.py       # operaciones administrativas de ArcadeDB
└── dependencies.py       # adaptación a stores limitados al usuario
```

Contrato interno:

```python
class UserWorkspace:
    user_id: UUID
    arcade_instance_key: str
    database_name: str
    graph_username: str
    filesystem_root: Path
```

El flujo de resolución es:

```text
cookie -> AuthenticatedUser -> UserWorkspace -> stores del usuario
```

Los casos de uso no reciben nombres de base, credenciales ni tipos de autenticación.

### Contrato con la API y la PWA

- Una operación protegida requiere una sesión activa.
- `GET /auth/session` devuelve al menos `{ "user_id": "..." }` cuando la sesión es válida.
- Una sesión ausente, vencida, revocada o inválida devuelve `401`.
- La PWA mantiene el perfil de sesión, no solamente un booleano `authenticated`.
- Ante `401`, la PWA descarta el estado de sesión en memoria y redirige al login.
- Login local, registro, logout, verificación, recuperación de contraseña y OAuth pertenecen al
  módulo de usuarios.
- La lógica de documentos, audio, búsqueda y reflexión no conoce si el usuario ingresó con password
  o con Google.

### Configuración inicial de FastAPI Users

- PostgreSQL con SQLAlchemy async y migraciones Alembic.
- IDs de usuario UUID.
- `CookieTransport` para la PWA.
- Estrategia de sesión persistida en base de datos para permitir revocación; no JWT como estrategia
  principal.
- Dependencia equivalente a `current_active_verified_user` adaptada al contrato
  `AuthenticatedUser`.
- Hash de contraseña provisto por FastAPI Users.
- Soporte OAuth de Google y tabla de cuentas OAuth.
- `associate_by_email=False`: una identidad externa no se vincula automáticamente a una cuenta
  local sólo porque coincida el email.
- La asociación de Google a una cuenta local existente requiere una sesión válida de esa cuenta.

FastAPI Users está en modo mantenimiento: continúa recibiendo actualizaciones de seguridad y
dependencias, pero no funcionalidades nuevas. Por eso su encapsulación es un requisito y no sólo una
preferencia de organización.

Referencias:

- [FastAPI Users: funcionalidades](https://fastapi-users.github.io/fastapi-users/latest/#features)
- [FastAPI Users: SQLAlchemy](https://fastapi-users.github.io/fastapi-users/latest/configuration/databases/sqlalchemy/)
- [FastAPI Users: estrategias de autenticación](https://fastapi-users.github.io/fastapi-users/latest/configuration/authentication/)
- [FastAPI Users: OAuth y asociación de cuentas](https://fastapi-users.github.io/fastapi-users/dev/configuration/oauth/)

## PostgreSQL como registro de usuarios y recursos

PostgreSQL será la fuente de verdad para usuarios, identidades, sesiones y la asignación entre un
usuario y su almacenamiento. En esta etapa no reemplaza al graph store.

La asignación del grafo se registra explícitamente:

```text
user_graphs
- user_id UUID PRIMARY KEY
- arcade_instance_key TEXT NOT NULL
- database_name TEXT NOT NULL UNIQUE
- graph_username TEXT NOT NULL UNIQUE
- graph_secret_ciphertext TEXT NOT NULL
- status: pending | provisioning | active | failed | suspended
- schema_version TEXT
- created_at
- updated_at
- provisioned_at
- last_error_code
- last_error
```

`arcade_instance_key` es un identificador lógico resuelto por configuración del backend. Permite
distribuir usuarios entre instancias de ArcadeDB en el futuro sin guardar URLs en la tabla ni
cambiar el contrato de la aplicación.

Los nombres son opacos, generados por el backend y nunca derivados del email ni proporcionados por
el frontend. La contraseña técnica de ArcadeDB es aleatoria, diferente de la contraseña de login y
se almacena cifrada o mediante una referencia a un secret store.

## Aislamiento del grafo

### Decisión

Cada usuario tiene una base ArcadeDB independiente. El adaptador obtiene el destino a partir de
`user_graphs` y abre allí la sesión. El nombre nunca se interpola desde datos del request.

Una base por usuario reduce considerablemente el riesgo de una consulta Cypher sin filtro, pero no
protege contra una aplicación completamente comprometida ni contra consumo excesivo de recursos en
la JVM compartida. Por eso cada workspace también tiene un principal técnico de ArcadeDB con acceso
exclusivo a su base y permisos CRUD, sin permisos para modificar schema o seguridad.

La cuenta `root` se reserva para aprovisionamiento, migraciones de schema y tareas administrativas.
No se utiliza en el camino normal de una petición HTTP.

ArcadeDB satisface esta arquitectura porque:

- Está licenciado íntegramente bajo Apache 2.0.
- Un mismo proceso puede alojar múltiples bases independientes.
- Su modelo de usuarios asigna grupos y permisos por base.
- Tiene motor de grafo, índices vectoriales persistentes y búsqueda aproximada nativa.
- Expone una variante compatible de `db.index.vector.queryNodes()`.
- El adaptador HTTP, el schema y las consultas necesarias ya están implementados en el proyecto.

Referencias:

- [ArcadeDB: licencia y capacidades](https://github.com/ArcadeData/arcadedb)
- [ArcadeDB: múltiples bases](https://docs.arcadedb.com/arcadedb/concepts/databases)
- [ArcadeDB: seguridad por base](https://docs.arcadedb.com/arcadedb/how-to/operations/users)
- [ArcadeDB: búsqueda vectorial](https://docs.arcadedb.com/arcadedb/concepts/vector-search)
- [ArcadeDB: driver Python HTTP](https://docs.arcadedb.com/arcadedb/how-to/connectivity/drivers/python-http)

## Aprovisionamiento inicial

El alta mantiene una secuencia corta e idempotente:

1. FastAPI Users crea el usuario en PostgreSQL.
2. Se crea `user_graphs` con estado `pending`, nombres reservados y credencial cifrada.
3. El provisionador cambia el estado a `provisioning`.
4. Crea o verifica la base ArcadeDB.
5. Aplica el schema e índices de la versión vigente con una credencial administrativa.
6. Crea o reconcilia el principal técnico limitado a esa base.
7. Verifica acceso a la base propia y rechazo de acceso a otra base.
8. La asignación pasa a `active`; ante error pasa a `failed` y puede reintentarse.
9. Mientras no esté activa, la aplicación muestra que el espacio personal se está preparando.

Para la primera versión no se incorpora un motor de workflows ni una cola obligatoria. El
provisionador puede ser un servicio de aplicación idempotente invocado después del registro y por un
comando administrativo de reintento. Las operaciones son reconciliables: `ensure_database`,
`ensure_schema`, `ensure_runtime_principal`, `verify_isolation` y `mark_active`.

PostgreSQL es la fuente de verdad. Los usuarios y permisos técnicos de ArcadeDB se reconcilian desde
`user_graphs` al iniciar el servicio o mediante un comando administrativo. Esto evita depender de la
persistencia del archivo interno `config/server-users.jsonl` de ArcadeDB.

### Desaprovisionamiento

Queda únicamente el siguiente placeholder:

```text
TODO: definir retención, exportación y eliminación de la base/grafo cuando se elimina una cuenta.
```

Desactivar un usuario sólo bloquea el acceso. No se elimina automáticamente su base, archivos ni
historial en esta etapa.

## Aislamiento fuera del graph store

Aunque el grafo sea una base independiente, también se requiere:

- Directorios u object keys bajo `users/<user_id>/...` para documentos y audio.
- Stores construidos con un directorio ya limitado al usuario. Sus métodos no necesitan recibir
  `user_id` si la frontera se establece al crearlos.
- Extracciones y reflexiones asociadas al mismo usuario que el documento origen.
- Base IndexedDB separada por usuario, abierta después de resolver la sesión.
- Al cambiar de cuenta, cerrar el contexto offline anterior antes de sincronizar.
- No transferir automáticamente notas offline entre usuarios que compartan navegador.

## Plan por etapas

1. **Módulo de usuarios:** PostgreSQL, Alembic y FastAPI Users encapsulado en
   `src/user_management`.
2. **Contrato de sesión:** `AuthenticatedUser`, `GET /auth/session` y redirección de la PWA ante
   `401`.
3. **Workspaces:** tabla `user_graphs`, `UserWorkspace` y provisionador idempotente de bases y
   principales restringidos.
4. **Backend aislado:** construcción de graph store y file stores por workspace; propagación segura
   del contexto a procesos en background.
5. **PWA aislada:** sesión con `user_id`, Dexie por usuario, cierre del contexto anterior y manejo
   global de `401`.
6. **Google:** login OAuth y asociación explícita con una cuenta autenticada.
7. **Validación multiusuario:** matriz negativa completa con dos usuarios y recursos cruzados.

No se incluye una etapa de migración: la implementación multiusuario comienza desde cero y no hay
datos existentes que deban reasignarse.

## Validaciones obligatorias

- Un usuario nunca obtiene documentos, claims, embeddings o reflexiones del otro.
- Un `document_id` ajeno devuelve `404` para lectura, reproceso y borrado.
- El polling de un audio ajeno devuelve `404`.
- Los trabajos en background conservan el `user_id` original.
- Una búsqueda vectorial sólo consulta la base asignada por `UserGraphLocator`.
- Alterar IDs, parámetros HTTP o metadata no cambia la base seleccionada.
- Logout invalida la sesión persistida.
- Ante sesión inválida, API `401` y PWA redirige al login.
- Una cuenta Google no se asocia por coincidencia de email sin autenticación explícita.
- La credencial técnica del usuario A no puede abrir la base ArcadeDB del usuario B.

## TODO posteriores

- Definir backups coordinados de PostgreSQL, cada base ArcadeDB y los archivos por usuario.
- Probar restauración completa de un único usuario.
- Definir métricas y alertas para cantidad de bases, disco, heap y tiempos de apertura.
- Ejecutar pruebas de capacidad antes de fijar un máximo de usuarios por instancia.
- Definir retención, exportación y eliminación de datos al borrar una cuenta.

Estos puntos quedan registrados, pero no forman parte de las primeras etapas de implementación.

## Decisiones pendientes

- Registro público, por invitación o inicialmente cerrado.
- Proveedor de email para verificación y recuperación de contraseña.
- TTL y política de revocación de sesiones.
- Política de datos offline al cerrar sesión en un dispositivo compartido.
