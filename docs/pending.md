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

## Validaciones que los informes dejaron abiertas

- [ ] PWA: aceptación visual entre 320 y 1440 px, textos/listas/grafos densos,
  scroll de diálogos, foco/teclado, contraste, texto ampliado y áreas seguras.
  Verificar navegación, captura/fecha, material, lectura y Laboratorio.
- [ ] Safari/iOS y Chrome/Android reales, en navegador y PWA instalada:
  IndexedDB, recuperación de borradores, descargas/importación y aislamiento al
  cerrar sesión/cambiar de cuenta.
- [ ] Audio real: codecs, finalización/reproducción, bloqueo de pantalla, cambio
  de aplicación, llamada, permisos revocados, cierre/reapertura, falta de espacio
  y desconexión. Comprobar conservación de originales y recuperación.
- [ ] Web Push con VAPID persistente y origen HTTPS: recepción y apertura con app
  abierta/cerrada, permisos denegados, sesión vencida, horario, red interrumpida,
  logout/cambio de cuenta y borradores/adjuntos. La aceptación del transporte no
  acredita recepción. Referencia: [invitaciones](exteriorization-notifications.md).
- [ ] Evaluación con LLM real de criterios/hallazgos de ejes y su voz lingüística:
  voseo, tuteo, ustedeo y texto sin señales regionales, sin alterar citas ni atribuir
  hechos ausentes. Evaluar también títulos y segmentación/embeddings con muestras
  controladas. Las pruebas determinísticas no acreditan utilidad editorial.
- [ ] Administración en el destino: acceso desde otro dispositivo LAN, bindings,
  hosts/firewall, aislamiento frente al origen público y cobertura del inventario.
- [ ] Aceptación integrada sobre HTTPS con versiones identificadas y recorridos
  reales de notas, audio, recuperación y notificaciones. Revalidar las comprobaciones
  de cada contrato; no arrastrar como pendiente un merge/deploy sólo porque un
  informe antiguo lo marcaba así.

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
