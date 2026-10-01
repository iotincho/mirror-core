# Requisitos multiusuario

<<<<<<< Updated upstream
Estado: borrador de arquitectura  
Fecha: 2026-09-29
=======
Estado: etapas 1 a 6 implementadas; validación multiusuario final pendiente
Fecha: 2026-09-30
>>>>>>> Stashed changes

Este documento registra las definiciones acordadas y las decisiones pendientes para convertir El
Espejo en una aplicación multiusuario. No describe una implementación terminada.

## Objetivos

- Permitir registro e inicio de sesión local.
- Permitir inicio de sesión y asociación de cuenta con proveedores externos, inicialmente Google.
- Evitar implementar desde cero los flujos genéricos de gestión de usuarios.
- Mantener la gestión de identidad encapsulada para poder reemplazar FastAPI Users por otro
  proveedor o tecnología en el futuro.
- Aislar documentos, audios, extracciones, reflexiones, embeddings y grafo entre usuarios.
- Mantener Neo4j y el modelo de grafo actuales mientras se evalúan alternativas; no migrar el
  contenido del grafo como parte de la primera etapa multiusuario.

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

<<<<<<< Updated upstream
=======
Implementado en las etapas 1, 2 y 6: usuarios UUID en PostgreSQL, migraciones Alembic, cookie
revocable, login/registro/logout local, `GET /auth/session` y Google OAuth opcional. Google sólo se
habilita al configurar `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` y
`GOOGLE_OAUTH_REDIRECT_URL`. El callback es una ruta pública de la PWA; ésta reenvía el `code` y el
`state` al callback de la API para que FastAPI Users valide el flujo y cree la cookie de sesión.

>>>>>>> Stashed changes
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
- engine TEXT NOT NULL
- database_name TEXT NOT NULL
- status: pending | provisioning | active | failed | suspended
- schema_version TEXT
- created_at
- provisioned_at
- last_error
- UNIQUE(engine, database_name)
```

`engine` permite conservar Neo4j para usuarios existentes y probar otro proveedor con usuarios de
prueba sin cambiar el contrato de la aplicación.

Ejemplos:

```text
usuario legado -> engine=neo4j,   database_name=neo4j
usuario prueba -> engine=arcadedb, database_name=usr_8f1a44ca...
```

Los nombres son opacos, generados por el backend y nunca derivados del email ni proporcionados por
el frontend.

## Aislamiento del grafo

### Requisito preferido

Cada usuario debe tener una base o grafo lógico independiente. El adaptador obtiene el destino a
partir de `user_graphs` y abre allí la sesión. El nombre nunca se interpola desde datos del request.

Una base por usuario reduce considerablemente el riesgo de una consulta Cypher sin filtro, pero no
<<<<<<< Updated upstream
protege contra una aplicación comprometida que utilice una credencial administrativa con acceso a
todas las bases. Deben mantenerse credenciales de servicio con el menor privilegio posible y probar
el `UserGraphLocator` como una frontera de seguridad.
=======
protege contra una aplicación completamente comprometida ni contra consumo excesivo de recursos en
la JVM compartida. Por eso cada workspace también tiene un principal técnico de ArcadeDB con acceso
exclusivo a su base, permisos CRUD y `updateSchema`. Este último es necesario para los `MERGE`
parametrizados del writer bajo ArcadeDB 26.9.1; no concede acceso a otras bases ni permisos de
seguridad.
>>>>>>> Stashed changes

### Opciones evaluadas

| Motor | Licencia/edición relevante | Separación abierta por usuario | Cypher y vectores | Evaluación inicial |
| --- | --- | --- | --- | --- |
| Neo4j Community | Community, una base estándar | No dentro de un mismo DBMS | Compatibilidad actual completa | No satisface DB por usuario |
| Neo4j Enterprise | Comercial | Sí, múltiples bases | Compatibilidad actual completa | Menor cambio, sujeto a licencia y costo |
| ArcadeDB | Apache 2.0 | Sí, múltiples bases independientes por proceso | OpenCypher y vector index nativos | Candidato abierto principal; requiere spike de compatibilidad |
| Apache AGE | Apache 2.0 | PostgreSQL permite múltiples graphs y databases | OpenCypher; vectores mediante PostgreSQL/pgvector | Muy abierto, pero implica una migración mayor del adaptador y del modelo |
| FalkorDB | SSPLv1 | Sí, múltiples grafos nombrados | Cypher y vectores nativos | Técnicamente atractivo, pero SSPL no ofrece la libertad buscada para un servicio |
| Memgraph Community | Business Source License | Multi-database es Enterprise | Cypher y vectores | No mejora la restricción principal de Neo4j Community |
| ArangoDB Community | Community License / BSL | Sí, con restricciones de licencia y uso | AQL, multi-modelo y vectores | Se descarta como alternativa abierta permisiva |
| JanusGraph | Apache 2.0 | Posible con instancias/configuraciones separadas | Gremlin; índices externos | Demasiada complejidad y migración para el tamaño actual |

### ArcadeDB

ArcadeDB merece la primera prueba técnica porque:

- Está licenciado íntegramente bajo Apache 2.0.
- Un mismo proceso puede alojar múltiples bases independientes.
- Su modelo de usuarios asigna grupos y permisos por base.
- Tiene motor de grafo, índices vectoriales persistentes y búsqueda aproximada nativa.
- Expone una variante compatible de `db.index.vector.queryNodes()`.
- Tiene un driver HTTP async para Python y también expone Bolt.
- Su implementación OpenCypher nativa declara 97,8 % de aprobación sobre el TCK de OpenCypher.

Riesgos que impiden adoptarlo sin prueba:

- El motor OpenCypher nativo es reciente.
- Compatibilidad sintáctica no garantiza igualdad de semántica, planes, score vectorial ni tipos
  devueltos por el driver.
- Las consultas y procedimientos específicos de Neo4j deben verificarse uno por uno.
- Deben medirse el costo por base, los backups y el comportamiento con muchas bases pequeñas.

Referencias:

- [ArcadeDB: licencia y capacidades](https://github.com/ArcadeData/arcadedb)
- [ArcadeDB: múltiples bases](https://docs.arcadedb.com/arcadedb/concepts/databases)
- [ArcadeDB: seguridad por base](https://docs.arcadedb.com/arcadedb/how-to/operations/users)
- [ArcadeDB: matriz de compatibilidad Cypher](https://docs.arcadedb.com/arcadedb/reference/cypher/cypher-compatibility)
- [ArcadeDB: búsqueda vectorial](https://docs.arcadedb.com/arcadedb/concepts/vector-search)
- [ArcadeDB: driver Python HTTP](https://docs.arcadedb.com/arcadedb/how-to/connectivity/drivers/python-http)

### Spike requerido para decidir el graph store

El spike debe ejecutarse sin migrar ni retirar Neo4j:

1. Levantar una versión fija de ArcadeDB en un entorno experimental.
2. Crear al menos dos bases con usuarios/permisos restringidos a una sola base.
3. Implementar un adaptador experimental detrás de los ports existentes, sin modificar los casos de
   uso.
4. Probar las consultas actuales de:
   - persistencia de documentos y extracciones;
   - conceptos, entidades, claims, evidencias y relaciones;
   - embeddings de documentos y claims;
   - búsqueda vectorial;
   - recuperación de relaciones para reflexión;
   - borrado en cascada de un documento.
5. Comparar IDs, metadatos, orden y score de resultados con Neo4j.
6. Probar primero Bolt para estimar cuánto puede reutilizarse; usar el driver HTTP oficial si Bolt
   introduce incompatibilidades o limita operaciones administrativas.
7. Crear 100 bases vacías con su esquema e índices y medir tiempo, memoria, disco y reinicio.
8. Verificar backup y restauración de una única base sin afectar a las demás.
9. Probar que una credencial restringida a la base A no puede consultar la base B.

Criterio de decisión:

- ArcadeDB pasa a ser el graph store preferido si conserva el comportamiento funcional actual,
  permite aislamiento efectivo por base en la distribución Apache 2.0 y presenta un costo operativo
  aceptable.
- Neo4j continúa siendo la opción si la compatibilidad o estabilidad no son suficientes; para DB por
  usuario deberá evaluarse Enterprise.
- Un grafo compartido con `user_id` queda como fallback, no como diseño preferido.

## Aprovisionamiento inicial

El alta mantiene una secuencia corta e idempotente:

1. FastAPI Users crea el usuario en PostgreSQL.
2. Se crea `user_graphs` con estado `pending`.
3. El provisionador crea la base y aplica el esquema e índices de la versión vigente.
4. La asignación pasa a `active`; ante error pasa a `failed` y puede reintentarse.
5. Mientras no esté activa, la aplicación muestra que el espacio personal se está preparando.

Para la primera versión no se incorpora un motor de workflows ni una cola obligatoria. El
provisionador puede ser un servicio de aplicación idempotente invocado después del registro y por un
comando administrativo de reintento.

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
- Stores cuyo `get`, `list`, `save` y `delete` requieran `user_id`.
- Extracciones y reflexiones asociadas al mismo usuario que el documento origen.
- Base IndexedDB separada por usuario o tablas con propietario e índices compuestos.
- Al cambiar de cuenta, cerrar el contexto offline anterior antes de sincronizar.
- No transferir automáticamente notas offline entre usuarios que compartan navegador.

## Plan por etapas

1. **Prueba de arquitectura:** spike ArcadeDB y comparación con Neo4j Enterprise.
2. **Módulo de usuarios:** PostgreSQL, Alembic y FastAPI Users encapsulado en
   `src/user_management`.
<<<<<<< Updated upstream
3. **Contrato de sesión:** `AuthenticatedUser`, `GET /auth/session` y redirección de la PWA ante
   `401`.
4. **Registro de recursos:** tabla `user_graphs` y asignación de la base actual al usuario legado.
5. **Graph routing:** `UserGraphLocator` y adaptación del store para seleccionar una base de forma
   explícita.
6. **Aislamiento restante:** archivos, audios, procesos en background e IndexedDB.
7. **Google:** login OAuth y asociación explícita con una cuenta autenticada.
8. **Validación multiusuario:** matriz negativa completa con dos usuarios y recursos cruzados.
=======
2. **Contrato de sesión (implementada):** `AuthenticatedUser`, `GET /auth/session` y retorno de
   la PWA al login cuando la sesión inicial es inválida.
3. **Workspaces (implementada):** tabla `user_graphs`, `UserWorkspace` y provisionador idempotente
   de bases y principales restringidos. El registro crea el usuario y solicita el aprovisionamiento;
   un fallo queda en estado `failed` y no invalida la cuenta.
4. **Backend aislado (implementada):** cada request resuelve su `UserWorkspace` activo desde la
   sesión; construye graph, documentos, audio, extracciones y reflexiones bajo
   `WORKSPACES_PATH/<user_id>/`. Los procesos de background conservan el store ya limitado al
   usuario que los originó. Una transcripción de audio crea un documento `pwa_audio` con ID estable
   y conserva su vínculo para reintentos. El backend no usa el grafo ni directorios globales en
   rutas protegidas.
5. **PWA aislada (implementada):** sesión con `user_id`, una base Dexie por usuario
   (`el_espejo_user_<user_id>`), cierre del contexto anterior al perder o cambiar sesión y manejo
   global de `401` para las APIs protegidas. No se reutiliza ni se migra la base Dexie global previa
   entre cuentas.
6. **Google (implementada):** login OAuth opcional y asociación explícita con una cuenta
   autenticada. La PWA inicia `/auth/google/authorize` o `/auth/associate/google/authorize`, y usa
   su callback público `/oauth/google/callback` para completar el flujo contra la API. Se mantienen
   cookies CSRF distintas para login y asociación. `associate_by_email=False` impide vincular una
   cuenta local por coincidencia de email; una cuenta externa nueva crea su propio usuario y su
   workspace mediante el hook de registro existente.
7. **Validación multiusuario:** matriz negativa completa con dos usuarios y recursos cruzados.

No se incluye una etapa de migración: la implementación multiusuario comienza desde cero y no hay
datos existentes que deban reasignarse.
>>>>>>> Stashed changes

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
- La base existente conserva su comportamiento para el usuario legado.

## Decisiones pendientes

- Neo4j Enterprise o ArcadeDB como graph store definitivo.
- Registro público, por invitación o inicialmente cerrado.
- Proveedor de email para verificación y recuperación de contraseña.
- TTL y política de revocación de sesiones.
- Política de datos offline al cerrar sesión en un dispositivo compartido.
- Cantidad objetivo de usuarios y bases para dimensionar el spike.
- Política de exportación, retención y eliminación de cuentas; fuera del alcance inicial.
