# Embeddings de documentos

La capa `document_embeddings` encuentra notas por similitud de contenido. Se
procesa como trabajo independiente junto con emociones, tanto al subir texto como
al crear la nota desde una transcripción. No crea relaciones entre notas ni genera
respuestas reflexivas. El buscador HTTP, la evaluación con OpenAI real y el
reprocesamiento masivo quedan para después de validar esta primera implementación.

Cada resultado conserva configuración, perfil, hash del original y secciones con
texto original, posiciones en caracteres Unicode, tokens y vector. Los reintentos
conservan el artefacto completo y pueden persistirlo sin llamar a OpenAI otra vez.
El conteo usa `tiktoken`/`cl100k_base` localmente; la imagen precarga el tokenizador
al construirla y no necesita descargarlo durante el procesamiento.

## Configuración

| Variable | Valor inicial |
| --- | --- |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` |
| `OPENAI_EMBEDDING_DIMENSIONS` | `1536` |
| `EMBEDDING_SEGMENTATION_THRESHOLD` | `2000` tokens |
| `EMBEDDING_SECTION_TARGET_TOKENS` | `1000` tokens |
| `EMBEDDING_SECTION_MAX_TOKENS` | `2000` tokens |

`OPENAI_MODEL` se usa únicamente para la segmentación temática. La configuración
se fija al aceptar el trabajo; cambiar variables no modifica trabajos aceptados.
La versión inicial admite OpenAI small y hasta 1536 dimensiones. Todos los textos
se cuentan antes de llamar a embeddings y nunca pueden exceder 8192 tokens.
El objetivo de sección debe ser menor o igual al máximo.

Las notas cortas generan un vector de todo el contenido. Las extensas se dividen
en ventanas de hasta 6000 tokens y bloques de hasta 256 tokens. El modelo devuelve
rangos de bloques para agrupar temas, sin copiar ni corregir el texto. Se reparan
huecos/solapamientos mediante límites de bloques y se ignoran rangos fuera de la
ventana; una respuesta estructurada vacía conserva una sección de la ventana.
Los textos se reconstruyen desde el original y se subdividen localmente cuando
superan el máximo. Las secciones solo de espacios no generan vectores.

## Persistencia y reemplazo

`ArcadeDBDocumentEmbeddingStore` implementa el puerto propio de la capa. Usa
`DocumentSemanticIndex`, secciones `DocumentEmbeddingSection_<config hash>` y
un índice nativo `LSM_VECTOR` con métrica `COSINE`. La persistencia comprueba
el original, el registro completo, las secciones y las conexiones dentro de la
transacción. El borrado habitual de documentos elimina todos estos derivados.

Sin `force`, se reutiliza el resultado completo para el mismo contenido, perfil
y configuración. Si cambiaron, se requiere reprocesamiento explícito. Con `force`,
primero se generan/validan todos los nuevos vectores; eliminar los anteriores e
insertar los nuevos ocurre en una sola transacción. Una falla conserva el índice
anterior. Repetir la persistencia del mismo artefacto no lo duplica. La solicitud explícita
de reprocesamiento de documento de la API también activa `force`; un reintento
del trabajo conserva su configuración original.

El resultado se marca `visualizable=false` en nodos/conexiones, de modo que el
visor de grafo no exponga los vectores como elementos visuales. En la base inicial
`origin/develop` aún falta integrar el commit previo `d8439f7` de metadatos y filtros
múltiples; esta marca no depende de que ese PR ya esté incorporado.

## CLI por documento

El comando requiere una base de procesamiento migrada y un workspace activo.
Usa el bloqueo del recurso para no competir con trabajos ni borrados activos.
No imprime texto ni vectores.

```sh
# Generar y conservar el artefacto sin escribir derivados en ArcadeDB.
python -m src.extractors.cli extract --extractor document_embeddings \
  --workspace UUID --document UUID

# Persistir un artefacto generado anteriormente, sin proveedor.
python -m src.extractors.cli persist --extractor document_embeddings \
  --workspace UUID --document UUID --run UUID

# Regenerar y reemplazar el índice existente.
python -m src.extractors.cli extract --extractor document_embeddings \
  --workspace UUID --document UUID --force --persist
```

No se recorren automáticamente documentos anteriores. La CLI no realiza DDL ni
escribe derivados en dry run, aunque lee el índice existente para evitar generación
repetida. Los artefactos se mantienen en el filesystem del workspace.

## Búsqueda interna

`store.search(vector, configuration, limit=10)` usa `vector.neighbors` del índice
compatible. Devuelve documentos únicos y los fragmentos recuperados, ordenados por
la menor distancia de sus secciones. Distancia menor significa mayor similitud;
no es confianza ni una afirmación de relación entre notas. Aumenta los candidatos
cuando varios resultados corresponden a una misma nota, hasta cubrir el límite de
documentos o agotar el índice. El resultado mantiene la naturaleza aproximada de
la búsqueda vectorial; no se fija un umbral de relevancia sin evaluación.

La futura capa de búsqueda generará el vector de consulta con el mismo modelo y
dimensiones y cargará el documento original usando los IDs recuperados. El motor
reflexivo podrá usar después esos documentos y fragmentos como contexto.

## Validación

Las pruebas unitarias usan el tokenizador real y proveedores simulados. Las
integraciones optativas usan ArcadeDB 26.9.1 aislado y comprueban búsqueda nativa,
deduplicación, rollback de reemplazo, idempotencia y eliminación del documento.
No constituyen evaluación de calidad temática ni prueba del proveedor OpenAI real.

```sh
EMBEDDINGS_TEST_ARCADEDB_URL=http://localhost:2487 \
EMBEDDINGS_TEST_ARCADEDB_PASSWORD=PASSWORD \
python -m pytest tests/integration/test_document_embedding_layer.py
```
