# Ejes personales y Laboratorio

- Consultar [el contrato](../../../docs/personal-axes-api.md) y la prueba del
  recorrido afectado. Tipos y puertos están en `../../core/extractors/personal_axes/`;
  HTTP, SQL, archivos y grafo permanecen en sus adaptadores.
- Las versiones aceptadas son inmutables; una prueba temporal no modifica la
  proyección activa. Conservar snapshot, hash, identidad y propiedad del dueño.
- Las reservas capturan configuración en la transacción de aceptación; histórico
  reutiliza transacciones y retry de procesamiento. No introducir sesiones ORM ni
  mutar el extractor para resolver prioridad de escritura.
- Cubrir expiración, recuperación, aislamiento y competencia cuando corresponda;
  una prueba con puertos falsos no acredita locks o transacciones reales.
