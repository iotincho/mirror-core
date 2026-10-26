# API pública

- Leer sólo la ruta y schema afectados; registro en `router.py`, composición en
  `../dependencies.py` y `../bootstrap/workspaces.py`. Las familias migradas se
  componen en bootstrap y exponen rutas bajo `../adapters/access/api/public/`.
- El proxy publica `/api`, pero las rutas internas no repiten el prefijo.
- Mantener autenticación, protección de origen de mutaciones y ownership.
  SSE valida sesión también durante el stream; no retener una sesión SQL abierta.
- Ingestión usa `/v2` e `Idempotency-Key`. Conservar la recuperación de una
  respuesta perdida y las respuestas 410 de rutas retiradas.
- No añadir proveedores, SQL de negocio o tareas durables en la ruta.
  No registrar endpoints administrativos aquí.
- Verificar contrato HTTP, errores seguros y usuario ajeno con la prueba cercana.
  Si cambia exposición/prefijo, incluir `tests/test_openapi_docs.py`.

Referencia: [mapa](../../docs/development/repository-map.md).
