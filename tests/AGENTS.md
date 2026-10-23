# Validación

- Elegir suite en [pruebas](../docs/development/testing.md). Usar
  `.venv/bin/python -m pytest <archivo>` desde la raíz.
- Probar comportamiento observable y fallos reales; no reflejar detalles privados
  de implementación. Reutilizar fixtures locales antes de crear infraestructura nueva.
- Material sintético y temporales por test. Proveedores determinísticos por defecto;
  sin llamadas reales a OpenAI, Resend o push para una suite ordinaria.
- Integraciones son opt-in con servicios aislados. Leer variables/fixtures del test;
  nunca conectar a bases de usuarios. Informar skips y servicios no verificados.
- Si cambia durabilidad cubrir respuesta perdida, duplicado, fallo parcial y replay
  sin repetir proveedor. Para aislamiento incluir otro usuario.
- Ejecutar primero los tests afectados; ampliar por fronteras cambiadas. No repetir
  una suite aprobada sin cambios nuevos o dudas concretas.
