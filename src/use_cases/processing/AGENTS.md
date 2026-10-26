# Procesamiento durable

- Leer [runtime](../../../docs/processing-runtime.md) para transporte/leases y
  [jobs](../../../docs/extractor-jobs.md) para coordinación por capa; no ambos por defecto.
- PostgreSQL decide estado y reintentos. Conservar atomicidad job/evento/outbox,
  generación, fencing, heartbeat, checkpoints y orden de locks por recurso/capa.
- Taskiq entrega ID/generación y usa ACK manual. No agregar un retry independiente.
- La configuración queda fijada al aceptar el job. Workflows históricos mantienen
  su semántica; no añadir nuevas llamadas LLM al retomar un job anterior.
- Retry conserva IDs/artefactos; reprocess crea una ejecución nueva. Persistencia
  recupera el artefacto sin crear proveedor. Los hijos completados no se repiten.
- Contratos y registros sin ORM en `../../core/processing/`; casos durables en
  `./`; SQL/eventos/recibos en `../../adapters/storage/postgres/`.
  `../../bootstrap/workflows.py` registra versiones y extractores;
  `../../bootstrap/processing.py` inyecta puertos y hooks de compatibilidad con ejes.
  Los entrypoints externos conservados sólo delegan a bootstrap.
- Un cambio de concurrencia requiere integración PostgreSQL aislada: duplicados,
  lease vencido, cancelación, pérdida de entrega y fallo parcial relevantes.
  Un test simulado de transporte no prueba las transacciones ni locks reales.
