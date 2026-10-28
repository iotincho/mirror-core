# Pendientes consolidados

Revisión documental del 2026-10-23. Reúne pendientes explícitos de los planes e
informes eliminados, descartando los que ya cubren los contratos actuales.
No constituye autorización de implementación ni una afirmación sobre el estado
del despliegue. Revalidar cada punto al tomarlo y quitarlo al resolverlo; las
decisiones y contratos definitivos se documentan en su referencia específica.

## Funcionalidad diferida

- [ ] Definir una API general para elegir extractores y solicitar dry run o
  persistencia de un artefacto, más allá de los recorridos específicos de
  Laboratorio. Conservar configuración aceptada, idempotencia y límites por dueño.
  Referencia: [trabajos por extractor](extractor-jobs.md).
- [ ] Definir controles de ejecución/reintento por capa en la PWA. La API de
  estados/retry por hijo ya existe; no volver a implementarla como tarea pendiente.
- [ ] Decidir autenticación, sesiones y roles del panel administrativo si se amplía
  su alcance LAN actual. Incluir revocación efectiva y tratamiento de cuentas Google;
  no confundirlo con el permiso de Laboratorio ya implementado.
- [ ] Diseñar por separado operaciones administrativas: bloqueo/desbloqueo con
  motivo, revocación de sesiones, auditoría, detalle/reintento de procesamientos y
  acciones masivas. Resolver efectos sobre jobs/invitaciones, confirmaciones,
  idempotencia y permisos; evaluar MFA/step-up para operaciones sensibles.


## Operación por definir o medir

- [ ] Retención/limpieza de eventos y outbox, métricas de operación y capacidad/HA
  del broker según necesidad. La persistencia actual no acredita alta disponibilidad.
- [ ] Medir SSE con muchas conexiones y ajustar proxy/worker/pools a partir de
  carga real. Referencias: [runtime](processing-runtime.md) y
  [eventos PWA](processing-pwa-events.md).

Los planes de capas, administración, rediseño e informes de Laboratorio/push
originaron estos puntos. No se trasladan como trabajo vigente los experimentos
de Alex, la extracción/reflexión genérica retirada ni funcionalidades ya entregadas
como el frontend de Laboratorio, las vistas por capa y el reprocesamiento masivo.
