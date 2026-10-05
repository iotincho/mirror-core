# Etapa 3: ejecución durable

Implementa la infraestructura compartida para los casos de uso diferidos.
Los endpoints actuales conservan su comportamiento. La
[etapa 4](deferred-ingestion.md) conecta documentos/audio mediante rutas `/v2`,
registra ambos workflows de producción y agrega recibos idempotentes y
relaciones padre/hijo. Un workflow desconocido termina con
`workflow_not_registered`.

## Componentes y límites

- `ProcessingRepository`: PostgreSQL guarda registros, historial de eventos y
  outbox. La creación del trabajo, su evento inicial y la intención de envío se
  confirman en una misma transacción. Las búsquedas de usuario exigen su `user_id`.
- `ExecuteProcessing`: adquiere lease, mantiene heartbeat, verifica workspace
  activo y ejecuta la versión registrada del caso de uso. La definición del
  workflow contiene sus transiciones; el runner no conoce extracción ni audio.
- `ExecutionContext.advance`: valida la transición del workflow y confirma
  checkpoint, versión y evento antes de iniciar la siguiente etapa.
- `WorkflowFailure`: el caso de uso devuelve un código seguro y decide si el
  error admite reintento y su demora. El runner limita a cuatro intentos por
  etapa; la etapa 4 incorpora clasificación de proveedores y backoff 10/30/120 con jitter. Los errores internos inesperados terminan como
  `workflow_internal_error`; los errores SQL dejan el lease para recuperación.
- `processing.execute`: adaptador Taskiq. El mensaje contiene únicamente ID y
  generación. Confirma manualmente la entrega después de resolver el estado en
  SQL. Mientras PostgreSQL no responde conserva la entrega y espera; cancelar
  el worker deja el mensaje sin confirmar.
- `processing.dispatcher`: reclama outbox con `SKIP LOCKED`, publica mensajes
  persistentes con publisher confirms y marca el envío confirmado. Si RabbitMQ
  falla, conserva la intención y difiere otro intento. Puede tener varias
  réplicas. Escanea también leases vencidos y entregas posiblemente perdidas.

Una caída entre confirmación de Rabbit y confirmación SQL puede duplicar un
mensaje: la generación y el lease impiden duplicar la ejecución. Un retry crea
otra generación, invalidando mensajes antiguos. La recuperación de una entrega
perdida conserva la generación para que un mensaje válido ya en cola mantenga
su posición. No recrea envíos mientras exista outbox pendiente de esa generación.
La recuperación de entrega se verifica a los cinco minutos; el dispatcher
consulta cada cinco segundos. Los leases vencidos conservan etapa/checkpoints,
invalidan el token anterior y reprograman o fallan al agotar intentos.

## Exclusión y efectos externos

Cada ejecución mantiene un advisory lock PostgreSQL por usuario e ID del
recurso, en una conexión dedicada. Dos jobs del mismo recurso se serializan,
además de rechazar avances con un lease/token vencido. La conexión del lock
mantiene una transacción abierta durante la ejecución; las transacciones que
actualizan estado y lease son independientes y cortas. Dimensionar el pool para
una conexión de lock por ejecución más las operaciones breves.

Esta exclusión coordina ejecutores que usan el runner. Si la conexión del lock
se pierde mientras un servicio remoto sigue procesando una petición, el lock
puede liberarse antes de finalizar ese efecto remoto. Los adaptadores concretos
necesitan IDs deterministas, artefactos exclusivos y reconciliación de commits
ambiguos. La etapa 4 integra y prueba esos adaptadores;
el token SQL no se presenta como garantía de ejecución única de efectos remotos.

La exclusión por recurso usa la clave `user_id:resource_id`.
Audio y documento derivado comparten UUID y esa exclusión. La configuración del job contiene sólo opciones
sin secretos, y los checkpoints referencias/metadatos, nunca documentos completos.
Los códigos de error expuestos no deben contener mensajes de proveedores.

## Ejecución local

Instalar dependencias y aplicar migraciones antes de iniciar consumidores:

```bash
python -m pip install -e '.[dev]'
python -m alembic upgrade head
```

El Compose habitual incluye RabbitMQ, el worker y el dispatcher. RabbitMQ no
publica puertos hacia el host:

```bash
docker compose up -d --build

# Tres containers independientes; sin container_name ni puertos fijos.
docker compose up -d --scale processing-worker=3 processing-worker
```

Cada container ejecuta un proceso Taskiq con cuatro tareas async por defecto.
`PROCESSING_CONCURRENCY` controla tanto el límite de tareas del comando Compose
como el prefetch Rabbit. `PROCESSING_LEASE_SECONDS` vale 90; heartbeat cada tercio
del lease. No agregar middleware de reintentos Taskiq: PostgreSQL programa todos
los reintentos. El comando worker debe usar `--ack-type manual`.

Para ejecutar sin Compose, con PostgreSQL migrado y RabbitMQ disponibles:

```bash
python -m taskiq worker src.processing.broker:broker src.processing.tasks \
  --workers 1 --max-async-tasks 4 --max-prefetch 0 --ack-type manual
python -m src.processing.dispatcher
```

`DATABASE_URL`, `RABBITMQ_URL` y los paths de datos deben apuntar a los mismos
servicios/volúmenes para todas las réplicas. `PROCESSING_QUEUE_NAME` identifica
la cola y exchange de ese entorno; por defecto `el_espejo.processing.v1`.
Distintos entornos deben usar bases, volúmenes y vhosts Rabbit separados.

RabbitMQ usa una imagen fija `4.3.6-management-alpine`, un hostname estable y
volumen persistente. Este Compose es de desarrollo y usa una instancia con colas
clásicas durables; no ofrece alta disponibilidad del broker. El despliegue de
producción, métricas, retención de eventos/outbox y estrategia HA corresponden
a etapa 6. La API no requiere iniciar RabbitMQ hasta conectar los uploads.

## Validación

Las pruebas de transporte se ejecutan en la suite habitual. Las pruebas de
integración requieren PostgreSQL **aislado**, con migraciones aplicadas, y
opcionalmente RabbitMQ aislado. Crean usuarios/jobs temporales y dos procesos
Taskiq reales; no usar una base ni un broker compartidos con usuarios.

```bash
PROCESSING_TEST_DATABASE_URL='postgresql+asyncpg://.../processing_test' \
PROCESSING_TEST_RABBITMQ_URL='amqp://.../processing_test' \
python -m pytest tests/integration/test_processing_postgres.py
```

Se validan atomicidad de estado/evento/outbox y rollback, ownership y workspace
suspendido, duplicados, transiciones ilegales, reintentos acotados por etapa,
checkpoints recuperables, fencing y recuperación, advisory locks por recurso,
heartbeat, cancelación, reclamo concurrente de outbox, fallo de publicación,
recuperación de una entrega perdida y ejecución/ACK con dos workers reales.
La prueba real mata un proceso worker después de persistir un checkpoint,
vence su lease y comprueba la continuación desde ese checkpoint.

La migración `20261005_03` fue validada con upgrade/downgrade/upgrade en un
PostgreSQL de pruebas. Estas verificaciones no aplican migraciones al entorno de
desarrollo ni acreditan despliegue de producción.

Referencias: [Taskiq CLI y ACK manual](https://taskiq-python.github.io/guide/cli.html),
[adaptador RabbitMQ](https://github.com/taskiq-python/taskiq-aio-pika),
[publisher confirms de aio-pika](https://docs.aio-pika.com/apidoc.html),
[releases RabbitMQ](https://www.rabbitmq.com/release-information).
La implementación usa la API publicada de `taskiq-aio-pika 0.5`, cuya firma
difiere de la documentación de la rama `master`.
