# Respuestas de audio a la pregunta diaria

El backend acepta respuestas de audio mediante el flujo existente de procesamiento
diferido. La PWA puede asociar la grabación a la invitación al enviar el audio.

## Contrato

`POST /v2/audio-notes` admite `invitation_id` e `invitation_question_id` opcionales (UUID),
junto con `file`, `authored_at` opcional y el header obligatorio `Idempotency-Key`.
El identificador debe pertenecer al usuario autenticado. Una invitación inexistente
o de otra cuenta devuelve 404 antes de reservar o guardar el audio; un UUID inválido
devuelve 422.
Una variante necesita invitación y debe pertenecer a ella; una variante ajena es
404 y omitirla selecciona la pregunta inicial. Ver [paquetes v2](daily-question-v2-contract.md).

`audio_note` en la respuesta y `GET /v2/audio-notes/{id}` exponen ambos identificadores,
con valor `null` para audio sin pregunta. Los uploads sin invitación y los
recibos anteriores conservan su identidad idempotente. Reutilizar una clave con otra asociación
(incluido quitar una asociación existente) devuelve 409.

## Persistencia y recuperación

- La asociación queda fijada en el recibo SQL de aceptación y en los metadatos JSON
  del audio. Recuperar una aceptación interrumpida reconstruye esos metadatos desde
  el recibo.
- La transcripción genera el documento con el mismo UUID del audio y agrega
  ambos identificadores a sus metadatos cuando están presentes. El contenido contiene solamente la transcripción;
  no se incorpora la pregunta al texto ni se modifica la selección de extractores.
- Después de persistir el documento original y su base en el grafo, el vínculo en
  `invitation_responses` se confirma en la misma transacción que el procesamiento
  hijo. Los reintentos reutilizan la transcripción y no duplican el vínculo.
- La aceptación del upload no significa que la transcripción esté lista. Si falla,
  el audio y su asociación se conservan para el mecanismo de reintento existente.

La variante usa la migración aditiva `20261029_18`, además del manifiesto JSON y
los metadatos existentes. Los audios históricos sin variante se leen con ese campo
en `null`; los recibos v1 conservan su hash y admiten replay de la pregunta inicial.
Actualizar API/worker/dispatcher antes de habilitar el envío de variantes en PWA.

## Validación local

Con una base PostgreSQL aislada y migrada, ejecutar:

```sh
PROCESSING_TEST_DATABASE_URL='postgresql+asyncpg://...' .venv/bin/python -m pytest \
  tests/integration/test_audio_invitation_processing.py \
  tests/integration/test_daily_question_ingestion.py \
  tests/integration/test_deferred_ingestion.py
```

Los casos cubren el contrato HTTP, aislamiento entre cuentas, aceptación interrumpida,
fallos del grafo, rollback de la asociación si falla el handoff al hijo, idempotencia
y compatibilidad con audio sin pregunta. Usan transcripción simulada y archivos
sintéticos; no prueban proveedores externos ni micrófonos reales.
