# Implementar cambios en el backend

La [arquitectura](../../ARCHITECTURE.md) separa `core`, `use_cases`, `adapters`
y `bootstrap`. Los entrypoints de procesos viven en bootstrap; no agregar
dependencias concretas dentro de aplicación o acceso.

## Recorrido de una tarea

1. Confirmar alcance y estado de Git; ubicar el área con arquitectura y el [índice](../README.md).
2. Leer las instrucciones del área, el contrato específico y una prueba cercana.
3. Identificar el comportamiento observable que cambia y sus fallos posibles.
4. Modificar el responsable existente y sus colaboradores mínimos.
5. Verificar según [la matriz](testing.md), actualizar el contrato y revisar el diff.

Una tarea ordinaria no necesita un documento nuevo. Cuando cambie una frontera
entre módulos, persistencia o compatibilidad, registrar la decisión en el contrato
afectado: problema, decisión, alternativas relevantes, recuperación y validación.
Un plan no reemplaza esa actualización al finalizar la implementación.

## Ubicación y diseño

- Rutas: validar entrada/sesión, obtener dependencias, llamar al caso de uso y
  traducir resultado/error. No introducir orquestación durable o SQL de negocio allí.
- Casos de uso: coordinar comportamiento y recuperación mediante contratos.
  Mantener I/O asíncrono; no bloquear el loop con procesos o archivos grandes.
- Repositorios: transacciones y consultas de su agregado. Persistencia de una
  capa de extracción pertenece a esa capa, no a un store genérico creciente.
- Composición: concentrar construcción de adaptadores y registros en `bootstrap`.
  Reutilizar las factories del área y el registro versionado de workflows;
  no crear un segundo registro o selector paralelo.
- Nombres: verbos para casos de uso, contratos explícitos y tipos en fronteras.
  Evitar `utils.py` o servicios que mezclen responsabilidades sin relación.
- Extraer un módulo cuando tenga una responsabilidad propia y reduzca acoplamiento;
  el número de líneas por sí solo no justifica un refactor general.

## Invariantes de datos y procesamiento

El documento original y el audio son evidencia. Guardar una interpretación o una
corrección no habilita a sobrescribirlos silenciosamente. Mantener fechas,
identidad y citas con offsets sobre el texto original.

La aceptación de documentos conserva el original y el vértice base de ArcadeDB
antes del recibo/job/outbox SQL. Esto no es una transacción distribuida: los fallos
intermedios necesitan replay idempotente. No esperar emociones, títulos o embeddings
para aceptar el original. Ver [ingestión](../deferred-ingestion.md).

PostgreSQL es la autoridad para el estado durable. Las entregas son al menos una
vez: conservar generación, lease/fencing, advisory locks y outbox. RabbitMQ/Taskiq
no decide la política de retry. Jobs ya aceptados conservan su versión y configuración.

`extract()` produce un artefacto recuperable; `persist()` lo valida y proyecta sin
volver a invocar el proveedor. Cada extractor reemplaza atómicamente sólo su capa.
Retry conserva IDs y checkpoints; reprocesamiento inicia otra ejecución. Al modificar
esta frontera cubrir duplicados, respuesta perdida y recuperación tras fallo parcial.

Los ejes aceptados son versiones inmutables. Las previews son temporales, con TTL,
y no escriben la proyección activa. Consultar [su contrato](../personal-axes-api.md).

## Aislamiento, errores y configuración

Resolver stores desde el workspace autenticado; workers lo reconstruyen desde el
dueño del job. Verificar ownership también en lecturas, retry, borrado y SSE.
La API administrativa se compone por separado en `src/bootstrap/administration.py`.

La configuración de entorno vive en `src/bootstrap/settings.py`. Inyectar valores tipados a la aplicación, manteniendo
especificaciones aceptadas en core y evitando nuevos accesos globales a settings.
Documentar alias/default en `.env.example` y en su contrato. API, workers
y dispatcher deben compartir valores cuando participan del mismo workflow.
Nunca persistir claves dentro de snapshots de configuración o manifests.

Errores de API/SSE usan códigos seguros; los logs conservan correlación técnica
sin notas, transcripciones ni credenciales. Una falla del proveedor no demuestra
corrupción del original. Distinguir disponibilidad, datos y representación.

## Migraciones y entrega

- Cambios SQL requieren una revisión Alembic nueva; no reescribir revisiones aplicadas.
- Separar esquema ArcadeDB y migraciones de datos de las escrituras normales.
- Probar upgrade y recuperación con bases aisladas. Explicar si downgrade pierde datos.
- Para entornos existentes: detener escritores, migrar SQL, preparar esquema de
  ArcadeDB y aplicar migraciones de datos antes de levantar la nueva versión.
  Revisar `deploy.sh` y [migraciones de datos](../data-migrations.md) para el procedimiento real.
- El build de imagen se mantiene junto a `Dockerfile.prod`. Un cambio de red/volumen
  puede requerir recrear contenedores. Validación local no confirma despliegue.

La entrega debe indicar qué cambia, cómo se verificó y qué quedó sin validar.
No añadir informes extensos por cada ejecución; conservar comandos reproducibles
en el contrato y resultados concretos en la descripción de la entrega.
