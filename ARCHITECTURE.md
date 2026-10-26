# Arquitectura del backend

Estado al 2026-10-26: arquitectura objetivo acordada; etapas 0–5 completadas.
Documentos, audio, extractores de títulos/emociones/embeddings, grafo, respaldos,
procesamiento durable, identidad, recuperación, workspaces, invitaciones,
notificaciones y administración migrados, con enlaces
explícitos a áreas pendientes.
El resto del código todavía no cumple todas estas fronteras.
El [mapa del repositorio](docs/development/repository-map.md)
describe el árbol existente; el [plan de migración](docs/development/hexagonal-migration-plan.md)
define cómo llegar a esta organización sin cambiar el comportamiento del producto.

Este documento es la referencia de responsabilidades, dependencias y crecimiento
del backend. [AGENTS.md](AGENTS.md) contiene instrucciones de trabajo; los contratos
de cada funcionalidad están en el [índice](docs/README.md).

## Modelo hexagonal

El interior del hexágono comprende **core y casos de uso**. Los adaptadores quedan
fuera: traducen tecnologías concretas al lenguaje de la aplicación. Bootstrap
construye y conecta los componentes al iniciar cada proceso.

![Modelo hexagonal: acceso, aplicación, puertos, adaptadores y composición](docs/assets/hexagonal-architecture.png)

[Ampliar PNG](docs/assets/hexagonal-architecture.png) ·
[SVG editable](docs/assets/hexagonal-architecture.svg) ·
[Generador](scripts/render_architecture_diagram.py)

Las flechas sólidas muestran llamadas en ejecución; las líneas discontinuas,
composición. La franja inferior indica las dependencias de código, que apuntan
hacia el interior. Los puertos de salida están dentro de `core`.

Para regenerar las dos imágenes: `python3 scripts/render_architecture_diagram.py`.
La herramienta documental usa Pillow y una fuente Noto Sans o DejaVu Sans; no
importa la aplicación ni necesita servicios o acceso a la red.

La llamada en ejecución atraviesa el puerto hacia el adaptador de salida, pero
la aplicación no importa ese adaptador: depende del contrato y recibe una
implementación. Esa inversión de dependencia es la frontera esencial.
El hexágono no representa seis módulos, seis capas ni un número de servicios.
Seguimos teniendo un backend con varios procesos, no una propuesta de microservicios.

Un puerto de entrada puede ser el método público de un caso de uso con su comando
y resultado tipados; no exige una interfaz adicional por cada endpoint. Un puerto
de salida describe una necesidad de la aplicación, por ejemplo guardar un original,
obtener un artefacto o aceptar un trabajo durable. Un cliente HTTP o una sesión SQL
no constituyen ese contrato.

## Estructura objetivo

```text
src/                              # Backend; estructura objetivo tras la migración
├── core/                         # Modelos, reglas y contratos internos
│   ├── domain/                   # Document, AudioNote y valores compartidos
│   ├── documents/                # Reglas y puertos propios de documentos
│   ├── audio/                    # Originales, preparación y puerto de transcripción
│   ├── graph/                    # Contratos de navegación y proyecciones de lectura
│   ├── processing/               # Estados, transiciones y contratos durables
│   ├── extractors/               # Perfiles, resultados, evidencia y puertos
│   ├── notifications/            # Vigencia y reglas del centro de notificaciones
│   ├── workspaces/               # Identidad, alcance y disponibilidad del espacio
│   ├── auth/                     # Identidad, contraseñas, sesiones y recuperación
│   ├── exteriorization/          # Invitaciones, horarios y consentimiento
│   └── administration/           # Contratos de inventario, métricas y permisos
├── use_cases/                    # Acciones de aplicación y coordinación por puertos
│   ├── documents/                # Aceptar, consultar, borrar y respaldar notas
│   ├── audio/                    # Aceptar audio y obtener su documento derivado
│   ├── processing/               # Coordinar jobs, checkpoints, retry y reprocess
│   ├── extraction/               # Ejecutar extractores y recuperar persistencia
│   ├── graph/                    # Consultar proyecciones y verificar originales
│   ├── notifications/            # Consultar y marcar notificaciones leídas
│   ├── workspaces/               # Preparar, resolver y reconciliar espacios
│   ├── auth/                     # Login, recuperación y revocación de sesiones
│   ├── exteriorization/          # Configurar, programar y enviar invitaciones
│   └── administration/           # Consultar inventario y administrar permisos
├── adapters/                     # Entrada/salida y tecnologías concretas
│   ├── access/                   # Traducir entradas externas a casos de uso
│   │   ├── api/                  # HTTP: rutas, schemas y traducción de errores
│   │   │   ├── public/           # Endpoints de la aplicación pública
│   │   │   └── administration/   # Endpoints exclusivos del proceso admin
│   │   ├── cli/                  # Comandos operativos y de mantenimiento
│   │   └── workers/              # Recibir entregas Taskiq y gestionar ACK
│   ├── storage/                  # Implementar persistencia por capacidad
│   │   ├── arcadedb/             # Esquemas, consultas y proyecciones del grafo
│   │   ├── postgres/             # ORM, transacciones, leases, locks y outbox
│   │   └── filesystem/           # Originales, artefactos y archivos durables
│   ├── providers/                # Integraciones con servicios externos
│   │   ├── openai/               # Extracción, embeddings y transcripción
│   │   ├── email/                # Entrega de correo y traducción de fallos
│   │   ├── security/             # Cifrado y protección de credenciales técnicas
│   │   └── web_push/             # Envíos push y respuestas del proveedor
│   └── messaging/                # Transporte de mensajes de procesamiento
│       └── rabbitmq/             # Publicación, cola y confirmación del broker
└── bootstrap/                    # Construir, conectar y cerrar componentes
    ├── settings.py               # Leer y validar configuración del entorno
    ├── dependencies.py           # Ensamblar casos de uso y adaptadores
    ├── public_api.py             # Componer la aplicación HTTP pública
    ├── admin_api.py              # Componer la aplicación HTTP administrativa
    └── worker.py                 # Componer el worker y sus recursos
```

Es un esquema de ubicación, no una orden de crear carpetas vacías. Cada área
crece cuando existe una responsabilidad concreta. Dentro de un adaptador técnico
se agrupa por capacidad: por ejemplo `storage/arcadedb/extractors/emotions.py`.
Tener varios repositorios de una tecnología no implica un único store universal.

## Responsabilidad de cada capa

| Capa | Responsabilidad | Ejemplos | Fuera de su responsabilidad |
| --- | --- | --- | --- |
| `core/domain` | Entidades y valores compartidos con una definición canónica | Documento, audio original e identidad de recurso | Modelos ORM, request/response HTTP, rutas de archivos de un adaptador |
| `core/<área>` | Modelos específicos, reglas, políticas, errores semánticos y puertos | Evidencia válida, configuración aceptada, transiciones de trabajo, contratos de almacenamiento | SQL/Cypher, DDL, SDKs, variables de entorno, publicación RabbitMQ |
| `use_cases/<área>` | Ejecutar una acción, autorizarla y coordinar operaciones por puertos | Aceptar nota, reintentar procesamiento, recuperar contraseña, programar invitación | Detalles HTTP, sesiones/modelos ORM, construcción de clientes, settings globales |
| `adapters/access` | Traducir entrada externa y resultado del caso de uso | Cookies, schemas HTTP, UUID del mensaje, parámetros CLI, códigos HTTP, ACK | Decisiones de negocio o consultas SQL de la funcionalidad |
| `adapters/storage` | Implementar persistencia y consultas por capacidad | ORM, transacciones SQL, consultas ArcadeDB, publicación durable de archivos | Elegir la política del producto o reinterpretar la configuración aceptada |
| `adapters/providers` | Traducir llamadas y respuestas de servicios externos | OpenAI, correo y Web Push; normalización de errores del proveedor | Decidir qué trabajo aceptar o qué usuario tiene permiso |
| `adapters/messaging` | Implementar publicación y transporte | Exchange/cola, publisher confirms y envío del mensaje | Decidir reintentos de negocio o convertir el broker en autoridad del estado |
| `bootstrap` | Configurar y ensamblar cada proceso | Settings del entorno, factories, registros, lifespans y cierre de clientes | Reglas de negocio, SQL de funcionalidades o implementación de sus recorridos |

El dominio específico de un área permanece en ella. `core/domain` se reserva para
conceptos realmente compartidos; no se replica Document en cada módulo. Pydantic
es admisible para tipos y validación interna. Sus modelos internos no adquieren
por ello dependencia de FastAPI ni se exponen automáticamente como contrato HTTP.

Los schemas HTTP están en acceso; los modelos ORM, en storage. Los casos de uso
operan con comandos/resultados propios o tipos del núcleo y traducen entre ellos
sin depender de esos schemas ni de objetos ORM ligados a una sesión.

## Reglas de dependencia

| Origen | Puede depender de | No puede depender de |
| --- | --- | --- |
| `core` | Biblioteca estándar, validación y contratos internos explícitos de core | `use_cases`, `adapters`, `bootstrap`, FastAPI, SQLAlchemy, Taskiq, SDKs e implementaciones de I/O |
| `use_cases` | `core` y colaboradores de aplicación explícitos, sin ciclos | Adaptadores, bootstrap, SQL/Cypher, clientes concretos, sesiones ORM o lectura global del entorno |
| Acceso | Casos de uso, tipos de core y su framework de entrada | Implementaciones de storage/proveedores para resolver directamente la funcionalidad |
| Salida | Puertos/tipos de core, su tecnología y utilidades técnicas de su adaptador | Casos de uso, rutas y bootstrap; modelos privados de otra persistencia |
| `bootstrap` | Las capas y tecnologías necesarias para componer | No recibe dependencias desde las capas interiores |

Las dependencias entre áreas son explícitas y sin ciclos. Una acción que afecta
varias capacidades se coordina en aplicación; no se resuelve importando el modelo
SQL privado de otra área. Si se necesita compartir una transacción, se expresa
mediante el contrato transaccional y su implementación común.

La inyección de HTTP/workers se conecta desde bootstrap. Un router no importa
factories de bootstrap para construir su persistencia; recibe el caso de uso o un
resolvedor ya conectado. Los entrypoints son parte de la composición externa.

Los puertos pueden organizarse como `core/<área>/ports.py` o `ports/` según tamaño.
Expresan operaciones semánticas, no `execute_sql`, `get_session` o acceso al cliente
del grafo. Tampoco se pasan implementaciones dentro de diccionarios/contextos para
eludir estas reglas. Los adaptadores traducen fallos técnicos a errores del contrato;
acceso traduce esos errores al protocolo externo.

## Separaciones relevantes para este backend

### Extracción y persistencia

El núcleo define perfil, resultado, evidencia y validez de una extracción. Los
casos de uso coordinan leer el documento, invocar al proveedor, guardar un artefacto
y persistirlo. Los adaptadores implementan cada I/O. La recuperación de persistencia
lee el artefacto y no vuelve a invocar al modelo.

Cada extractor sigue siendo dueño lógico de su capa: su adaptador administra su
esquema y reemplaza atómicamente sólo su proyección. No se concentra SQL de todas
las capas dentro de un store genérico. Los constructores se registran en bootstrap;
el ejecutor común no añade condicionales por cada extractor nuevo.

Un eje definido por el usuario es compatible con este contrato. Sus acciones de
definir, probar y aceptar versiones pertenecen a aplicación; sus reglas y tipos,
al núcleo de extracción, y HTTP/ORM/proveedores a sus adaptadores. El alcance
actual pospone su reorganización interna, manteniendo compatibilidad y reglas de
versionado/evidencia sin decidir que deba ser un módulo independiente.

### Procesamiento durable y transacciones

Core define estados, transiciones, identidad, checkpoints y contratos de ejecución.
La aplicación decide aceptación, coordinación padre/hijos, retry y reprocess.
PostgreSQL implementa estado durable, leases, locks y outbox. Taskiq/RabbitMQ
transportan entregas; no agregan otra política de reintentos.

La unidad de trabajo SQL debe confirmar recibo, job, evento y outbox juntos cuando
lo requiere el contrato. Separar repositorios no habilita commits independientes
ni expone `AsyncSession` a la aplicación. Los registros del caso de uso son tipos
de aplicación/core, no modelos ORM retornados fuera de la transacción.

El original y el vértice base se conservan antes de confirmar una aceptación de
documento. Archivos, PostgreSQL y ArcadeDB no comparten transacción: se mantienen
operaciones idempotentes, respaldos y checkpoints. Retry retoma identidad/configuración;
reprocess crea una ejecución nueva. El refactor no modifica estas garantías.

### Identidad, workspaces y procesos

Acceso autentica con el mecanismo del canal y entrega una identidad verificada.
El caso de uso comprueba autorización, propietario y disponibilidad del workspace;
un UUID arbitrario del cliente no elige el almacenamiento. Los adaptadores reciben
el alcance ya resuelto y bootstrap construye clientes acotados y gestiona su cierre.

La API pública y administrativa se ensamblan por separado. Compartir núcleo y
casos de uso no registra automáticamente rutas administrativas en el proceso público.
Las observaciones técnicas se correlacionan sin volcar notas, audio o credenciales.

## Criterios para agregar módulos y funcionalidades

Un módulo es una capacidad con propósito, vocabulario y responsabilidades propias;
no es necesariamente una nueva carpeta en cada capa ni un servicio desplegable.
Antes de añadir uno, comprobar si la responsabilidad ya tiene un dueño.

Crear una nueva área de core cuando tenga reglas/modelos propios y un ciclo de
vida o frontera que pueda explicarse y probarse de forma independiente. Un endpoint
nuevo, otra tabla, otra tecnología o un archivo largo no bastan por sí solos.
Extender el área existente cuando se mantiene el mismo propósito e invariantes.

Para cada funcionalidad nueva:

1. **Definir el resultado y el dueño.** Explicar qué acción o regla agrega, qué
   conceptos usa y qué capacidades existentes consume. No duplicar modelos canónicos.
2. **Ubicar la regla.** Una invariante va a `core/<área>`; la coordinación de una
   acción va a `use_cases/<área>`. Una consulta sin regla adicional no requiere
   crear artificialmente una entidad o un agregado.
3. **Definir sólo los puertos necesarios.** Si necesita I/O, nombrar la operación
   de aplicación y sus tipos/errores. Reutilizar contratos compatibles; no crear
   una interfaz por cada función privada ni repositorios CRUD universales.
4. **Agregar adaptadores donde corresponda.** Rutas y schemas en acceso; SQL,
   grafo y archivos en storage; SDKs en providers. Organizar cada tecnología por
   área. Una integración nueva no crea automáticamente otro dominio.
5. **Componer explícitamente.** Conectar el caso de uso, implementaciones y recursos
   en bootstrap. Si es otro extractor, registrarlo por el contrato común sin
   acoplar el coordinador a su nombre o payload.
6. **Revisar dependencias y recuperación.** No introducir ciclos, imports privados
   de infraestructura ni pérdida de atomicidad. Definir ownership, idempotencia y
   recuperación de efectos parciales cuando existan.
7. **Probar y documentar.** Reglas/casos de uso con puertos falsos; adaptadores con
   sus tecnologías y contratos de entrada. Actualizar el contrato funcional y el
   mapa. Si cambia una frontera arquitectónica, actualizar este documento.

Ejemplos: otra ruta de lectura de documentos amplía el área existente; un nuevo
proveedor de transcripción implementa su puerto; un extractor de temas aporta sus
reglas/tipos y adaptadores bajo extracción. Ninguno necesita un `utils` o `services`
global donde mezclar responsabilidades sin dueño.

## Comprobación y transición

La etapa 0 incorpora [controles de imports](docs/development/architecture-checks.md)
para núcleo, aplicación y adaptadores, con excepciones heredadas por archivo/import.
También impide agregar ubicaciones nuevas fuera del árbol objetivo. Los módulos
heredados sin migrar no se declaran limpios; su inventario y compatibilidad siguen
el plan. El chequeo documental es independiente de este control de código.

Un recorrido cumple esta arquitectura cuando puede ejecutar su caso de uso con
puertos falsos sin iniciar FastAPI, ORM, broker o proveedor real; las pruebas de
adaptadores e integración comprueban después la infraestructura y la atomicidad.
Una prueba con mocks no acredita locks o transacciones de motores reales.

El piloto ubica originales y puertos en `core/domain`, `core/documents` y
`core/extractors`; los casos en `use_cases/documents` y `use_cases/extraction`;
persistencia en `adapters/storage/{filesystem,arcadedb}` y el proveedor de títulos
en `adapters/providers/openai`. `bootstrap/documents.py` conecta esos componentes.
`TitleReadPolicy` entrega configuración sin credenciales a la aplicación.
`TitleScheduling` aísla la aceptación durable: `BackfillDocumentTitles` usa ahora
el puerto transaccional de procesamiento, sin SQL en el caso de uso.

Procesamiento separa `ProcessingJob`, `SubmissionReceipt` y `OutboxDelivery` de sus
modelos ORM. `ProcessingTransaction` expresa operaciones de recibos, trabajos,
eventos y outbox en una misma transacción; sólo el adaptador conoce la sesión.
`ExecutionStore` conserva leases, fencing, checkpoints y coordinación padre/hijos.
Los adaptadores entregan copias independientes y traducen fallos SQL a
`StorageUnavailable`: la aplicación deja el lease sin resolver y el transporte
mantiene el mensaje sin ACK. El acceso HTTP conserva su respuesta 503.

Los casos durables viven en `use_cases/processing`; PostgreSQL en
`adapters/storage/postgres`; recepción Taskiq en `adapters/access/workers` y
construcción del broker RabbitMQ en `adapters/messaging/rabbitmq`. Bootstrap conecta
registro, configuración aceptada, recursos y limpieza del dispatcher/worker.
Las rutas HTTP y el workspace actuales siguen siendo entrypoints; los módulos
anteriores delegan, sin duplicar algoritmos.

Emociones separa evidencia/perfiles en core, coordinación en aplicación y reemplazo
atómico en `adapters/storage/arcadedb/emotions.py`. Embeddings recibe su contador de
tokens como dependencia; tiktoken y OpenAI quedan en adaptadores. Cada capa sigue
siendo dueña de sus artefactos y de la sustitución de su proyección.

Audio usa `AudioNoteStore`, `TranscriptionSource` y `TranscriptionProvider`:
la aplicación conserva checkpoints y deriva documentos sin manejar paths ni SDK.
El adaptador filesystem prepara el upload y limpia temporales; el proveedor gestiona
su cliente y concurrencia. La composición conecta estos puertos sin dependencias
directas entre los adaptadores de archivos y OpenAI. Los hashes históricos no cambian.

`ReadGraph` verifica originales y coordina las lecturas; los contratos viven en
`core/graph` y las consultas/proyecciones en el adaptador ArcadeDB. Respaldos y
borrado usan puertos de originales, proyección y procesamiento transaccional.
`FailureFacts` separa hechos técnicos normalizados en el adaptador de la política
de errores/retry del núcleo. Bootstrap conecta esas responsabilidades por capacidad.

Ejes mantiene dos puentes explícitos en bootstrap: preparación/orden de escritura
y clasificación de fallos privados para el extractor; contexto SQL sólo para sus
workflows experimentales de preview/histórico. El procesador genérico no conoce
el nombre de ejes ni accede a sesiones. La revocación de sesiones e invitaciones
comparte la transacción PostgreSQL sin importar módulos de aplicación desde storage.
Los consumidores HTTP y comandos
heredados conservan constructores/imports compatibles hasta su consolidación;
los casos canónicos no reciben ORM ni leen configuración global.

Identidad y recuperación usan tipos independientes en `core/auth` y acciones en
`use_cases/auth`. FastAPI Users adapta cookies, registro y OAuth en acceso público;
bootstrap conecta el proveedor de hashing y el store de cuentas. La autenticación
conserva el lock compartido con reset y la versión de sesión, incluso al rehashear.
La transacción de recuperación aplica presupuestos, desafío, contraseña, revocación
y outbox juntos; sólo el adaptador conoce sus modelos SQL. Los errores del núcleo
contienen códigos y esperas; acceso decide HTTP y `Retry-After`.

Workspace define estados, contexto y puertos en `core/workspaces`, y coordina acceso,
provisión y reconciliación en `use_cases/workspaces`. El adaptador ArcadeDB usa root
sólo para provisionar; los runtimes reciben el principal restringido al dueño.
El cifrado conserva sus claves y separación de dominios. `bootstrap/workspaces.py`
crea y cierra los stores una vez resuelto ese límite. Las carpetas anteriores
`src/user_management`, `src/workspaces` y `src/auth` se eliminaron al migrar sus
consumidores; no conservan implementaciones ni shims duplicados.

Invitaciones mantiene selección, horarios y estados en `core/exteriorization`,
y consentimiento, programación y envío en sus casos de uso. Sus puertos
transaccionales entregan estados independientes del ORM. PostgreSQL conserva
los locks y la confirmación conjunta de invitación, aviso, delivery, job y outbox;
Web Push valida y envía mediante puertos separados. La bandeja funciona sin push.
Notificaciones separa reglas/acciones tipadas, coordinación y persistencia; las
publicaciones son explícitas e inmutables y su distribución conserva el cursor durable.

Administración calcula períodos y métricas desde hechos tipados; la cobertura
desconocida sigue siendo `null`. El lector filesystem entrega sólo metadatos al
sincronizador, que coordina su proyección mediante un puerto. Consultas y cambios
de permisos usan transacciones distintas, con commit explícito para las escrituras.
`bootstrap/administration.py` compone su API y su pool SQL independientes.
`bootstrap/public_channels.py` ensambla los canales HTTP públicos; los módulos de
servicios no cargan esas rutas al iniciar CLIs, dispatcher o workers. Las carpetas
anteriores `src/exteriorization`, `src/notifications` y `src/administration` se retiraron.

Mover archivos no basta si persisten sesiones SQL en los casos de uso o clientes
concretos detrás de un runtime. Durante la transición se mantienen puentes de import
y entrypoints sólo donde sean necesarios para consumidores identificados, con
condición de retiro. No hay dos implementaciones canónicas ni excepciones generales
para paquetes completos. El plan y el mapa se actualizan al completar cada etapa.
