# Extractores independientes

- Ciclo común en `../use_cases/extraction/base.py`; contratos en `../core/extractors/`.
  Títulos se compone en `../bootstrap/documents.py`. `base.py`, `contracts.py` y
  módulos de títulos de esta carpeta conservan imports de compatibilidad.
  Las demás capas y el registro siguen aquí; `../processing/workflows.py` conecta
  el registro durable hasta la etapa 2.
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
