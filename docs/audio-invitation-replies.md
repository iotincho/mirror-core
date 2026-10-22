# Respuestas de audio a la pregunta diaria

El backend acepta respuestas de audio mediante el flujo existente de procesamiento
diferido. La integración visual de la PWA es una etapa posterior.

## Contrato

`POST /v2/audio-notes` admite el campo multipart opcional `invitation_id` (UUID),
junto con `file`, `authored_at` opcional y el header obligatorio `Idempotency-Key`.
El identificador debe pertenecer al usuario autenticado. Una invitación inexistente
o de otra cuenta devuelve 404 antes de reservar o guardar el audio; un UUID inválido
devuelve 422.

`audio_note` en la respuesta y `GET /v2/audio-notes/{id}` exponen `invitation_id`,
con valor `null` para audio sin pregunta. Omitir el campo conserva la identidad
idempotente de los uploads anteriores. Reutilizar una clave con otra asociación
(incluido quitar una asociación existente) devuelve 409.

## Persistencia y recuperación

- La asociación queda fijada en el recibo SQL de aceptación y en los metadatos JSON
  del audio. Recuperar una aceptación interrumpida reconstruye esos metadatos desde
  el recibo.
- La transcripción genera el documento con el mismo UUID del audio y agrega
  `invitation_id` a sus metadatos. El contenido contiene solamente la transcripción;
  no se incorpora la pregunta al texto ni se modifica la selección de extractores.
- Después de persistir el documento original y su base en el grafo, el vínculo en
  `invitation_responses` se confirma en la misma transacción que el procesamiento
  hijo. Los reintentos reutilizan la transcripción y no duplican el vínculo.
- La aceptación del upload no significa que la transcripción esté lista. Si falla,
  el audio y su asociación se conservan para el mecanismo de reintento existente.

No requiere nuevas tablas ni migraciones: usa el manifiesto JSON del recibo, los
metadatos del audio y la tabla existente de respuestas. Los audios anteriores se
leen con `invitation_id=None`. Desplegar el backend antes de habilitar el envío
de este campo desde la PWA.

## Validación local

Con una base PostgreSQL aislada y migrada, ejecutar:

```sh
PROCESSING_TEST_DATABASE_URL='postgresql+asyncpg://...' .venv/bin/python -m pytest \
  tests/integration/test_audio_invitation_processing.py \
  tests/integration/test_deferred_ingestion.py
```

Los casos cubren el contrato HTTP, aislamiento entre cuentas, aceptación interrumpida,
fallos del grafo, rollback de la asociación si falla el handoff al hijo, idempotencia
y compatibilidad con audio sin pregunta. Usan transcripción simulada y archivos
sintéticos; no prueban proveedores externos ni micrófonos reales.
