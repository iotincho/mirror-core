# Constelación: primer experimento entre documentos

## Hipótesis

La extracción fiel de cada nota más una comparación acotada de claims cercanos
puede producir conexiones útiles para formular preguntas sin interpretar la
identidad o la salud de la persona. Los documentos originales siguen siendo la
fuente de verdad. La base ArcadeDB de cada usuario delimita la búsqueda y las
aristas de su propia constelación.

## Qué se extrae

El perfil opcional `v5` conserva `Concept`, `Entity`, `Claim` y citas originales.
Agrega la posibilidad de una entidad con `type="emotion"` y el nombre que usó
la persona. `EXPRESSES_EMOTION` conecta el claim que la expresa con esa entidad.
`ABOUT`, `DESIRES`, `FEARS`, `VALUES`, `QUESTIONS`, `DECIDES` y
`ASSOCIATES_WITH` vinculan un claim con su referente cuando la relación aparece
en la nota. La evidencia de cada ítem y arista se resuelve contra el texto
original con el validador existente. Los perfiles anteriores permanecen
disponibles; la ingesta automática sigue usando `v4`.

La rueda de emociones es una **capa de normalización posterior**, todavía no
implementada. Para esta prueba se conserva la palabra original y se puede
comparar manualmente si una familia de la rueda ayudaría a explorar sin forzar
etiquetas. No se presupone que la emoción se conozca siempre.

## Cómo se conectan dos notas

`POST /documents/{document_id}/links` recibe un `run_id` completado. Por cada
claim de ese run genera un embedding y pide a ArcadeDB candidatos cercanos del
mismo perfil en **otros documentos de la misma base de usuario**. Deduplica
texto por documento y envía al comparador un claim y hasta cinco candidatos
con sus citas. El comparador puede devolver ninguna relación. Un ID ajeno a
los candidatos se rechaza. `SHIFTS` y `REVISITS` requieren `authored_at` distinto
en ambos documentos.

Las relaciones propuestas son `SAME_REFERENT`, `REVISITS`, `SHIFTS` e
`IN_TENSION`. Cada una conserva el ID de ambos claims y sus respectivas citas.
La respuesta incluye la similitud vectorial para auditar la selección; esa
similitud no se interpreta como prueba de la relación. Por defecto la operación
es de inspección (`persist=false`). Con `persist=true` se escribe una arista
`CROSS_DOCUMENT_LINK` con tipo, perfil y evidencia de ambos lados. Cada vínculo
conceptual se proyecta en dos aristas navegables con un `link_id` común:
`SAME_REFERENT` e `IN_TENSION` son recíprocas; `SHIFTS` se acompaña de
`SHIFTED_FROM` y `REVISITS` de `IS_REVISITED_BY`. En los dos últimos casos el
vínculo conceptual se ordena de la evidencia anterior a la posterior y requiere
fechas `authored_at` distintas. La arista queda visible para el contexto
reflexivo, pero sigue siendo una **propuesta**.
Una relación temporal o causal que no pueda sostenerse no se debe emitir.

ArcadeDB permite ejecutar `vector.neighbors()` y recorridos del grafo en el
mismo store. Se usa el índice vectorial para seleccionar candidatos y la
transacción HTTP para guardar las aristas en un lote, con IDs estables para
reintentos. No se hace una búsqueda agéntica en esta variante.

## Corrida reproducible

1. Aplicar la migración de esquema `v3` en cada workspace. El reconciliador de
   inicio lo hace para workspaces activos; el provisionador lo hace para nuevos.
2. Reextraer el mismo conjunto de notas con `profile="v5"`, conservando las
   corridas `v4` como línea base. Esperar a que sus embeddings estén listos.
3. Invocar el endpoint de links para cada `run_id` de `v5` con `persist=false`.
   Revisar las propuestas antes de repetir con `persist=true`.
4. Comparar con una tabla manual de pares esperados, pares dudosos y pares que
   **no** deberían relacionarse. Incluir emociones compartidas con situaciones
   distintas, un tema compartido sin referente común, cambios de postura y
   notas importadas con `created_at` posterior a `authored_at`.

```json
{"run_id":"<uuid-del-run-v5>","persist":false,"candidates_per_claim":5,"max_claims":20}
```

Medir precisión y cobertura de conexiones útiles, fusiones falsas, calidad de
preguntas posibles, costo por nota y porcentaje de claims sin candidatos. La
variante A es `v4` sin links; B agrega únicamente coincidencias de referentes
revisadas a mano; C es la comparación propuesta aquí. Una exploración agéntica
acotada quedaría como variante D sólo si C pierde conexiones importantes.

Para la parte cuantitativa, guardar las respuestas JSON y crear un archivo de
pares anotados como:

```json
[{"source_document_id":"<uuid-a>","target_document_id":"<uuid-b>","relation_type":"REVISITS"}]
```

Ejecutar `python scripts/evaluate_constellation_links.py expected.json report-*.json`.
El script compara `SAME_REFERENT` e `IN_TENSION` sin dirección, y `SHIFTS` y
`REVISITS` de forma direccional. Reporta precisión, cobertura, falsos positivos
y pares perdidos. La calidad de las preguntas requiere revisión humana: una
relación correcta no garantiza que la repregunta sea útil o cuidadosa.

## Límites conocidos

- Las emociones son entidades locales a cada run; esta versión conecta claims,
  pero todavía no crea una identidad canónica para «angustia» entre documentos.
- El mismo documento reprocesado varias veces puede aportar claims candidatos
  duplicados; se deduplican por texto/documento, no se elige automáticamente
  un único run como autoridad.
- La búsqueda top-k puede perder pares útiles. El modelo sólo compara los que
  recuperó el índice; su rechazo no demuestra que no haya conexión.
- El endpoint es explícito, no corre durante la ingesta. Esto permite evaluar
  los resultados antes de automatizar su persistencia o su reproceso incremental.
