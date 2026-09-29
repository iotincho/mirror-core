# Embeddings semánticos

Cada carga completa dos representaciones semánticas, conservadas en ArcadeDB y
versionadas por proveedor, modelo y dimensiones:

- El documento original completo, para encontrar una nota aunque la extracción
  no haya producido el claim exacto.
- Cada `Claim.text` extraído, para recuperar evidencia puntual y alimentar las
  reflexiones sin perder su vínculo con el documento y sus líneas de soporte.

```text
(:Document)-[:HAS_EMBEDDING]->(:DocumentEmbedding)
(:Claim)-[:HAS_EMBEDDING]->(:ClaimEmbedding)
(:Claim)-[:SUPPORTED_BY]->(:Evidence)-[:FROM_DOCUMENT]->(:Document)
```

Los dos índices se mantienen separados por tipo y por especificación del
modelo. Esto impide comparar vectores incompatibles y conserva los vectores
anteriores de forma auditable cuando se cambia de modelo.

## Flujo

```text
ingesta → extracción → persistencia de grafo → embeddings de claims y documento
```

Si fallan los embeddings, el documento y su extracción siguen preservados, pero
la API informa que todavía no son recuperables semánticamente.

## Búsqueda

`POST /search` devuelve hasta `limit` resultados de ambos tipos, ordenados por
`score`. Cada elemento se identifica mediante `target: "document"` o
`target: "claim"`. Los resultados de documento contienen el texto original,
metadatos y fecha; los de claim conservan el run de extracción y las evidencias.

```bash
curl -X POST http://localhost:8000/search \
  -H 'content-type: application/json' \
  -d '{"query":"preocupación por perder libertad", "limit":10}'
```

`POST /search/claims` sigue disponible exclusivamente para las reflexiones, que
requieren candidatos con evidencia explícita. Un `score` sólo ordena material
potencialmente relacionado: no demuestra por sí solo un patrón.
