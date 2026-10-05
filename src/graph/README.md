# Persistencia de grafo

ArcadeDB `26.9.1` es el graph store objetivo. Su schema se administra de forma explícita,
versionada e independiente del runtime mediante:

```bash
docker compose run --rm arcadedb-schema
```

Compose ejecuta el mismo inicializador antes de iniciar la API. La migración base crea los tipos,
propiedades, restricciones e índices vectoriales para la especificación de embeddings configurada.
El registro `SchemaMigration` usa la versión `v1:<embedding_suffix>`, por lo que una nueva
combinación de proveedor, modelo o dimensiones puede convivir con las anteriores.

La integración completa del store es opt-in para que la suite normal no dependa de Docker:

```bash
ARCADEDB_INTEGRATION=1 python -m pytest -q tests/integration/test_arcadedb_live.py
```

La prueba crea datos con IDs aleatorios, verifica idempotencia, embeddings, búsqueda, relaciones
y borrado, y limpia el documento temporal aun cuando una aserción falle.

La implementación runtime es `ArcadeDBGraphStore`. Usa Cypher para escrituras y recorridos del
grafo, SQL nativo para `vector.neighbors()` y transacciones HTTP para preservar atómicamente cada
extracción. Los casos de uso sólo dependen de los contratos de aplicación.
Las operaciones del store son async y usan `AsyncArcadeDBHTTPClient`; el cliente
síncrono queda para schema/administración. Lifecycle y límites están en
[Pipeline async](../../docs/async-pipeline.md).

## Modelo inicial

La fase de grafo persiste únicamente una extracción que ya fue validada contra el
contenido original. La escritura ocurre después de que el `ExtractionRun` se
guarda localmente; si el graph store falla, el documento y la corrida siguen disponibles,
pero la API responde `503` con el `run_id` para permitir reintento y diagnóstico.

```text
(:Document)-[:HAS_EXTRACTION]->(:ExtractionRun)
(:ExtractionRun)-[:EXTRACTED]->(:Concept | :Entity | :Claim)
(:Concept | :Entity | :Claim)-[:SUPPORTED_BY]->(:Evidence)-[:FROM_DOCUMENT]->(:Document)
(:Claim)-[:ABOUT | :RELATES_TO | :SUPPORTS | :CONTRADICTS]->(:Concept | :Entity | :Claim)
```

Todos los nodos extraídos están acotados al `run_id`: por ahora `autonomía` de
dos corridas distintas son dos nodos distintos. La canonicalización entre
documentos es una decisión futura y no debe mezclarse con la fidelidad de la
extracción inicial.

`Evidence` conserva la cita literal y su posición calculada por el backend.
Las relaciones semánticas contienen `run_id`, `document_id` y `evidence_json`;
esto permite inspeccionar su respaldo sin perder que la arista nativa representa
la relación (`ABOUT`, por ejemplo).

## Idempotencia y restricciones

El adaptador usa `MERGE` con IDs estables y crea restricciones únicas para
`Document`, `ExtractionRun`, `Concept`, `Entity`, `Claim` y `Evidence`. Repetir
la escritura de una misma corrida no duplica el subgrafo.

## Inspección manual durante la transición

ArcadeDB Studio queda disponible en `http://localhost:2480`. Las consultas Cypher de inspección
siguen siendo:

```cypher
MATCH (document:Document)-[:HAS_EXTRACTION]->(run:ExtractionRun)
RETURN document.id, document.source, run.id, run.profile_name, run.model
ORDER BY run.created_at DESC;
```

```cypher
MATCH (claim:Claim)-[relationship:ABOUT]->(concept:Concept)
RETURN claim.text, concept.name, relationship.evidence_json;
```

```cypher
MATCH (item)-[:SUPPORTED_BY]->(evidence:Evidence)-[:FROM_DOCUMENT]->(document:Document)
RETURN labels(item), item.local_id, evidence.quote, evidence.start_line, document.id;
```
