# Documentación del backend

Entrar por [el mapa](development/repository-map.md), leer el contrato del área y
ampliar sólo si la tarea lo requiere. No cargar este directorio completo como
contexto. Las guías describen código implementado; no acreditan despliegue.

## Desarrollo y agentes

- [Mapa de módulos y pruebas](development/repository-map.md).
- [Reglas de implementación y fronteras](development/implementation.md).
- [Arquitectura, responsabilidades y criterios para nuevos módulos](../ARCHITECTURE.md).
- [Plan de migración hexagonal](development/hexagonal-migration-plan.md): etapa 0
  completada, piloto pendiente y ejes fuera del refactor interno inicial.
- [Chequeo de fronteras e inventario](development/architecture-checks.md).
- [Verificación y servicios aislados](development/testing.md).
- [Configuración de agentes y presupuesto de contexto](development/agents.md).
- [Instrucciones comunes](../AGENTS.md) y [README del proyecto](../README.md).

## Contratos y operación por tema

| Tema | Referencia principal | Complemento |
| --- | --- | --- |
| Runtime durable | [processing-runtime](processing-runtime.md) | [Eventos PWA/SSE](processing-pwa-events.md) |
| Ingestión diferida | [deferred-ingestion](deferred-ingestion.md) | [Reprocesamiento](reprocess-notes.md) |
| Extractores independientes | [extractor-jobs](extractor-jobs.md) | [Migraciones de datos](data-migrations.md) |
| Emociones | [emotion-extractor](emotion-extractor.md) | [Navegación y grafo](../src/graph/README.md) |
| Embeddings | [document-embeddings](document-embeddings.md) | La búsqueda HTTP anterior sigue retirada |
| Títulos | [document-title-extractor](document-title-extractor.md) | Generación independiente y títulos al leer |
| Laboratorio / ejes | [personal-axes-api](personal-axes-api.md) | Versiones, pruebas, resultados e historial |
| Originales / respaldos | [document-archives](document-archives.md) | [Recuperación de audio](audio-transcription-recovery.md) |
| Registro / workspace | [signup](signup.md) | [Recuperación de contraseña](password-recovery.md) |
| Invitaciones / push | [exteriorization-notifications](exteriorization-notifications.md) | [Respuestas de voz](audio-invitation-replies.md) |
| Centro de notificaciones | [notification-center](notification-center.md) | Lectura persistente, independiente del canal push |
| Administración | [Operación y contrato LAN](admin-lan.md) | API separada, inventario y permisos |
| Observabilidad | [sentry](sentry.md) | Configuración por proceso y privacidad |
| Publicación de imagen | [production-image-publishing](production-image-publishing.md) | Workflow junto a `Dockerfile.prod` |

Los documentos de runtime, ingestión y eventos conservan detalles de entregas
anteriores: para selección de capas y workflow actual prevalece `extractor-jobs`;
para cada capa, su contrato. Ante contradicción contrastar código y pruebas y
actualizar la referencia afectada, sin inferir estado de producción.

## Trabajo diferido

[Pendientes consolidados](pending.md) reúne funciones diferidas y verificaciones
que quedaron abiertas. Revisar vigencia antes de tomar una tarea y eliminarla
cuando se resuelva. No constituye una autorización de implementación.

## Mantener esta documentación

Actualizar el contrato principal cuando cambia comportamiento; el mapa cuando
cambia una responsabilidad. Eliminar planes resueltos e informes que ya no aporten
un procedimiento vigente, rescatando sólo pendientes explícitos en `pending.md`.
No conservar copias históricas de visiones reemplazadas. Los documentos nuevos
de primer nivel deben figurar en este índice.

Verificar enlaces locales y presupuesto de instrucciones con
`python3 scripts/check_repo_docs.py`; CI ejecuta el mismo comando sin servicios.
