# Pregunta diaria · Evaluación y operación

La implementación local conserva `DAILY_QUESTION_MODE=curated`. La fase 5 tiene
dataset, runner, revisión y métricas, con una corrida real sintética ejecutada el
2026-10-30. Quedan pendientes revisión humana de calidad, aceptación en PWA
instalada/teléfono y habilitación de un entorno. No se modificó producción.
El [contrato](daily-question-v2-contract.md)
describe persistencia, límites y recuperación; el [plan](daily-question-v2-plan.md)
mantiene las validaciones pendientes.

## Dataset y criterio de evaluación

El [dataset versionado](../src/adapters/access/cli/daily_question_cases.json) contiene
**18 casos completamente sintéticos**: intención abierta, cierre/rechazo, mención
sin reapertura, intención explícita de retomar, pausa, silencio, límite de seguimiento,
variedad, falta de notas, importación antigua, contexto insuficiente, instrucciones
en una nota, voseo/tuteo/ustedeo, cierre posterior, intenciones contradictorias y
otro tema personal durante el descanso. Usa fechas e IDs ficticios estables.
La versión actual es `daily-question-eval-v2`; conserva compatibilidad de lectura
con v1. Corrige la fecha autoral del caso de pausa para representar una nota escrita
antes del descanso y subida después, sin confundirla con una intención nueva.
El runner consume únicamente ese archivo incluido en el paquete, sin recibir paths
de notas privadas ni consultar SQL, ArcadeDB o los workspaces del usuario.

Reutiliza el constructor de contexto y `SelectPreparedQuestions` de producción,
con puertos sintéticos, las mismas referencias/contratos/políticas y el adaptador
real cuando se solicita una corrida paga. No implementa un selector paralelo.

Los checks automáticos comprueban contrato, origen inicial esperado, cantidad de
grupos personales, temas excluidos y alternativa de catálogo. Las expectativas
son específicas de cada caso: elegir catálogo puede ser el resultado correcto.
No se usa la tasa de respuesta como objetivo.

La revisión humana evalúa seis dimensiones con `pass`, `fail` o `pending`:

| Dimensión | Criterio para `pass` |
| --- | --- |
| `grounded` | Se apoya en lo escrito y conserva incertidumbre; no inventa hechos o motivaciones. |
| `boundaries` | Respeta intención actual, cierre y rechazo; no cambia el nombre del tema para insistir. |
| `gentle_effort` | La variante suave permite responder brevemente sin reconstruir toda una historia. |
| `depth_progression` | Las tres profundidades exploran el mismo tema, con un aumento comprensible de profundidad. |
| `no_assumptions` | Una pregunta por variante, sin diagnóstico, explicación asumida ni obligación. |
| `language` | Conserva voseo, tuteo o ustedeo según el material, con tono cercano y natural. |

La evaluación combina checks específicos y juicio humano, siguiendo
[OpenAI Docs: evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
Las respuestas de referencia sirven para probar el mecanismo; no acreditan
la calidad de un LLM. Ningún comando cambia el modo operativo ni habilita usuarios.

## Recorrido local sin llamadas

Desde la raíz, con un nombre nuevo para el plan y la salida:

```sh
.venv/bin/python -m src.bootstrap.daily_question_evaluation plan \
  --mode reference --model reference \
  --output /tmp/daily-question-reference-plan.json
.venv/bin/python -m src.bootstrap.daily_question_evaluation run \
  --plan /tmp/daily-question-reference-plan.json \
  --output-dir /tmp/daily-question-reference
```

Produce `report.json`, `report.md`, `review.json` y recibos inmutables. El reporte
muestra material sintético, propuestas y selección, para poder revisar por qué
una pregunta fue descartada o elegida. Incluso si los checks están verdes,
`quality_validated` y `ready_to_enable` permanecen en `false` en este modo.
Este recorrido no carga credenciales ni crea clientes de proveedor.

## Preparar y ejecutar la evaluación real

Antes de correrla, elegir el ID exacto del modelo y verificar sus tarifas vigentes.
El plan exige modelo, presupuesto USD, tarifas de entrada/salida por millón y fuente
de esas tarifas. No estima precios de memoria ni elige un modelo implícito.
Reemplazar los valores en mayúscula de esta plantilla:

```sh
.venv/bin/python -m src.bootstrap.daily_question_evaluation plan \
  --mode live --model MODELO_ELEGIDO \
  --max-calls 16 --max-input-tokens 24000 --max-output-tokens 3000 \
  --budget-usd PRESUPUESTO_USD \
  --input-price TARIFA_ENTRADA --output-price TARIFA_SALIDA \
  --price-source FUENTE_Y_FECHA_DE_TARIFAS \
  --output /tmp/daily-question-live-plan.json
```

Los 18 casos actuales requieren como máximo **16 llamadas**: no se llama al modelo
si falta contexto o sólo hay una nota antigua. Ese límite reserva, conservadoramente,
hasta 384000 tokens de entrada y 48000 de salida. La reserva monetaria es
`max_calls × (input_cap × input_price + output_cap × output_price) / 1000000`.
Un presupuesto inferior impide crear el plan. Las tarifas son una declaración del
operador que debe comprobarse antes de autorizar, no facturación del proveedor.

El plan congela hashes de dataset e implementación, configuración y límites.
Cambiar código/casos requiere un nuevo plan. La API key se obtiene únicamente de
`OPENAI_API_KEY` en el entorno al ejecutar una corrida real; nunca se guarda en el
plan, los recibos o el reporte. No se lee `.env` desde este runner.

Con autorización específica de llamadas pagas y credencial preparada localmente:

```sh
.venv/bin/python -m src.bootstrap.daily_question_evaluation run \
  --plan /tmp/daily-question-live-plan.json \
  --output-dir /tmp/daily-question-live --allow-paid
```

No se agregan retries SDK. Antes de cada llamada se confirma un recibo de inicio;
una respuesta guardada se reutiliza al retomar. Si existe inicio pero no resultado,
la corrida se detiene como intento ambiguo: no vuelve a pagar automáticamente.
Un rechazo/error de proveedor conserva el intento consumido sin atribuir costo cero.
Los límites operativos globales del dispatcher son independientes de este presupuesto
de evaluación; el runner no modifica datos de aplicación.

Revisar `report.md` y completar `review.json`, sin cambiar `plan_id` ni
`results_sha256`. Después:

```sh
.venv/bin/python -m src.bootstrap.daily_question_evaluation review \
  --report /tmp/daily-question-live/report.json \
  --review /tmp/daily-question-live/review.json
```

La revisión debe corresponder a resultados exactos. Sólo una corrida `live` con
checks y dimensiones humanas aprobados acredita esa evaluación. `ready_to_enable`
sigue en `false`: falta la aceptación externa y la decisión operativa.

## Configuración compartida

Aplicar migraciones hasta **`20261029_22`** antes de iniciar esta versión. No migrar
un entorno con datos sin autorización. API, worker y dispatcher deben usar la misma
imagen/configuración y volumen de workspaces. Los Compose vigentes de core y deploy
comparten `env_file` entre esos procesos; no requiere un opt-in nuevo en la PWA.
Cambiar variables requiere recrear los procesos que las consumen; settings/clientes
están cacheados por proceso.

Además de los límites de modelo/contexto del [contrato](daily-question-v2-contract.md):

| Variable | Default y rango |
| --- | --- |
| `DAILY_QUESTION_MAX_FOLLOWUPS` | 1; 1–14. |
| `DAILY_QUESTION_REST_DAYS` | 7; 1–90. |
| `DAILY_QUESTION_SILENCE_HOURS` | 48; 1–720. |
| `DAILY_QUESTION_GENERAL_EVERY` | 4; 2–14. |
| `DAILY_QUESTION_MAX_CALLS_PER_DAY` | 1000; 0–100000, global por día UTC. |

Cada intento reservado, incluso con resultado desconocido, consume cuota diaria.
La admisión se serializa en PostgreSQL entre propietarios y workers; excederla
produce `question_daily_call_limit` y permite usar catálogo. Cero impide nuevos
intentos pagos desde el runtime. No es un tope monetario de la cuenta OpenAI.

Modelos, versiones y límites aceptados quedan en el job; la política se incorpora
al snapshot de preparación. La publicación aplica la política operativa actual y
la congela en la invitación. Feedback histórico usa esa política congelada, aunque
después cambie el descanso. La cuota global actual puede restringir jobs anteriores.

## Métricas agregadas

Con el acceso operativo a PostgreSQL configurado, sin usar notas para diagnóstico:

```sh
.venv/bin/python -m src.bootstrap.daily_question_evaluation metrics --days 7
```

Devuelve sólo agregados: preparaciones por modelo y a tiempo, decisiones del
finalizador, estados/fallos con códigos permitidos, intentos de proveedor, uso de
tokens conocido/reservado, latencia p95, orígenes iniciales y feedback explícito.
No devuelve propietarios, documentos, texto de preguntas, notas ni transcripciones.
Un inicial general puede ser variedad deliberada; no equivale por sí solo a fallback.

`unknown_outcome` y `unknown_usage` distinguen intentos no confirmados. Sumas de
tokens conocidas no incluyen el consumo desconocido; no se informan dólares sin
tarifas verificadas y `cost_usd` queda `null`. Las reservas de tokens permiten
estimar una cota conservadora con las tarifas del modelo correspondiente.
Los recibos se confirman bajo fencing. Si falla la persistencia de métricas después
de guardar propuestas, el retry recupera el artefacto y su uso sin volver a generar.

Métricas y recibos de llamadas se conservan 90 días y se limpian en lotes de 500.
Sobreviven a la eliminación de preparaciones/artefactos de 36 horas. La migración
no inventa métricas históricas ni backfill; downgrade pierde estas métricas,
conservando invitaciones/respuestas/feedback y procedencia de la fase 4.

## Habilitación, rollback y aceptación externa

Orden operativo, sujeto a autorización de migración/despliegue:

1. Migrar esquema y publicar API compatible en `curated`; mantener el mismo modo
   en worker y dispatcher. Instalar la PWA compatible con paquetes/feedback.
2. Aprobar la evaluación real y confirmar modelo, límites y cuota diaria para
   todos los procesos. Conservar imagen/configuración anterior para reversión.
3. Cambiar `DAILY_QUESTION_MODE=personalized` y recrear worker/dispatcher/API.
   Se aplica automáticamente a quienes ya habilitaron invitaciones; las preferencias
   apagadas siguen apagadas. No cambia el permiso de push.
4. Observar preparación a tiempo, errores, cuotas, latencia, reservas/uso y feedback.
   Ante falta de contexto, proveedor fallido o resultado tardío debe aparecer catálogo
   sin duplicar la ocurrencia ni el push.
5. Para volver al catálogo, usar `DAILY_QUESTION_MODE=curated` y recrear esos procesos.
   Se omite el selector personalizado y los jobs pendientes no inician generación.
   No borrar tablas, paquetes, respuestas ni feedback para hacer rollback.

La aceptación en dispositivo sigue pendiente: push programado y de prueba con sesión
real, app cerrada/abierta, texto y voz, nota pendiente de subir, recuperación de audio,
otra cuenta, cierre del modal y actualización de PWA instalada durante grabación.
La actualización debe quedar esperando sin activar ni recargar hasta resolver el audio.
`verify:build`, pruebas de DOM y un navegador headless no sustituyen esta aceptación.

## Evidencia local y límites

Los 18 casos de referencia verifican estructura/políticas; las pruebas SQL cubren
fencing, metadata perdida sin nueva llamada, cuota concurrente entre propietarios,
uso desconocido, política histórica y rollback sin borrar feedback. El wheel incluye
dataset, entrypoint y adaptador sintético. Las migraciones se verifican en PostgreSQL
descartable; no acreditan despliegue. Los resultados de la entrega están registrados
en el [contrato v2](daily-question-v2-contract.md). La prueba antes omitida de
entregas duplicadas pasó con dos workers Taskiq y RabbitMQ aislados, sustituyendo
el push. Se mantiene pendiente la aceptación real en dispositivo.

## Corrida real sintética · 2026-10-30

Se usó `gpt-6-luna` y la credencial OpenAI de `.env.local`, con autorización de
hasta USD 0,50, sin enviar notas privadas ni cambiar esa configuración. El prompt
fue `daily-proposals-v1`; no se ajustó el motor para forzar el resultado.

La primera corrida obtuvo 17/18: en `pause`, la nota afirmaba que quería escribir
sobre el tema y era posterior a la restricción, por lo que reabrirlo era válido
según la política acordada. La expectativa del fixture era contradictoria. Se
conservó esa evidencia y se corrigió el caso en v2: autoría previa a la pausa,
aceptación posterior. Una llamada adicional confirmó que esa subida tardía no reabre
el tema. Los demás resultados se reutilizaron después de comprobar igualdad exacta
de entrada y configuración, sin pagar de nuevo.

El resultado automático corregido fue **18/18**. En total se hicieron **17 llamadas**
con uso conocido: 16478 tokens de entrada y 6839 de salida. A tarifas estándar
publicadas de USD 0,10/0,50 por millón, la estimación sin descuento de caché es
**USD 0,0050673**; no constituye una lectura de facturación.
[OpenAI Docs: modelo y tarifas](https://developers.openai.com/api/docs/models/gpt-6-luna).
La reserva conservadora acumulada de ambos planes fue USD 0,0663, bajo el tope autorizado.

La revisión preliminar del asistente detectó margen editorial: algunas preguntas
son repetitivas o poco naturales. Los checks no acreditan naturalidad ni aprobación
humana; la revisión permanece pendiente, igual que dispositivo y habilitación.
Los reportes guardan procedencia por caso y distinguen respuestas nuevas de reutilizadas.
