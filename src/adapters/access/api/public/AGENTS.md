# API pública

- Leer sólo la ruta y schema afectados. La composición está en
  `../../../../bootstrap/public_router.py` y `public_dependencies.py`.
  Los routers reciben dependencias; no importar bootstrap ni storage desde acceso.
- El proxy publica `/api`, pero las rutas internas no repiten el prefijo.
- Mantener autenticación, protección de origen de mutaciones y ownership.
  SSE valida sesión también durante el stream; no retener una sesión SQL abierta.
- Ingestión usa `/v2` e `Idempotency-Key`. Conservar la recuperación de una
  respuesta perdida y las respuestas 410 de rutas retiradas.
- No añadir proveedores, SQL de negocio o tareas durables en la ruta.
  No registrar endpoints administrativos aquí.
- Verificar contrato HTTP, errores seguros y usuario ajeno con la prueba cercana.
  Si cambia exposición/prefijo, incluir `tests/test_openapi_docs.py`.

Referencias: [arquitectura](../../../../../ARCHITECTURE.md) e [índice](../../../../../docs/README.md).
