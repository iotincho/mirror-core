# Persistencia y navegación del grafo

`ArcadeDBGraphStore` conserva y borra documentos originales, expone el puerto de
comandos de la base del workspace y lee vecindarios para el visor de la PWA.
No ejecuta extracción, embeddings, reflexión ni análisis de Constelación.

El esquema base de ArcadeDB crea `Document` y el registro administrativo
`SchemaMigration`. Cada extractor administra el esquema y las escrituras de su
capa; el ejemplo implementado es [emociones](../../docs/emotion-extractor.md).
Las escrituras de documentos verifican identidad y contenido en una transacción.
El borrado elimina el documento y sus nodos derivados identificados por
`document_id`, junto con sus aristas.

## Contrato del visor

`GET /documents/{document_id}/links` requiere sesión y documento del workspace.
Acepta `offset`, `limit` (1 a 40) y `relation_type`. Devuelve `LinkNeighborhood`
definido en [contracts.py](contracts.py), con vecinos, total, siguiente offset,
relaciones y evidencia. No crea relaciones. Sin `CROSS_DOCUMENT_LINK`, devuelve
un vecindario vacío. La limpieza puede dejar sólo documentos en el grafo.

La consulta de relaciones acepta tipos de extremos arbitrarios. Los nombres
JSON `source_claim_id` y `target_claim_id` se mantienen para compatibilidad del
visor, sin importar modelos ni exigir vértices históricos `Claim`. Las relaciones
simétricas se leen una vez; las dirigidas mantienen su orientación. La hidratación
se limita a 500 relaciones por página y señala resultados incompletos mediante
`links_truncated`.

## Grafo de extracciones

El visor usa `GET /documents/{document_id}/graph`, con `layer` opcional. Devuelve
`ExtractionGraph`: nodo raíz, nodos conectados, aristas con dirección y capas
disponibles para esa nota. Todos los accesos se hacen en la base del workspace
autenticado y se comprueba primero la existencia del original.

La vista muestra conexiones inmediatas entrantes y salientes etiquetadas con capa.
Los contenedores de ejecución identificados por `artifact_hash` se ocultan; sus
entidades hijas se proyectan directamente sobre la nota. Así `Document →
EmotionExtraction → Emotion` se presenta como `Document → Emotion`, manteniendo
la identidad de las entidades, aristas, profile y citas guardadas. No se crean ni
modifican relaciones para visualizar. Los IDs se califican por tipo para evitar
colisiones entre modelos de extractores distintos.

Los filtros salen de las capas conectadas, incluyendo una extracción vacía válida.
`Todas` muestra el conjunto completo; un filtro conserva la nota y las conexiones
de esa capa. No se elige una ejecución vigente ni se agrega un gestor de versiones.
La vista no tiene el límite anterior de 40 nodos ni expande otras notas de forma
recursiva. Una respuesta truncada de la base falla explícitamente, evitando mostrar
un resultado parcial como completo. La ruta `/links` se conserva por compatibilidad.


## Validación

Las pruebas de navegación cubren el contrato HTTP y el adaptador. Las integraciones
opt-in crean bases aisladas usando `EMOTIONS_TEST_ARCADEDB_URL` y
`EMOTIONS_TEST_ARCADEDB_PASSWORD`; verifican documentos, la capa de emociones y
navegación sin modelos históricos. La limpieza se prueba por separado con fixtures
de esquemas históricos, fuera del runtime.
