# Extractor de emociones: prueba de la arquitectura por capas

El contrato común y el primer extractor están integrados al procesamiento durable.
Las notas nuevas y los documentos transcritos de audio extraen y persisten emociones
automáticamente, después de guardar el original. También sigue disponible la CLI
para dry run y persistencia diferida.

## Procesamiento al subir una nota

El request de subida guarda el original y agenda el trabajo; no llama al modelo.
Las notas nuevas usan el coordinador de documento v4 y un hijo por extractor:

```text
documento: document_persistence → extractor_processing → done
hijo emociones: extraction → persistence → done
```

La configuración aceptada conserva extractor, snapshot del profile, proveedor y
modelo. Cambiar el prompt o `OPENAI_MODEL` no modifica un trabajo ya aceptado.
El UUID de ejecución de la capa se deriva del UUID del procesamiento y su nombre.
Un retry reutiliza el artefacto; un fallo de persistencia no vuelve a extraer ni
construye un proveedor. La escritura repetida es idempotente.

La extracción usa `LLM_PROVIDER=openai`, `OPENAI_API_KEY` y `OPENAI_MODEL`. Si falta
configuración, el original queda guardado y el trabajo permite retry después de
corregirla. Los errores transitorios siguen los reintentos del runtime, sin sumar
reintentos internos del SDK. Audio conserva su transcripción y transmite la
configuración aceptada al documento hijo.

Trabajos anteriores sin capas mantienen el workflow v2 y no invocan modelos.
La limpieza masiva sigue convirtiendo trabajos exploratorios v1 a v2. Un nuevo
reprocesamiento explícito usa v4 con la configuración actual; no se ejecuta un
backfill automático de emociones para notas existentes.

Cada capa tiene un trabajo independiente con sus etapas, artefactos y retry.
El coordinador espera a todas sin cancelar las exitosas cuando otra falla. Los
locks por rama permiten paralelismo y un guard compartido impide borrar el
documento mientras ejecutan. Ver [trabajos por extractor](extractor-jobs.md).
El visor de Constelaciones muestra la nota conectada con las emociones y sus
citas. Permite filtrar por tipo de extracción; el nodo administrativo de ejecución
no aparece en la vista.

## Propósito y resultado

`EmotionExtractor` extrae ocurrencias de emociones expresadas explícitamente
por quien escribe. Cada una tiene `label` y una `quote` literal del documento
completo. Las etiquetas son breves y en el idioma de la nota; no hay taxonomía
cerrada, intensidad calculada, diagnóstico ni inferencia de estados ocultos.
El prompt excluye emociones atribuidas sólo a terceros, ejemplos y negaciones.

```json
{
  "occurrences": [
    {"label": "alegría", "quote": "Hoy siento alegría."},
    {"label": "miedo", "quote": "Después sentí miedo."}
  ]
}
```

La validación local exige citas exactas, no vacías y con una sola aparición
(incluidas coincidencias superpuestas). Rechaza pares etiqueta/cita duplicados.
Dos emociones diferentes pueden compartir una oración que expresa ambas.
Un array vacío es un resultado válido. La validación de citas demuestra su
procedencia; la fidelidad semántica de las etiquetas todavía debe evaluarse con
notas representativas. No se realizó una evaluación de precisión con modelos reales.

## Contrato y encapsulamiento

`src/extractors/base.py` define `Extractor` como clase abstracta. La implementación
define `produce`, `validate_payload` y `write_layer`: algoritmo, modelo y lógica
de guardado pertenecen a la capa. `EmotionProvider` es su puerto de generación;
`OpenAIEmotionProvider` usa el schema propio `Emotions`. Otro extractor puede
usar un proceso distinto sin heredar esa dependencia de LLM.

El ciclo común ofrece:

- `extract(document, dry_run=True, run_id=None)`: genera, valida y guarda un
  artefacto durable. `dry_run=False` además persiste la capa. Un UUID nuevo
  acumula una ejecución independiente; no reemplaza ni selecciona resultados vigentes.
- `persist(output)`: exige el artefacto guardado en el workspace, recupera el
  original actual, comprueba su huella y valida el payload antes de escribir.
  Funciona sin proveedor y sin volver a extraer.
- `ExtractorRegistry`: compone implementaciones por nombre, sin condicionales
  sobre modelos de emociones ni perfiles exploratorios históricos.

El envoltorio `ExtractionOutput` conserva UUID de ejecución, documento, SHA-256
del texto, capa, fecha, snapshot del profile y su huella, configuración solicitada,
metadatos del proveedor y payload propio. No acepta un workspace indicado por el
resultado; las dependencias ya están limitadas al workspace confiable.

Los artefactos usan almacenamiento inmutable con publicación exclusiva, checksum
y fsync en `layers/<document UUID>/<run UUID>/result.json` dentro del workspace.
Un reintento con el mismo UUID reutiliza el resultado y no llama al proveedor.
Cambiar profile o modelo para ese UUID falla; usar otro UUID inicia una ejecución
nueva. Persistir un resultado anterior conserva el profile guardado aunque el
prompt actual haya cambiado. Esto es trazabilidad, sin gestor de versiones.

## Grafo propio de la capa

```text
Document → HAS_EMOTION_EXTRACTION → EmotionExtraction → HAS_EMOTION → Emotion
```

`Emotion` representa una ocurrencia, no una entidad global fusionada. Sus IDs
se derivan de UUID de ejecución y posición del resultado. La ejecución también
queda registrada cuando el array está vacío. Todos los nodos derivados y relaciones
incluyen `layer=emotions`, documento, ejecución y etiquetas del profile.
Las ocurrencias guardan etiqueta, cita y offsets Unicode del texto original;
el run conserva la huella del texto y el artefacto serializado.

El extractor crea únicamente su esquema, al persistir. Usa el puerto de comandos
de ArcadeDB del workspace, sin acceso administrativo ni cambios al documento.
Una transacción verifica el documento, el run, las ocurrencias y los endpoints de
las relaciones. Reintentos idénticos no duplican; un run con otra huella falla.
Una escritura incompleta revierte en vez de reportar éxito. La inicialización DDL
puede dejar tipos vacíos si la persistencia falla.

El borrado existente elimina nodos con `document_id` y sus relaciones; ahora
elimina también los artefactos locales de capas para ese documento.

## Ejecutar la prueba

La limpieza de la etapa 1 debe haberse completado antes de habilitar esta prueba.
Usar la imagen nueva y la misma configuración/volumen del worker. El workspace
se resuelve por PostgreSQL y credenciales propias; debe estar activo.
Para extraer, se requieren `LLM_PROVIDER=openai`, `OPENAI_API_KEY` y `OPENAI_MODEL`.
El dry run sí llama al proveedor y guarda el artefacto; sólo excluye escritura de
la capa en el grafo. El documento debe haber terminado su procesamiento previo
antes de persistir emociones.

```sh
# Extrae y guarda un artefacto; no escribe emociones en el grafo.
python -m src.extractors.cli extract --workspace UUID_USUARIO --document UUID_DOCUMENTO

# Persistencia diferida: usa el UUID devuelto, sin volver a llamar al proveedor.
python -m src.extractors.cli persist --workspace UUID_USUARIO \
  --document UUID_DOCUMENTO --run UUID_EJECUCION

# Extraer y persistir inmediatamente; conservar este UUID permite reintentar.
python -m src.extractors.cli extract --workspace UUID_USUARIO \
  --document UUID_DOCUMENTO --run UUID_EJECUCION --persist
```

`extract --profile archivo.json` permite probar un snapshot con `id` e
`instructions`, manteniendo el schema de emociones. La salida del comando contiene
identidades y conteos, sin notas, citas ni secretos. El artefacto local permite
inspeccionar el resultado completo.

El comando conserva el lock actual por documento y rechaza procesamientos activos;
coordina con borrado y workers sin quitar protecciones. El núcleo permite ejecutar
extractores independientes concurrentemente, probado con otra implementación de
algoritmo y payload diferentes. El comando de prueba serializa por documento:
el pipeline durable ahora dispone de locks y estados por rama para ejecutar capas
en paralelo. El proceso llamador de la CLI debe gestionar su contexto de concurrencia.

## Validación

La suite general del backend pasó localmente. Cuatro pruebas con ArcadeDB
aisladamente validaron la persistencia de la capa.

Pruebas locales cubren evidencia, vacío válido, artefactos dañados, aislamiento
por workspace, cambios de fuente/profile/modelo, reintentos sin proveedor,
persistencia diferida y dos algoritmos distintos ejecutados a la vez.
El adaptador OpenAI se prueba con un cliente inyectado, incluyendo ausencia de
salida estructurada; sigue el contrato de
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

Integraciones opt-in crean y eliminan bases desechables en ArcadeDB 26.9.1.
Comprueban esquema propio, dry run sin DDL, metadatos/citas, persistencia diferida,
repetición idempotente, resultado vacío, ejecuciones independientes, rechazo de
original ausente, rollback de escritura parcial y borrado de documentos.
No se ejecutó la prueba contra notas de usuario, proveedores reales ni producción.

Cuatro integraciones adicionales con PostgreSQL y ArcadeDB verifican subida sin
LLM en el request, extracción/persistencia automática, replay idempotente, retry
desde persistencia sin proveedor, audio y reprocesamiento. Los proveedores son
fixtures determinísticos; no acreditan precisión del modelo sobre notas reales.
