# Constelación: primer experimento entre documentos

> Documento histórico: el extractor exploratorio y el análisis anterior de
> Constelación se retiraron. El estado actual está en
> [Retiro de la extracción](extraction-retirement.md).

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

La revisión `prompt_version="v5.1"` refuerza la copia de evidencia: comprobar
una única aparición, ampliar citas repetidas con contexto literal y omitir el
ítem y sus relaciones si no puede obtenerse una cita inequívoca. No cambia el
perfil solicitado (`v5`), el esquema ni la validación estricta.

La rueda de emociones es una **capa de normalización posterior**, todavía no
implementada. Para esta prueba se conserva la palabra original y se puede
comparar manualmente si una familia de la rueda ayudaría a explorar sin forzar
etiquetas. No se presupone que la emoción se conozca siempre.

## Cómo se conectan dos notas

`POST /documents/{document_id}/links` recibe un `run_id` completado. Genera
embeddings de hasta `max_claims` claims y de la nota completa, y recupera hasta
`candidates_per_claim` candidatos nuevos por búsqueda, con un máximo global de
50 candidatos del mismo perfil en **otros documentos de la misma base de usuario**.
Deduplica por texto/documento y realiza una comparación estructurada `link-v2`
que recibe la **nota de origen completa**, su extracción existente y los claims,
citas y fechas de los candidatos. La nota original no se trunca. Un ID ajeno a
los candidatos se rechaza. `SHIFTS` y `REVISITS` requieren `authored_at` distinto
en ambos documentos. `compared_pairs` informa la cantidad de candidatos únicos
presentados al comparador, no el número de combinaciones posibles entre claims.

La respuesta puede incluir `supplemental_extraction`: hasta 20 claims, 20 entidades,
20 conceptos y 50 relaciones internas sustentadas en la nota de origen. Los nuevos
claims conservan texto literal; todas las citas se resuelven contra esa nota. No se
extraen nuevos elementos de los candidatos, porque sus snippets no son documentos
completos. Un nuevo claim puede ser el extremo de un vínculo propuesto. Los elementos
idénticos de la misma nota se reutilizan por tipo y contenido; no se fusionan entidades
entre documentos por compartir nombre. Las identidades de nodos nuevos son estables
para que repetir un análisis no los duplique.

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

Con `persist=false`, no se escriben las propuestas suplementarias ni sus vínculos.
Con `persist=true`, se guarda un registro de auditoría suplementario separado,
con `origin="constellation"`, `parent_run_id` y las identidades de sus nodos. Después
se escriben en una sola transacción de ArcadeDB los nodos nuevos, evidencias,
relaciones internas y vínculos, comprobando las cantidades/identidades resultantes.
Si falla cualquier vínculo, se revierte el conjunto; el registro local de auditoría
puede quedar preparado, pero `graph_persisted=false` y no se usa como extracción inicial.
No se modifica el resultado de las corridas previas ni los atributos de nodos reutilizados.

Los embeddings se generan después del commit. Un fallo devuelve `persisted=true`,
`embeddings_status="pending"` y una advertencia: los vínculos están guardados.
`POST /documents/{id}/extractions/{run_id}/embeddings` permite reintentarlos sin
reanálisis, sólo para suplementos de ese documento ya persistidos. El historial
incluye `origin`, `graph_persisted` y `ready`. Los suplementos no sustituyen la
extracción inicial completa en la preparación automática de la webapp.

## Corrida reproducible

### Uso desde la webapp

La sección **Constelación** muestra notas sincronizadas del usuario autenticado.
Lee los vínculos guardados sin invocar al modelo al abrir la pantalla. El grafo
usa Cytoscape, tiene una alternativa en lista y permite consultar las citas y
abrir cada nota original. Se muestran 10 vecinos por página y hasta 40 notas
simultáneas; centrar otra nota permite continuar explorando sin cargar el grafo
completo. Los filtros se aplican también en el servidor.

Los endpoints de lectura, dentro del workspace autenticado, son:

- `GET /documents/{id}/links?offset=0&limit=10&relation_type=SHIFTS`: vecinos,
  cantidad total, siguiente offset y hasta 500 vínculos conceptuales por página.
  `relation_type` es opcional; las proyecciones inversas no se duplican.
- `GET /documents/{id}/extractions`: historial y estado `ready`, que requiere
  todos los claims esperados y embeddings del modelo configurado en el grafo.

«Buscar conexiones» permite seleccionar hasta 10 notas. Primero reutiliza una
corrida `v5` lista o crea una extracción para cada nota seleccionada; después
ejecuta las comparaciones secuencialmente. «Analizar sin guardar» no escribe
vínculos, pero puede crear extracciones y embeddings. «Analizar y guardar» pide
confirmación y ejecuta un nuevo análisis; no confirma el resultado inmutable de
una vista previa. Las propuestas pueden incluir otras notas del workspace,
no sólo las seleccionadas para iniciar la búsqueda. Cada escritura es atómica;
el lote completo de notas no es una única transacción y se informa si hay fallos
parciales.

La webapp muestra también los elementos suplementarios y sus citas, en vista
previa o después del guardado, y ofrece reintentar embeddings pendientes.

### Comparación manual

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
