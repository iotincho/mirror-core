# Laboratorio / ejes personales

- Contrato vigente: [personal-axes-api](../../../docs/personal-axes-api.md).
  Para trabajo diferido consultar [pendientes](../../../docs/pending.md).
- Acceso exige interruptor global y permiso por cuenta. Consultar autorización
  antes de abrir el workspace o reservar jobs; no exponer esta mutación en API pública.
- Previews conservan muestra/hashes y TTL. No escriben la proyección activa.
  Ajustes mantienen historial acumulativo y cambio de muestra explícito.
- Aceptar fija una versión inmutable y su evidencia. Editar crea otra versión;
  rechazar aceptación concurrente sobre una versión base que ya cambió.
- Resultados e historial conservan identidad de versión/profile; pausar un eje
  no borra resultados. Usar la coordinación durable existente.
- Citas literales y voz de hallazgos se validan por separado; no inferir hechos
  personales para mejorar una descripción. Probar aislamiento de dueño y versión.
