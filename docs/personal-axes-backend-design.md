# Ejes personales: modelo y backend de creación y prueba

Estado: diseño acordado. Las entregas 1 a 4 del backend están implementadas
localmente; ver [contratos y operación de la API](personal-axes-api.md).

Continuación: [plan de implementación del backend completo](personal-axes-backend-implementation-plan.md).

Alcance: puntos 1 y 2 del plan del issue #51: modelo, generación/refinamiento del
criterio de extracción y pruebas recuperables sobre cinco notas. Se define el
contrato de aceptación y ejecución para evitar incompatibilidades. La integración
con notas nuevas y la exploración activa están detalladas en el plan ampliado;
la UI pertenece a una etapa posterior.

## Decisiones de partida

- La creación y el refinamiento son efímeros. El borrador puede persistirse en el
  dispositivo, separado por usuario. No existe un eje de dominio hasta aceptarlo.
- Sólo se conservan permanentemente las versiones aceptadas: finalidad y prompt
  ejecutable, junto con la configuración que identifica su comportamiento.
- Cada extracción identifica su eje y la versión utilizada.
- La prueba no escribe en ArcadeDB ni modifica las extracciones de las notas.
- Las citas pertenecen a las relaciones de origen, como en emociones: una
  relación por cita, con `quote`, `start_char` y `end_char`. El nodo del hallazgo
  conserva su título, contenido y etiquetas, sin citas como propiedades propias.
- Emociones conserva prompt, formato, validación, persistencia y comportamiento.
- El Laboratorio será una superficie separada de la constelación existente.

## 1. Responsabilidades

Los ejes personales son otra familia del sistema existente de extractores.
Su implementación vive en `src/extractors/personal_axes/`, sin crear un módulo
paralelo ni otra interfaz de extracción.

| Componente | Responsabilidad |
| --- | --- |
| `contracts.py` | Entrada de prueba y payload de hallazgos de esta familia; reutiliza los contratos comunes. |
| `models.py`, `repository.py` | Ejes y versiones aceptadas en PostgreSQL. |
| `preview_store.py` | Manifiestos temporales y vencimiento; compone los almacenes de artefactos existentes. |
| `prompt_builder.py` | Generación/refinamiento de instrucciones mediante LLM. |
| `extractor.py` | `PersonalAxisExtractor(Extractor)`: implementación de los hooks de la interfaz existente. |
| `preview_projection.py` | Lista y grafo desde hallazgos de una prueba. |
| `routes.py`, `dependencies.py` | API autenticada y composición. |

Los casos de uso viven en `src/use_cases/`: `RequestAxisPreview`,
`ProcessAxisPreview`, `AcceptAxisPreview`, `RetryAxisPreview` y
`ExpireAxisPreviews`. Los casos de uso controlan transiciones y reglas;
Taskiq/RabbitMQ transportan trabajo mediante el runtime y outbox existentes.

### Reutilización de las interfaces existentes

| Pieza existente | Uso en ejes personales |
| --- | --- |
| `ExtractorProfile` | Instrucciones evaluadas y su fingerprint. |
| `ExtractionOutput` | Sobre común de resultado: documento, ejecución, hash de fuente, profile, configuración y metadatos de proveedor. |
| `Extractor.extract(..., dry_run=True, run_id=...)` | Extracción de cada nota de la muestra, validación, guardado del resultado y recuperación por ID estable. |
| `Extractor.persist(output)` | Persistencia posterior de resultados activos, con las verificaciones de artefacto y fuente existentes. |
| `LayerArtifacts` | Almacenamiento de `ExtractionOutput`, con una raíz temporal para pruebas y la raíz de capas para ejecuciones activas. |
| `ProcessingArtifacts` | Manifiesto de prueba y checkpoints adicionales del generador o proveedor. |
| `ExtractorRegistry` | Un constructor de la familia `personal_axis`; el eje concreto se pasa como especificación. |
| `DocumentStore` | Lectura de fuentes dentro del workspace del usuario. |

`PersonalAxisExtractor` implementa `produce`, `validate_payload` y `write_layer`;
usa `produce_for_run` si necesita checkpoints propios de respuesta/corrección.
El payload de hallazgos le pertenece, pero no redefine `extract`, `persist` ni
el sobre común para duplicar funcionalidades de la clase base.

El generador/refinador produce un `ExtractorProfile` y la configuración aceptable
para ese extractor. Generar instrucciones es un paso previo; el procesamiento de
la nota sigue pasando por `Extractor.extract`.

`dry_run` ya guarda artefactos: significa ejecutar sin escribir la capa activa,
no ejecutar sin almacenamiento. La temporalidad se consigue inyectando una raíz
de `LayerArtifacts` dentro de la prueba y aplicándole su vencimiento. No se crea
otro mecanismo de checkpoint para los resultados finales de extracción.

El proveedor LLM y el repositorio de definiciones son específicos de esta familia;
para documentos, artefactos, extracción y registro se reutilizan las interfaces
existentes, sin introducir puertos equivalentes adicionales.

## 2. Modelo permanente

### `personal_axes`

| Campo | Regla |
| --- | --- |
| `id` | UUID estable del eje. |
| `user_id` | Propietario; FK al usuario. |
| `current_version_id` | Versión aceptada seleccionada para ejecuciones nuevas. |
| `enabled` | Habilitación; independiente de la versión del criterio. |
| `created_at`, `updated_at` | Fechas del servidor. |

Título y finalidad se leen desde la versión actual: no se duplican en esta tabla.
No se incluyen estados `draft`, historial de comentarios ni muestras de prueba.

### `personal_axis_versions`

| Campo | Regla |
| --- | --- |
| `id` | UUID de la versión aceptada. |
| `axis_id` | FK al eje. |
| `number` | Secuencia por eje: 1, 2, 3…; no es el número de iteraciones. |
| `title` | Título evaluado. |
| `purpose` | Descripción de la finalidad evaluada. |
| `prompt_snapshot` | Instrucciones efectivas exactas utilizadas en la prueba. |
| `execution_config` | Proveedor, modelo y parámetros explícitos utilizados. |
| `output_contract_version` | Versión del esquema de hallazgos. |
| `validation_policy_version` | Reglas de evidencia y validación aplicables. |
| `specification_hash` | Hash de la especificación ejecutable completa. |
| `accepted_preview_id` | UUID opaco de la prueba aceptada; único. |
| `created_at` | Fecha de aceptación. |

La versión es inmutable. No contiene notas, resultados de muestra, comentarios ni
versiones rechazadas del prompt. `accepted_preview_id` permite reconocer una
aceptación repetida incluso después de eliminar la prueba temporal; no exige
retenerla mediante FK.

En el modelo implementado, prompt, configuración y versiones de contrato y
validación se reúnen en una columna JSONB `specification`, utilizando
`AxisSpecification` y `ExtractorProfile`. La finalidad, título, hash e identidad
de aprobación son columnas propias; no se duplica el contenido de la especificación.

Restricciones: unicidad `(axis_id, number)`, número positivo y referencia de la
versión actual al mismo eje. Esta última se implementa mediante FK compuesta
diferible, para crear eje y primera versión en una sola transacción. Todas las
operaciones se filtran por el propietario del eje.

El hash no garantiza que dos llamadas futuras del proveedor produzcan la misma
respuesta: identifica las instrucciones y configuración que se les suministran.

## 3. Estado temporal

### Borrador en el dispositivo

Contiene `draft_id`, revisión local, título, finalidad, comentarios de ajuste,
cinco IDs de notas y referencia a la última prueba. Para editar un eje aceptado
también contiene `axis_id` y `base_version_id`.

Es trabajo en curso, no autoridad para aprobar prompts. El cliente no puede
registrar un prompt arbitrario como si hubiera sido evaluado por el backend.

### Prueba en el servidor

Ruta propuesta, sobre el volumen compartido que ya utilizan API y workers:

`workspaces/{user_id}/laboratory/previews/{preview_id}/`

Su entrada inmutable conserva la revisión recibida, información necesaria para
generar/refinar, finalidad, muestra con hashes, configuración elegida por el
servidor, eje/versión base cuando corresponda y vencimiento. Los artefactos son:

- Respuesta de generación del criterio y especificación ejecutable ensamblada.
- Respuesta del proveedor cuando corresponda y un `ExtractionOutput` validado por
  nota, guardado mediante `LayerArtifacts` con IDs de ejecución estables.
- Lista y grafo de la prueba, o información suficiente para reconstruirlos.

Las notas se leen de sus originales. No es necesario guardar copias completas
de las cinco notas dentro de la prueba.

Composición de almacenamiento:

```python
preview_root = workspace_root / "laboratory" / "previews" / str(preview_id)
manifest = ProcessingArtifacts(preview_root)
artifacts = LayerArtifacts(preview_root / "layers")
```

`preview_store.py` organiza esta composición y su ciclo de vida; no reemplaza
la escritura inmutable y verificación de hashes que ya ofrecen esas clases.

Los hashes de fuentes de la primera prueba se mantienen durante el refinamiento:
si el texto cambió, no se compara silenciosamente con otra muestra. El cliente
debe confirmar una nueva muestra/prueba. Si la prueba anterior venció, puede
retomar su intención desde el borrador local, pero deberá generar y evaluar de
nuevo; una copia local del prompt no acredita una prueba válida en el servidor.

### Metadatos operativos en PostgreSQL

Reutilizar `processing_records`, outbox, leases y eventos exige filas temporales
en PostgreSQL. No son ejes ni historial de creación: contienen identidad, dueño,
referencias a fuentes/artefactos, estado, errores seguros y vencimiento; no los
comentarios, prompts o resultados de las iteraciones.

Propuesta: `workflow=axis_preview`, `resource_kind=axis_preview`,
`resource_id=preview_id`, `document_id=NULL`. Agregar vencimiento opcional a los
registros/recibos temporales, sin aplicarlo a los trabajos de notas existentes.

El vencimiento se controla al solicitar, ejecutar, consultar, reintentar y aceptar.
La limpieza periódica elimina artefactos y filas operativas relacionadas en orden
seguro. No se eliminan archivos mientras un worker conserve su exclusión de la
prueba. Los mensajes tardíos del broker no pueden recrear una prueba eliminada.

Un plazo inicial configurable, por ejemplo 72 horas por prueba, permite retomar
sin convertir las pruebas en almacenamiento permanente. Si vence, el borrador
local sigue disponible, pero se requiere otra prueba antes de aceptar.

## 4. Contrato de hallazgos

Contrato exclusivo de extractores personales; no reemplaza contratos de otras
familias. Es el `payload` del `ExtractionOutput` existente, no un nuevo sobre
de ejecución. La salida del proveedor tiene esta forma conceptual:

```json
{
  "findings": [
    {
      "title": "Título breve",
      "content": "Desarrollo suficiente para recuperar la idea.",
      "evidence": [{"quote": "Fragmento literal de la nota"}],
      "tags": ["etiqueta abierta"]
    }
  ]
}
```

Reglas propuestas:

- Cero o varios hallazgos por nota; `findings: []` es éxito sin hallazgos.
- Cada hallazgo requiere título, contenido, evidencia y al menos una etiqueta.
- Las citas son literales, contiguas y localizables sin ambigüedad. El backend
  calcula offsets sobre el texto original; no confía en posiciones inventadas.
- Una cita ausente o ambigua es un error de validación, no un resultado vacío.
- El backend agrega IDs y trazabilidad: documento, hash de contenido,
  ejecución y profile reutilizan `ExtractionOutput`. La identidad del eje/versión
  aceptados y los campos específicos de sus hallazgos se validan en esta familia.
- Las etiquetas se deduplican por NFC, mayúsculas/minúsculas y espacios. Su
  agrupación se limita al eje, o a esa prueba cuando todavía no hay eje.
- No se impone un vocabulario de etiquetas ni se unen sinónimos automáticamente.
- El contenido expresa las interpretaciones ambiguas como posibilidades; no se
  agrega una puntuación numérica de certeza en esta etapa.

La validación garantiza estructura y citas; no demuestra que la interpretación
semántica sea correcta. Esa utilidad se evalúa con el usuario durante la prueba.

La salida estructurada y el listado agrupan `evidence` junto al hallazgo para
leer el resultado de cada nota; esa agrupación no define el almacenamiento del
grafo. En ArcadeDB cada cita vive en una relación
`AxisExtraction → HAS_AXIS_FINDING → AxisFinding`. Al ocultar el contenedor de
ejecución, la vista previa la representa como `Document → HAS_FINDING → AxisFinding`,
conservando la cita y los offsets en el enlace. Varias citas producen varias
relaciones hacia el mismo hallazgo, no varios nodos del mismo hallazgo.

Propuesta de recuperación de salida inválida: una corrección acotada y registrada
como artefacto, sin cambiar el criterio del eje. Si no puede validarse, esa nota
queda fallida y no habilita aceptación. No se descarta silenciosamente la parte
inválida para presentar una extracción parcial como completa.

## 5. Funcionamiento de una prueba

### Solicitud

`POST /laboratory/axis-previews`, con `Idempotency-Key`.

Recibe la revisión local, título, finalidad, IDs de las cinco notas y, para
refinamiento, referencia a la prueba anterior y comentarios/ajustes del borrador.
Para edición incluye el eje y versión base. El servidor elige proveedor y modelo.

Antes de encolar valida cinco IDs distintos, propiedad, existencia, contenido y
límites configurados. Fija sus hashes de contenido y la identidad completa de la
entrada. Cambiar la muestra requiere indicarlo expresamente; no ocurre al refinar.

La reserva idempotente permite guardar el artefacto de entrada antes de publicar
el trabajo. Un fallo entre archivos y PostgreSQL deja una reserva recuperable o
un archivo huérfano limpiable, nunca un trabajo ejecutable sin entrada válida.
La misma clave y entrada devuelven la misma prueba; otra entrada con la misma
clave devuelve conflicto.

La identidad de la solicitud incluye dueño, revisión local, muestra y hashes,
modo de generación/refinamiento/repetición y versión base. La reserva original
define la configuración: un replay no vuelve a capturar el modelo configurado
actualmente ni las versiones nuevas de las notas.

### Workflow `axis_preview` v1

`prompt_generation → sample_extraction → preview_projection → done`

1. **Generación/refinamiento.** El LLM recibe la finalidad vigente, el criterio
   anterior y los ajustes aplicables del borrador. Devuelve instrucciones de
   observación. El backend ensambla esas instrucciones con el esquema y reglas
   fijas de ejecución. Guarda el resultado antes de avanzar de etapa.
2. **Muestra.** Ejecuta la especificación resultante sobre las cinco notas con
   concurrencia limitada, usando el mismo `PersonalAxisExtractor` que ejecutará
   las notas activas. Llama `extract(document, dry_run=True, run_id=stable_run_id)`
   por nota con la raíz temporal de artefactos. La implementación heredada valida
   el contenido, recupera resultados previos y guarda un `ExtractionOutput`.
3. **Proyección.** Construye lista y grafo desde los payloads de esos resultados. Los IDs del
   grafo incluyen la identidad de la prueba. No se escribe en ArcadeDB.
4. **Finalización.** La prueba queda aceptable sólo cuando las cinco notas
   completaron la validación. Cinco resultados vacíos también son una prueba
   completada. Los resultados parciales pueden consultarse sin habilitar aceptación.

Las etapas son del caso de uso, no de la tarea del broker. Se reutilizan leases,
fencing, outbox y exclusión del runtime existente. Para esta muestra de tamaño
fijo no hace falta extender aún el coordinador padre/hijos de documentos.

`ProcessAxisPreview` coordina generación y cinco llamadas al extractor, no
implementa otro motor de extracción. El `ProcessExtractor` actual pasa siempre
por `extraction → persistence`; por eso no se lo invoca tal cual para una prueba.
Se reutiliza directamente la interfaz de `Extractor` y el runtime de workflows,
sin agregar banderas de Laboratorio al workflow de notas existente.

Una nueva iteración crea otra prueba temporal; no muta la que el usuario estaba
revisando. Un reintento recupera la misma prueba. Repetir sólo la muestra con el
mismo criterio debe ser una operación explícita que reutiliza la especificación,
sin pedir al LLM que la genere otra vez.

La generación del criterio no necesita recibir el contenido de las cinco notas;
la extracción sí recibe cada nota como datos, nunca como instrucciones. El
contrato de salida y las reglas de evidencia pertenecen al backend, no al prompt
generado. Notas demasiado largas se rechazan con un error explicativo; nunca se
truncan silenciosamente. La segmentación de notas queda fuera de esta etapa.

## 6. Consulta y aceptación

| Operación | Propósito |
| --- | --- |
| `GET /laboratory/axis-previews/{id}` | Estado, etapas, progreso por nota, hashes y vencimiento. |
| `GET /laboratory/axis-previews/{id}/results` | Hallazgos por nota y proyección del grafo, identificados por prueba. |
| `POST /laboratory/axis-previews/{id}/retry` | Retomar fallos recuperables sin nueva iteración. |
| `POST /laboratory/axis-previews/{id}/accept` | Registrar eje o nueva versión con el contenido exacto evaluado. |
| `GET /personal-axes` | Ejes aceptados del usuario. |
| `GET /personal-axes/{id}` | Descripción y versión actual para iniciar otro borrador. |

Prefijos internos de FastAPI; el proxy público conserva su prefijo `/api`.

La aceptación recibe la identidad de prueba y el hash de la revisión evaluada,
no un prompt de reemplazo. Bajo exclusión de la prueba, valida dueño, vigencia,
cinco resultados válidos y fuentes todavía existentes/sin cambios. Si edita un
eje, comprueba mediante bloqueo de fila que `base_version_id` siga siendo actual.

En una transacción crea eje y versión 1, o una nueva versión del eje existente,
y actualiza su referencia actual. `accepted_preview_id` evita duplicados; una
repetición devuelve el eje y versión ya registrados, incluso si se perdió la
respuesta anterior o ya se limpió la prueba. No hay llamada al LLM ni escritura
en ArcadeDB durante la aceptación.

Aceptar una definición no llama `extractor.persist(output)`: ese método guarda
los hallazgos de una nota. Aquí se registra el profile/configuración aceptados
en PostgreSQL. Las ejecuciones activas posteriores usarán el mismo extractor y
su `persist` mediante el flujo normal de extracción/persistencia.

Al crear se habilita el eje; una nueva versión conserva su estado de habilitación.
Las extracciones previas no cambian. La prueba de muestra sigue siendo temporal
y no se promueve a hallazgos activos automáticamente en este contrato propuesto.

## 7. Fallos, concurrencia y aislamiento

- **Dos dispositivos editan el mismo eje:** la segunda aceptación con versión
  base obsoleta devuelve conflicto. No pisa una aprobación más reciente.
- **Cae el worker:** retoma desde los artefactos guardados. Si el proveedor
  respondió pero el proceso murió antes de guardarlo, puede repetirse esa llamada;
  no se promete ejecución exactamente una vez ni cobro único del proveedor.
- **Falla una nota:** conserva las demás; reintenta sólo las notas pendientes o
  fallidas recuperables. El error de una nota no equivale a cero hallazgos.
- **Se modifica o elimina una fuente:** invalida la prueba para consulta de sus
  resultados y aceptación. Hay que cambiar explícitamente la muestra o repetirla.
  El borrado integra la invalidación/limpieza de artefactos que referencian la nota.
- **Carrera con borrado:** las lecturas de cada nota usan la exclusión compartida
  compatible con extractores, y aceptación revalida bajo los locks de fuentes
  correspondientes, adquiridos en orden estable.
- **Vence durante ejecución o aceptación:** ambas operaciones se serializan con
  limpieza mediante la exclusión de la prueba; no se acepta una prueba vencida ni
  se publican resultados de un worker que haya perdido su lease.
- **Usuarios:** el servidor obtiene `user_id` de la sesión, resuelve notas en su
  workspace y comprueba propiedad en cada consulta. IDs y hashes no son permisos.
- **Observabilidad:** eventos y logs contienen IDs, etapas y errores técnicos;
  no notas, finalidad, comentarios, prompts ni hallazgos.

Los locks de aplicación se intentan sin espera, como en el repositorio actual:
si no están disponibles se libera lo adquirido y se informa conflicto o se
reprograma. El borrado no espera un lock de prueba mientras retiene uno exclusivo
de documento. La limpieza de archivos se completa después de invalidar y cuando
ya no existe un worker con exclusión; no se mezclan órdenes de locks bloqueantes.

`expired` describe la disponibilidad de una prueba, no exige agregar otro estado
al enum genérico de procesamiento. Los endpoints devuelven `410` para pruebas
vencidas conocidas, `404` para IDs desconocidos o ajenos, y `409` para fuentes,
revisiones o versiones base que dejaron de coincidir. Aceptación repetida consulta
primero la versión permanente ya creada, antes de exigir que exista la prueba.

## 8. Adaptaciones al backend actual

1. Registrar el nuevo workflow y su caso de uso en la composición existente.
2. Agregar `PersonalAxisExtractor(Extractor)` y su constructor al registro;
   componer pruebas temporales con `LayerArtifacts`/`ProcessingArtifacts` y
   agregar la aceptación transaccional de definiciones.
3. Agregar vencimiento y limpieza segura de registros operativos y sus artefactos.
4. Dar a Laboratorio consulta y retry propios: el retry de notas actual asume
   que un recurso que no es documento es audio.
5. Filtrar por workflows de notas en los listados y clientes existentes. Si se
   usa el feed SSE común, agregar discriminación explícita por workflow para que
   pruebas del Laboratorio no alteren estados de notas. Mantener payloads seguros.
6. Integrar invalidación por eliminación de documentos y exclusión de fuentes.

Para la integración posterior con notas nuevas se separará tipo de implementación
(`personal_axis`) de identidad de rama (`axis:<uuid>`). Se conservarán contratos
y trabajos históricos, sin registrar un constructor por cada eje del usuario.
Las ejecuciones fijarán eje, versión, prompt y configuración al aceptar la nota;
el worker no resolverá la versión más reciente al ejecutar o reintentar.

## 9. Validación de estos dos puntos

- Migración, restricciones de propiedad y referencia a versión del mismo eje.
- Tras varias pruebas rechazadas no existe ningún eje ni versión permanente.
- Proveedor determinístico: generación, refinamiento y conservación de muestra.
- Dos ejes o borradores distintos no mezclan artefactos ni agrupaciones.
- Cero/múltiples hallazgos, citas ausentes/ambiguas y corrección acotada.
- Caídas después de generación y después de algunas notas; reanudar no repite
  resultados ya guardados ni publica trabajo sin entrada completa.
- Aceptación exacta, doble aceptación, respuesta perdida y dos dispositivos.
- Fuentes ajenas, fuente borrada/modificada y carreras con limpieza/vencimiento.
- Ninguna prueba escribe en ArcadeDB o aparece como procesamiento de una nota.
- Regresiones de emociones, ingesta, audio, reintentos, eventos y outbox.
- Evaluación humana con muestras de valores e ideas para podcast: las pruebas
  automatizadas no certifican utilidad o corrección de las interpretaciones.

## 10. Parámetros y alcance todavía propuestos

El plazo de retención, límites de entrada/salida, cantidad de pruebas simultáneas
y política concreta de corrección se fijarán mediante configuración. Las 72 horas
son una propuesta inicial, no una decisión ya aprobada. La edición de versiones,
habilitación y muestra no promovida se describen para cerrar el contrato de
aceptación; no implican implementar todavía toda la administración posterior.
