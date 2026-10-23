# Grafo y adaptador ArcadeDB

- Leer [README local](README.md) y el contrato afectado. El store base conserva
  documentos y lecturas; cada extractor posee su esquema y proyección.
- Mantener SQL/Cypher y detalles ArcadeDB dentro del adaptador/persistencia de capa.
  No importar clientes concretos desde casos de uso.
- Resolver siempre base/credenciales desde workspace. No crear conexiones globales
  con credenciales root para atender lecturas de usuarios.
- Las proyecciones de lectura no crean relaciones. Conservar identidad, dirección,
  citas, paginación y señales de truncamiento; no presentar parcial como completo.
- No reintroducir modelos Concept/Claim o búsqueda/reflexión retiradas por consultar
  planes antiguos. El contrato de emociones no implica equivalencia de sinónimos.
- Si cambia una transacción/consulta/esquema, usar integración ArcadeDB aislada
  además de pruebas del contrato HTTP y proyección.
