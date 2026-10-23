# Procesamiento durable

- Leer [runtime](../../docs/processing-runtime.md) para transporte/leases y
  [jobs](../../docs/extractor-jobs.md) para coordinación por capa; no ambos por defecto.
- PostgreSQL decide estado y reintentos. Conservar atomicidad job/evento/outbox,
  generación, fencing, heartbeat, checkpoints y orden de locks por recurso/capa.
- Taskiq entrega ID/generación y usa ACK manual. No agregar un retry independiente.
- La configuración queda fijada al aceptar el job. Workflows históricos mantienen
  su semántica; no añadir nuevas llamadas LLM al retomar un job anterior.
- Retry conserva IDs/artefactos; reprocess crea una ejecución nueva. Persistencia
  recupera el artefacto sin crear proveedor. Los hijos completados no se repiten.
- `workflows.py` compone; casos de uso en `../use_cases/` orquestan.
- Un cambio de concurrencia requiere integración PostgreSQL aislada: duplicados,
  lease vencido, cancelación, pérdida de entrega y fallo parcial relevantes.
  Un test simulado de transporte no prueba las transacciones ni locks reales.
