# TODO

Decisiones, hipótesis y mejoras que aparecen durante la POC pero no pertenecen
necesariamente a la etapa que está en curso. Cada punto debe convertirse en una
decisión explícita, un experimento o una tarea antes de implementarse.

## Notas de voz

- [ ] Diseñar la corrección de transcripciones. Debe preservar el audio y la
  transcripción literal originales, versionar toda corrección y reprocesar el
  documento sin sobrescribir silenciosamente la evidencia fuente.

## Búsqueda semántica

- [ ] Definir una política de relevancia para la recuperación vectorial. La
  búsqueda por vecinos cercanos siempre devuelve candidatos, incluso si la
  consulta no tiene relación con el corpus. Cuando haya más notas, reunir
  ejemplos de consultas relevantes e irrelevantes, medir la distribución de
  scores y decidir si corresponde un umbral, un margen entre resultados, u otro
  mecanismo. La API deberá poder devolver una lista vacía de forma explícita.

## Modelo de conocimiento

- [ ] Diseñar cómo relacionar y canonicalizar `Concept` entre corridas y
  documentos. No crear nodos globales ni embeddings de conceptos hasta validar
  una estrategia que no fusione ideas distintas silenciosamente.

## Exploración reflexiva

- [ ] Evaluar un flujo agéntico acotado que pueda profundizar en el grafo según
  un hilo de razonamiento: decidir qué relación o evidencia explorar, fijar un
  presupuesto de pasos y registrar cada decisión. No reemplazar la resolución
  actual de una sola pasada hasta poder evaluar si realmente mejora la utilidad.

- [ ] Diseñar contexto conversacional para explorar una idea en varios turnos.
  Debe conservar explícitamente preguntas, respuestas y `ReflectionRun` usados
  como contexto, sin mezclarlo con el material fuente ni permitir que el modelo
  trate mensajes previos como evidencia documental.
