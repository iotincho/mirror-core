# Extractores independientes

- Partir de `base.py`, `contracts.py` y la capa afectada. Registro en `registry.py`;
  composición concreta en `../processing/workflows.py`.
- Separar extracción y persistencia. `dry_run` no escribe el grafo; conservar
  artefacto, profile, configuración y hashes para persistir sin repetir proveedor.
- Validar citas/offsets contra el original completo. No normalizar el texto fuente
  silenciosamente ni truncarlo para satisfacer un modelo.
- Cada capa administra esquema y reemplazo atómico de su proyección. No eliminar
  documentos, resultados de otra capa ni introducir nodos globales sin contrato.
- Probar resultados vacíos válidos, evidencia inválida, proveedor fallido y retry
  de persistencia; usar proveedor determinístico.
- Leer sólo el contrato de la capa: [emociones](../../docs/emotion-extractor.md),
  [embeddings](../../docs/document-embeddings.md) o [títulos](../../docs/document-title-extractor.md).
