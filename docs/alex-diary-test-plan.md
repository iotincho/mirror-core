# Plan de pruebas: diario sintético de Alex

> Documento histórico: el extractor exploratorio y el análisis anterior de
> Constelación se retiraron. El estado actual está en
> [Retiro de la extracción](extraction-retirement.md).

Este dataset permite evaluar la POC con evidencia conocida, sin incorporar pensamientos reales. Cada archivo de [`data/fixtures/alex-diary`](../data/fixtures/alex-diary) es un `NewDocument` serializado y se debe cargar como documento independiente.

## Contrato de las notas

Cada fixture contiene `id`, `content`, `source`, `metadata` y `authored_at`. `authored_at` es la fecha del texto expresada con zona horaria (`-03:00`). `created_at` lo asigna El Espejo al insertar el documento, por lo que ambos valores pueden diferir en una importación. La API `POST /documents` acepta `authored_at` y conserva ambas fechas. Los metadatos son deliberadamente simples y todos sus valores son texto, tal como exige el contrato actual.

| Campo | Uso |
| --- | --- |
| `authored_at` | Orden temporal de lo expresado en la nota. |
| `created_at` | Momento de inserción del documento en El Espejo. |
| `metadata.title` | Título visible y referencia humana. |
| `metadata.note_number` | Identificador estable para la evidencia esperada. |
| `metadata.phase` | `baseline` (01–15) o `incremental` (16–18). |
| `metadata.dataset`, `dataset_version` | Aíslan esta batería de otros documentos y hacen reproducible la evaluación. |
| `metadata.language`, `author` | Contexto de idioma y carácter sintético del material. |

Los UUID son estables para que las corridas puedan compararse. Para cargar un archivo a la API, enviar el JSON completo como cuerpo de `POST /documents`; no usar el endpoint `/documents/files`, porque el formato de upload actual no recibe metadatos ni fecha de origen.

Primero cargar 01–15 y ejecutar los tests 01–15. Luego agregar únicamente 16–18, sin reingestar las anteriores, y ejecutar 16–18. Registrar la configuración de extractor, embeddings, modelo de reflexión y estrategia de recuperación en cada corrida.

## Registro por corrida

Guardar una fila por pregunta y la respuesta íntegra. Para cada fila, registrar los UUID y `note_number` recuperados, los fragmentos citados, la estrategia (`vector`, `graph` o `hybrid`) y el perfil/modelo usado. Una respuesta convincente sin evidencia no aprueba un test interpretativo.

| Test | Evidencia correcta | Relaciones o tiempo correctos | Interpretación respaldada | Inventó información | Estado |
| --- | --- | --- | --- | --- | --- |
| 01–18 | Sí/No/Parcial | Sí/No/Parcial | Sí/No/Parcial | Sí/No | Pendiente |

Diagnóstico: si faltan notas relevantes, investigar recuperación; si las notas están y falla la conexión, investigar extracción, grafo o contexto entregado al LLM; si la conexión está en el contexto pero la respuesta es errónea, investigar generación o instrucciones.

## Batería base (notas 01–15)

| ID | Pregunta | Evidencia mínima | Criterio de aceptación |
| --- | --- | --- | --- |
| 01 | ¿Qué propuesta laboral recibí y por qué la rechacé? | 06, 09 | Salario ~25 %, oficina cuatro días, rechazo por flexibilidad/remoto y posible mudanza. |
| 02 | ¿Cuáles son los principales temas que aparecen en mis notas? | 01, 02, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15 | Agrupa autonomía, trabajo/estabilidad, proyectos, ejecución, residencia/naturaleza y vínculos; no exige esos nombres exactos. |
| 03 | ¿Qué preocupaciones o deseos se repiten en mis notas? | 01, 02, 04, 06, 07, 08, 09, 12, 15 | Identifica autonomía, estabilidad y dificultad de inicio por significado, no solo por palabras repetidas. |
| 04 | ¿Qué tensiones recurrentes aparecen en mis notas? | 01, 02, 04, 05, 06, 07, 08, 09, 11, 12, 13, 14, 15 | Distingue al menos autonomía-estabilidad, carrera-flexibilidad, ideas-ejecución, naturaleza-vínculos o planificación-experimentación. |
| 05 | ¿Cómo cambié respecto de los proyectos entre enero y julio? | 01, 04, 07, 08, 10, 13, 14 | Reconstruye la secuencia de deseo, postergación, inicio, feedback, fracaso/aprendizaje y segunda versión en orden temporal. |
| 06 | ¿Cambió para mí la importancia del dinero y la autonomía? | 02, 06, 09, 12, 15 | Describe una prioridad más equilibrada; no afirma que el dinero dejó de importar. |
| 07 | ¿Qué relación hay entre mi trabajo, una mudanza y mis proyectos propios? | 01, 03, 05, 06, 09, 11, 12 | Conecta las tres áreas a través de autonomía/flexibilidad y lo respalda. |
| 08 | ¿Qué contradicciones o tensiones aparecen en mis notas? | 02, 04, 05, 08, 11, 12, 15 | Clasifica estabilidad-autonomía y naturaleza-vínculos como tensiones; planificación-ejecución como cambio de enfoque, no contradicción lógica. |
| 09 | ¿Qué patrón sigo al iniciar proyectos? | 04, 07, 08, 13, 14, 15 | Describe entusiasmo, investigación, temor, postergación, práctica y ajuste; no diagnostica rasgos psicológicos. |
| 10 | ¿Qué relación podría haber entre mudarme a las sierras y emprender? | 05, 09, 11, 12 | Propone autonomía como hipótesis, claramente marcada como inferencia y con evidencia. |
| 11 | ¿Por qué la autonomía es importante para mí? Mostrame las notas. | 01, 03, 09, 12 | Incluye citas o fragmentos verificables de esas notas. |
| 12 | ¿Cómo se llama la empresa donde trabajo? | Ninguna | Declara falta de información; no inventa un nombre. |
| 13 | ¿Tengo miedo al compromiso? | 04, 05, 07, 11 | Rechaza el diagnóstico; puede describir indecisiones concretas con cautela. |
| 14 | ¿Finalmente me mudaré a las sierras? | 05, 11, 15 | Declara que hasta julio no se sabe; no predice. |
| 15 | «Quiero dejar mi trabajo para ganar más dinero»: ¿qué evidencia respalda esa afirmación? | 02, 09, 12 | Corrige o matiza: emprendimiento se vincula después más con autonomía que con dinero. |

## Actualización incremental (notas 16–18)

| ID | Pregunta | Evidencia mínima | Criterio de aceptación |
| --- | --- | --- | --- |
| 16 | ¿Cómo evolucionó mi relación con el trabajo y el emprendimiento de enero a septiembre? | 01, 02, 09, 12, 16, 17 | Reconoce empleo remoto mejor pago como nueva vía a autonomía y proyecto propio no necesariamente como reemplazo laboral. |
| 17 | ¿Todavía estoy considerando mudarme? | 05, 11, 15, 18 | Responde que no: en septiembre ya se mudó; diferencia estado pasado de hecho actual. |
| 18 | ¿Qué esperaba de las sierras y qué viví después? | 05, 11, 15, 18 | Contrasta naturaleza/tranquilidad con extrañar amistades y construir comunidad; evita calificarlo como éxito o fracaso total. |

## Comparación Vector RAG, Graph RAG e híbrido

Usar el test 07 como experimento controlado. Mantener fija la misma pregunta, corpus base, modelo y prompt; variar solamente la estrategia. Comparar precisión de las notas recuperadas, presencia del vínculo común de autonomía, trazabilidad y contenido inventado. El objetivo no es que el grafo gane: es determinar si añade relaciones útiles que el vector no recupera.

## Límites de seguridad interpretativa

En todos los tests, separar explícitamente observación, extracción e inferencia. No diagnosticar, no atribuir motivaciones no expresadas, no transformar una posibilidad futura en hecho y no ocultar incertidumbre para contestar la pregunta.
