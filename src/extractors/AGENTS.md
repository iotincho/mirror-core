# Extractores independientes

- Ciclo común en `../use_cases/extraction/base.py`; contratos en `../core/extractors/`.
  Títulos se compone en `../bootstrap/documents.py`; emociones/embeddings en
  `../bootstrap/extraction.py`, con persistencia en `../adapters/storage/arcadedb/`
  y proveedores en `../adapters/providers/openai/`. El registro concreto vive en
  `../bootstrap/extractor_registry.py`; los wrappers anteriores fueron retirados.
  `personal_axes/` mantiene su implementación interna pendiente de otro alcance.
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
