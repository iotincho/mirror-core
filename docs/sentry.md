# Sentry

La captura es opcional. `SENTRY_DSN=` mantiene Sentry desactivado; no se incluye
ningún DSN real en el repositorio. Para activarlo en producción:

```dotenv
SENTRY_DSN=<DSN del proyecto backend>
SENTRY_RELEASE=mirror-core@<version desplegada>
SENTRY_TRACES_SAMPLE_RATE=1.0
ENVIRONMENT=production
```

La API inicializa el SDK al importar el entrypoint. Cada proceso Taskiq lo
inicializa en WORKER_STARTUP; el dispatcher lo inicializa al arrancar. Comparten
proyecto y se distinguen con `service=api`, `processing-worker` y
`processing-dispatcher`. El Compose de mirror-deploy pasa estas variables a los
tres servicios. Recrear sus contenedores aplica la configuración nueva.

Se capturan errores inesperados/5xx de HTTP, rechazos 4xx en escrituras,
desconexiones de subidas observadas por ASGI, fallos del stream SSE, fallos de
workflows (incluidos reintentos), entregas del broker y excepciones del dispatcher.
Los cierres normales de SSE y la expiración de sesión durante un stream no se
reportan como incidentes. Las operaciones conservan sus estados, ACK y reintentos
actuales; un fallo de envío a Sentry no modifica el resultado de la operación.

Los tags técnicos incluyen operación, servicio, request_id, estado HTTP y, en
workflows, processing_id, recurso, etapa, intento y código seguro. El SDK conserva
el tipo de excepción y ubicaciones del stack, pero el filtro elimina sus mensajes
dinámicos, variables locales, cuerpo/headers/URL de la petición, usuario, extras,
breadcrumbs, contexto de SQL/proveedores y adjuntos. No habilita
profiling, integración OpenAI ni captura automática de logs. Los logs locales
existentes conservan sus tracebacks y no son alterados por este filtro.

Tracing está habilitado cuando hay DSN, con muestreo local predeterminado de 1.0
(100%). `SENTRY_TRACES_SAMPLE_RATE` acepta valores entre 0 y 1. Las peticiones
continúan el `sentry-trace`/`baggage` recibido desde la PWA, incluyendo su decisión
de muestreo. El filtro conserva trace_id/span_id tanto en errores como en
transacciones, elimina atributos y descripciones dinámicas y usa nombres de
funciones del backend. No propaga headers de tracing a proveedores externos.

Workers y dispatcher generan transacciones independientes para ejecutar trabajos
y publicar outbox. Se correlacionan por processing_id cuando corresponde; no se
añade contexto de tracing al contrato durable del broker.

Validación local sin red: `tests/test_observability.py` usa el SDK real con un
transporte en memoria. Comprueba configuración desactivada, correlación de un
rechazo HTTP y eliminación de datos privados antes del transporte. La llegada
real de eventos se verifica después de configurar y desplegar en producción;
Sentry puede estar bloqueado por red o filtros del cliente y no reemplaza los logs.
