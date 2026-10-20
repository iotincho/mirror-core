# Centro de notificaciones

Implementa mirror-pwa #46. El centro es una bandeja PostgreSQL por usuario, independiente
del permiso push, con novedades, onboarding y preguntas diarias. La vigencia por defecto
es **15 días** desde la publicación. Al vencer, el elemento deja de aparecer en el listado
y contador; esto no borra físicamente la fila ni la invitación o las notas vinculadas.

## Persistencia y estados

- `notifications`: contenido estable, acción tipada, propietario, deduplicación,
  publicación, ingreso efectivo a la bandeja, vencimiento, lectura y descarte.
- `notification_enrollments`: crea los pasos de onboarding una sola vez por usuario.
  Descartarlos o dejarlos vencer no vuelve a generarlos.
- `notification_announcements`: snapshot inmutable de una publicación y cursor durable
  de distribución por usuarios. El dispatcher existente distribuye lotes con locks
  `SKIP LOCKED`; el cursor y los destinatarios se confirman juntos.

Lectura y descarte son idempotentes. Leer no completa una acción. El avance de primera
reflexión se obtiene de una recepción durable aceptada; activar pregunta diaria, de la
preferencia existente. La instalación es un estado del dispositivo que resuelve la PWA,
sin completar globalmente ese paso para los demás dispositivos del usuario.

El contador incluye sólo avisos visibles sin leer. No representa tareas sin completar.
Las acciones son una unión cerrada; no se ejecutan URLs ni código remoto. El contenido
se muestra como texto. Una publicación global no admite una invitación privada como destino.

## API pública

El proxy expone estas rutas bajo `/api`; internamente FastAPI las registra sin ese prefijo.
Todas requieren autenticación. Las mutaciones validan el origen como exteriorización.

| Método y ruta pública | Comportamiento |
| --- | --- |
| `POST /api/notifications/bootstrap` | Inicializa onboarding una sola vez. 204. |
| `GET /api/notifications?cursor=…&limit=30` | No leídas primero; dentro de cada grupo, publicación e ID descendentes. Máximo 100. |
| `GET /api/notifications/summary` | `{ "unread_count": 3 }`. |
| `POST /api/notifications/{id}/read` | Primera lectura; 204. |
| `POST /api/notifications/read-all` | JSON `{ "through": "fecha-con-zona" }`; 204. |
| `POST /api/notifications/{id}/dismiss` | Retira el elemento del listado y contador; 204. |

El listado devuelve `items`, `next_cursor`, `unread_count` y `through`, usando la hora
del servidor. El corte para lectura masiva comprueba tanto publicación como ingreso
efectivo: no marca un aviso distribuido después del listado aunque su publicación sea
anterior. Un recurso ajeno devuelve 404; cursor o corte inválidos, 422.
Lectura/descarte de filas vencidas siguen siendo idempotentes para recuperar peticiones
pendientes. El endpoint de listado no crea notificaciones.
El cursor incorpora el grupo de lectura además de fecha e ID para preservar la prioridad
entre páginas. Marcar como leído mueve el aviso al grupo de leídos en la próxima consulta.

## Preguntas diarias

Habilitar `PUT /api/exteriorization/preferences` ya no exige suscripción ni VAPID.
La preferencia actual se conserva; no se habilita automáticamente a usuarios nuevos.
El scheduler genera una sola pregunta por usuario/fecha local aun sin dispositivos.
La invitación, su elemento de bandeja y los envíos existentes se confirman en la misma
transacción. Las pruebas manuales aparecen como «Pregunta diaria de prueba» en la bandeja,
con la misma pregunta e ID del push, pero no consumen la rotación ni habilitan el horario.
Reintentar una solicitud aceptada no duplica el aviso ni recupera uno descartado. Si una
prueba anterior a esta integración no tenía aviso, su replay lo incorpora conservando
fecha y lectura. La vigencia del aviso sigue siendo de 15 días; el envío de prueba, 5 minutos.

El plazo de push existente (hasta dos horas, limitado por medianoche local) continúa
siendo independiente de los 15 días del aviso. El historial puede abrir la pregunta y
vincular una respuesta después del vencimiento de envío. Abrir por push también marca
el elemento correspondiente como leído. No se modifican el worker del navegador ni
el procesamiento de notas para abrir desde la bandeja.

## Publicar una novedad

Agregar una entrada a `src/notifications/announcements.json`, con clave nueva y estable,
título, resumen y cuerpo. `action` es opcional. Si se omite `lifetime_days`, usa 15;
el campo admite 1–365.
El archivo está incluido en el paquete Python; también se puede indicar otro catálogo
con `--catalog /ruta/catalogo.json`.

```sh
.venv/bin/python -m src.notifications.cli preview notification-center-v1
.venv/bin/python -m src.notifications.cli publish notification-center-v1
```

`preview` no escribe y muestra contenido y cantidad elegible. `publish` persiste la
publicación; el dispatcher la distribuye en lotes de hasta 100 usuarios por ciclo.
Repetir la misma clave/contenido no duplica. Cambiar el contenido de una clave publicada
se rechaza: usar una clave nueva para otra comunicación. El vencimiento cuenta desde
la publicación, no desde cada reintento de entrega.

Se dirige a cuentas activas con espacio activo al distribuir, creadas antes de la
publicación; se incluyen cuentas antiguas cuya fecha de alta es desconocida. No se
promete un snapshot de cambios de estado de cuentas durante el recorrido de lotes.
No se reproducen novedades históricas para altas nuevas. No se publica automáticamente
el ejemplo al arrancar ni durante migraciones, y no se envían estas novedades por push.

## Despliegue y compatibilidad

1. Construir backend con la migración `20261020_12` y este código.
2. Aplicar `python -m alembic upgrade head` antes de iniciar API/dispatcher/workers nuevos.
   La migración incorpora invitaciones programadas de los últimos 15 días y conserva
   su primera apertura. Las pruebas y las más antiguas quedan fuera de la bandeja.
3. Publicar la PWA compatible. La versión anterior puede seguir leyendo el contrato
   de preferencias; su botón antiguo todavía combina registro push y habilitación diaria.
4. Previsualizar y publicar explícitamente las novedades deseadas.

No se requieren servicios ni variables nuevas en `mirror-deploy`. La bandeja y la pregunta
en la app funcionan con VAPID vacío. El push sigue requiriendo la configuración existente.
El rollback exige retirar primero la PWA nueva y los procesos nuevos antes de bajar la
migración; no ejecutar una versión de este código contra el esquema anterior.

## Validación

```sh
.venv/bin/python -m ruff check src tests migrations
NOTIFICATIONS_TEST_DATABASE_URL='postgresql+asyncpg://…/isolated_test' \
  .venv/bin/python -m pytest tests/test_notifications.py tests/integration/test_notifications_postgres.py
```

La integración usa una base explícita y aislada, migrada previamente. Cubre TTL de 15 días,
onboarding concurrente, vencimiento, propiedad, paginación, primera lectura, corte masivo
incluyendo distribución tardía, generación sin push, apertura histórica, avance separado
de lectura, distribución concurrente recuperable y rollback de la transacción.
Recepción push e instalación real siguen necesitando dispositivos compatibles.

### Evidencia local — 2026-10-20

- Suite completa con PostgreSQL temporal para notificaciones/invitaciones:
  **305 passed, 147 skipped**. Las omisiones corresponden a requisitos no habilitados
  del entorno, incluidas otras integraciones opt-in y pruebas del transporte push.
- Ruff y `git diff --check`: correctos.
- Migración `downgrade 20261016_11 → upgrade head` y `alembic check`: correctos.
  Con datos previos se verificó recuperación de invitación programada reciente,
  conservación de lectura, exclusión de pruebas/antiguas y vigencia de 15 días.
- CLI `preview notification-center-v1`: correcto, sin publicación al entorno real.
- PWA conectada a API/cookie/PostgreSQL reales mediante el fixture de integración:
  lectura entre dos sesiones, preservación de borrador, pregunta persistida,
  replay offline y lectura conservada después de recargar. La disponibilidad del
  workspace externo y el stream de procesamiento se simularon; el centro no.
- Las pruebas automatizadas usaron una base aislada. La CLI no publicó novedades
  en la base de la aplicación.
- La prueba manual confirmó recepción push y acceso al detalle del aviso en la app.
