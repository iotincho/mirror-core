# Disparadores de entradas · Contrato de backend

Contrato implementado en la primera etapa de Constelaciones v2. Una entrada
puede tener un disparador opcional que registra qué inició la escritura. El
backend admite una pregunta diaria o una emoción como disparador. La referencia
queda registrada en la entrada aceptada. El borrador y la captura se integran en
la etapa de PWA.

## Modelo y API

Usar `entry_trigger` como unión discriminada por `kind`. La ausencia del campo o
el valor `null` representan escritura libre. El cliente envía una variante por
entrada.

```json
{"entry_trigger":{"kind":"invitation","invitation_id":"<uuid>","question_id":"<uuid>"}}
```

```json
{"entry_trigger":{"kind":"emotion","emotion_key":"calma"}}
```

- **Invitación.** Reutilizar la validación vigente de propietario y variante.
  Omitir `question_id` conserva la resolución de la pregunta inicial. Una vez
  aceptada, la referencia incluye la variante resuelta cuando está disponible.
- **Emoción.** Usar la clave canónica que ya retorna el catálogo de emociones.
  Aplicar la normalización vigente del grafo a la identidad. La coincidencia
  de búsqueda es independiente de esa identidad. El grupo debe existir en el
  workspace autenticado al aceptar por primera vez. El servidor conserva la
  clave y una etiqueta de presentación para la lectura histórica. La etiqueta y la cantidad de notas pueden cambiar en la
  proyección sin cambiar el disparador de una entrada aceptada. La consulta de
  aceptación lee sólo etiquetas de emociones con membresía y pagina por el
  límite del grafo. Devuelve `404 entry_trigger_emotion_not_found` si el grupo
  desapareció y `503` ante una lectura no disponible o parcial.
- **Destino y procedencia.** Mantener `journal_reference` para el destino y
  `source` para la procedencia técnica. La emoción es un contexto de captura.
  Las conexiones de Constelación siguen viniendo de la extracción sobre el texto.
  El disparador de emoción no completa invitaciones, habilita feedback de pregunta
  diaria ni genera una relación de emoción en el grafo.

Aceptar el objeto en `POST /v2/documents` para JSON y como campo JSON de multipart
en `POST /v2/documents/files` y `POST /v2/audio-notes`. Exponerlo como objeto
opcional en las respuestas de aceptación y las lecturas de documento y audio.
La integración de PWA enviará la misma referencia en texto y adjunto de una
captura conjunta, según el modelo de originales actual. El documento derivado de audio hereda el
disparador del audio, incluido el reintento de transcripción.

## Compatibilidad e identidad durable

1. **Normalizar al ingresar.** Las solicitudes existentes con `invitation_id` e
   `invitation_question_id`, incluso sus representaciones históricas, pasan al
   mismo flujo de validación de invitación. Si llegan ambos contratos, exigir
   equivalencia. Una discrepancia de asociaciones o reutilizar una clave con un
   disparador distinto devuelve 409. Una forma inválida o un tipo desconocido
   devuelve 422. Una referencia de otra cuenta o inexistente devuelve 404.
   La API deriva cuenta y workspace de la sesión.
2. **Conservar los recibos previos.** Los envíos libres y las invitaciones
   existentes conservan su representación para el hash vigente. La respuesta
   puede proyectar la variante tipada al leer sus campos históricos. Si un
   original histórico carece de variante, mostrar lo que se guardó y evitar
   reconstruirla a partir del estado actual de la pregunta.
3. **Fijar antes de procesar.** Resolver el disparador de emoción al aceptar por
   primera vez y guardar su identidad y etiqueta en el manifiesto de aceptación
   y en los metadatos del original. Usar el tipo y la clave canónica como parte
   de la identidad del envío. En un replay comparar con la referencia del recibo
   y reutilizar el original y la etiqueta aceptada. Recuperar una aceptación
   interrumpida o un audio en procesamiento desde el manifiesto, sin consultar
   de nuevo la emoción ni repetir la transcripción para restaurar metadatos.
   Los procesos antiguos pueden leer los originales. Actualizar worker, dispatcher
   y API antes de habilitar el envío desde la PWA, para que todos los escritores
   preserven el nuevo metadato. El cambio usa JSON existente y no requiere migración.
4. **Preservar contexto local.** Guardar el disparador junto al borrador, la
   sesión de grabación y la operación pendiente de sincronización. Tras cambiar
   de cuenta, conservar el aislamiento de los borradores. Si la emoción deja de
   estar disponible antes de la primera aceptación, conservar texto, audio y
   contexto en el dispositivo. Mostrar una recuperación explícita. Guardar como
   escritura libre, si se ofrece, requiere decisión de la persona y una operación
   nueva tras confirmar que el envío anterior quedó rechazado.
5. **Respaldos y borrado.** El formato de respaldo existente conserva el disparador
   en los metadatos. Al importar, se conserva como contexto histórico y los
   originales se asignan a la cuenta autenticada. No se busca el grupo en el
   grafo ni se otorgan permisos sobre el workspace original. La desaparición de
   un grupo tras un reprocesamiento no borra el disparador de entradas aceptadas.
   Invitaciones y Journals conservan su contrato de importación.

## Validación y conexión con PWA

La validación se conecta al puerto de lectura por workspace durante la
composición. El caso de ingestión conserva su reserva, manifiesto y escritura de
original. El procesador de audio recupera el disparador de los metadatos del
audio y lo copia al documento antes de persistir sus relaciones. La PWA debe
enviar la misma clave de idempotencia y el mismo disparador al reintentar un
envío incierto. En multipart, el campo es JSON. En el documento se persiste como
metadato reservado, y los uploads que intenten escribirlo directamente en
`metadata` reciben 422.

`tests/integration/test_deferred_ingestion.py` cubre texto, adjuntos, audio,
conflicto de origen, emoción que desaparece, replay con la etiqueta fijada y
recuperación del audio antes de escribir sus metadatos.
`tests/integration/test_daily_question_ingestion.py` cubre el replay entre
contratos y recibos históricos con y sin variante. Requieren PostgreSQL
desechable y proveedores sintéticos.

Referencias vigentes para la implementación: [Ingestión diferida](deferred-ingestion.md),
[Respuestas de audio](audio-invitation-replies.md), [Navegación del grafo](graph-navigation.md)
y [Respaldo e importación](document-archives.md).
