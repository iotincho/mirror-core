# El Espejo

> Un instrumento de introspección personal asistido por IA.

El flujo actual conserva documentos y transcribe audio mediante procesamiento
durable `/v2` con PostgreSQL, Taskiq/RabbitMQ y SSE. La extracción genérica
exploratoria, sus embeddings y las funciones de búsqueda/reflexión/Constelación
se retiraron. Se conserva el visor de la PWA y la API de lectura del grafo. Los documentos se guardan en ArcadeDB de forma
independiente, sin generar título mediante un modelo.

El [retiro y procedimiento de limpieza](docs/extraction-retirement.md) documenta
la migración masiva automática pendiente de ejecutar al desplegar. El [plan de extracción por capas](docs/extraction-layers-requirements-plan.md)
define los extractores independientes a incorporar después.

El [respaldo e importación de documentos](docs/document-archives.md) permite
descargar JSON desde la PWA y restaurar originales después de recrear las bases.
Incluye una herramienta administrativa independiente de los motores para
exportar antes de un reset si la API no puede arrancar.

Los documentos de [contratos diferidos](docs/deferred-processing.md),
[pipeline async](docs/async-pipeline.md), [runtime durable](docs/processing-runtime.md),
[uploads diferidos](docs/deferred-ingestion.md) y [PWA/SSE](docs/processing-pwa-events.md)
conservan las etapas previas; sus referencias al pipeline de extracción v1 son
históricas. Las secciones de visión y experimentos de este README describen el
objetivo del producto y exploraciones anteriores, no capacidades activas.

El [extractor de emociones de prueba](docs/emotion-extractor.md) implementa el
contrato común de capas y permite extraer en dry run o persistir un artefacto
más tarde. Las notas nuevas ejecutan automáticamente el workflow de documento v3:
`document_persistence → layer_extraction → layer_persistence → done`. Incluye los
documentos creados desde audio; los trabajos históricos v2 siguen guardando sólo
documentos. Se requieren `LLM_PROVIDER=openai`, `OPENAI_API_KEY` y `OPENAI_MODEL`.

## Contexto

El Espejo es una prueba de concepto (POC) para explorar si la IA puede ayudar a una persona a observar, recorrer y comprender sus propios pensamientos a lo largo del tiempo.

No busca ser un psicólogo virtual, un sistema de diagnóstico de salud mental, otra aplicación genérica de notas, ni un chatbot con historial largo. Busca ser un **espejo personal**: un lugar donde volcar pensamientos, ideas, decisiones, reflexiones y experiencias, y desde el cual explorar patrones, recurrencias, tensiones, conflictos y cambios a partir de evidencia en el propio material.

Ejemplos de preguntas que debería poder explorar:

- ¿Qué ideas aparecen recurrentemente?
- ¿Qué tensiones o conflictos vuelven a aparecer?
- ¿Cómo cambió mi pensamiento sobre el trabajo durante los últimos meses?
- ¿Qué conceptos parecen conectados aunque nunca los haya vinculado explícitamente?
- ¿Qué creencias o afirmaciones cambiaron con el tiempo?
- ¿En qué material se basa esta observación?

El sistema debe reflejar **lo que puede observarse e inferirse del material expresado**, no presentar una interpretación como verdad psicológica.

## Idea central

> Un espejo personal asistido por IA: un sistema que construye una representación navegable, temporal y respaldada por evidencia de los pensamientos expresados por una persona, y le permite explorarla.

```text
Notas / audio / material importado
               |
               v
     Normalización y extracción estructurada
               |
       +-------+--------+
       |                |
       v                v
Grafo cognitivo    Embeddings
       |                |
       +-------+--------+
               |
               v
     Recuperación + evidencia + LLM
               |
               v
          Reflexión para el usuario
```

El grafo no representa la mente ni la identidad objetiva de la persona. Representa aquello que el sistema pudo extraer y relacionar desde los registros originales.

## Grafo y embeddings

No son alternativas ni uno se deriva necesariamente del otro.

```text
                    TEXTO
                      |
          +-----------+-----------+
          |                       |
          v                       v
     Embedding               Extracción
          |                       |
          v                       v
  Similitud semántica   Conceptos, entidades,
  y búsqueda vectorial  afirmaciones y relaciones
                                  |
                                  v
                                Grafo
```

Los embeddings ayudan a responder: “¿Qué notas son semánticamente parecidas a esta idea?”. El grafo permite responder: “¿Qué conceptos están conectados, cómo y con qué evidencia?”.

```text
AUTONOMÍA -- relacionada con --> TRABAJO
     |                                |
     +--- en tensión con --- ESTABILIDAD
```

No hay un único grafo correcto. La representación útil depende de las preguntas que se quieran hacer.

| Pregunta | Representación posible |
|---|---|
| ¿Sobre qué temas pienso? | Temas y conceptos |
| ¿Qué parece importante para mí? | Conceptos y afirmaciones |
| ¿Qué contradicciones aparecen? | Afirmaciones, relaciones y tiempo |
| ¿Cómo cambió una idea? | Afirmaciones con marcas temporales |
| ¿Qué pensamientos se parecen? | Embeddings |
| ¿Qué conceptos están relacionados? | Grafo de conocimiento |
| ¿Qué ideas se repiten? | Frecuencia, grafo y tiempo |

La POC debe permitir experimentar con distintas estrategias de extracción, sin congelar prematuramente una ontología.

## Modelo inicial

El modelo se mantendrá deliberadamente pequeño.

### Document

Material original, que siempre debe preservarse.

```text
Document
- id
- content
- created_at (fecha de inserción en El Espejo)
- authored_at (fecha en que el usuario redactó la nota, si se conoce)
- source
```

Fuentes futuras posibles: Markdown, texto plano, transcripciones de audio, exportaciones de ChatGPT, WhatsApp, Telegram u otros materiales importados.

### Concept

Idea abstracta identificada en el material.

```text
Concept
- id
- name
```

Ejemplos: autonomía, estabilidad, creatividad, dinero, aprendizaje, trabajo y libertad.

### Entity

Elemento concreto e identificable.

```text
Entity
- id
- name
- type
```

Ejemplos: una empresa, un proyecto, una persona o un lugar.

### Claim

Una afirmación expresada explícitamente por la persona.

```text
Claim
- id
- text
- type
- timestamp
```

Tipos iniciales tentativos: `belief`, `desire`, `concern`, `observation`, `decision`, `preference` y `hypothesis`. Son descripciones operativas, no categorías psicológicas definitivas.

## Relaciones iniciales

Empezar con un conjunto mínimo:

```text
MENTIONS
CONTAINS
ABOUT
RELATES_TO
SUPPORTS
CONTRADICTS
EXPRESSES
```

Ejemplo:

```text
Document -- MENTIONS --> Concept(work)
Document -- CONTAINS --> Claim("Quiero más autonomía")
Claim    -- ABOUT    --> Concept(autonomía)
```

Relaciones futuras —solo si los experimentos muestran que son útiles—: `CAUSES`, `ASSOCIATED_WITH`, `EVOLVED_INTO`, `DEPENDS_ON`, `CONFLICTS_WITH`, `SIMILAR_TO`, `PRECEDES`.

## Evidencia y procedencia

Este es un requisito central. El sistema debe poder responder “¿por qué pensás eso?”. Cada concepto, relación o inferencia debe poder conducir al material original que la respalda.

```text
Concept: autonomía
  |
  +-- evidencia --> Document 183
  +-- evidencia --> Document 213
  +-- evidencia --> Document 271
```

Las respuestas deben distinguir siempre entre:

- **Observado:** “El concepto ‘autonomía’ aparece en 17 documentos.”
- **Extraído:** “El sistema identificó ‘autonomía’ como un concepto.”
- **Inferido:** “Autonomía parece asociarse frecuentemente con trabajo.”

Una inferencia nunca debe presentarse silenciosamente como hecho.

## Extractores por propósito

Cada extractor define sus modelos, validaciones, entidades, relaciones y escritura
en el grafo. El contrato común está en `src/extractors`; la prueba inicial es el
[extractor de emociones](docs/emotion-extractor.md), que usa citas del documento
completo y admite extracción sin escritura y persistencia posterior.

El pipeline automático guarda primero el documento y luego ejecuta emociones. La
extracción genérica, sus embeddings y la implementación anterior de Constelación
se retiraron. La PWA conserva el visor y `GET /documents/{id}/links` conserva la
respuesta de navegación paginada del grafo. El análisis de nuevas relaciones
queda pendiente de refactorización.

## Recuperación y reflexión (diseño futuro)

Una consulta futura combinará recuperación vectorial, recorrido del grafo y documentos originales:

```text
Pregunta
   |
   +-- búsqueda vectorial --> notas semánticamente cercanas
   |
   +-- búsqueda en grafo --> conceptos y afirmaciones conectadas
   |
   v
Contexto con evidencia
   |
   v
LLM
   |
   v
Respuesta reflexiva y auditable
```

Ejemplo de salida deseada:

> Aparece una tensión recurrente entre autonomía y estabilidad. La asociación se observa en los documentos 183, 213 y 271, y fue más frecuente en los últimos tres meses.

## Stack inicial propuesto

```text
Python
FastAPI
Pydantic
ArcadeDB
OpenAI API
Docker Compose
pytest
```

`Ollama` queda como experimento opcional para modelos y embeddings locales. La máquina de desarrollo cuenta con una RTX 2060 de aproximadamente 6 GB de VRAM: sirve para experimentar con modelos pequeños cuantizados, pero la primera POC debería priorizar una API para reducir complejidad.

ArcadeDB, FastAPI y la orquestación no requieren GPU.

LlamaIndex no es requisito inicial. La aplicación mantiene contratos propios para no acoplar los
casos de uso a un framework de RAG ni a un motor de grafo concreto.

## Estrategia de entrada

No empezar por una aplicación móvil. El primer formato debe ser simple:

```text
data/
  notes/
    001.md
    002.md
    003.md
```

Esto permite aprender rápido antes de construir interfaz, autenticación, sincronización o despliegue.

La entrada de audio será una etapa posterior:

```text
Audio --> Speech-to-text --> Document --> Extracción
```

Una futura PWA o app móvil solo debería escribir, grabar, consultar y explorar; la inferencia principal vive en el backend.

## Estructura actual

```text
el_espejo/
├── src/
│   ├── domain/
│   ├── extractors/
│   ├── graph/
│   ├── processing/
│   └── use_cases/
├── data/
│   └── notes/
├── tests/
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

La arquitectura debe mantenerse limpia y tipada, pero sin sobreingeniería mientras se descubre el modelo conceptual.

La persistencia de grafo se conecta mediante contratos de aplicación. Los casos de uso no
importan drivers ni adaptadores concretos. La implementación de ArcadeDB se organiza así:

```text
src/graph/
├── arcadedb/
│   ├── client.py      # cliente HTTP y transacciones
│   ├── store.py       # implementación de los contratos y mapeo al dominio
│   ├── schema.py      # tipos, propiedades, constraints e índices
│   └── queries.py     # SQL y Cypher propios de ArcadeDB
└── README.md
```

`dependencies.py` es el único punto que selecciona y construye el adaptador. El schema se
inicializa y versiona por separado de las operaciones normales del store. El directorio
`arcadedb/` contiene el adaptador activo; esta frontera permite reemplazar el motor sin modificar
los casos de uso.

## Etapas actuales

La transición y sus criterios de aceptación están en el
[plan de extracción por capas](docs/extraction-layers-requirements-plan.md).
El retiro del proceso exploratorio y las etapas durables de emociones están implementados.
Quedan la coordinación de ramas independientes para varias capas, su ejecución paralela y las
consultas por capas. La persistencia y la respuesta del visor están documentadas
en el [README de grafo](src/graph/README.md).

## Evaluación

La POC no se evalúa por lo vistoso o técnicamente complejo del grafo. Las preguntas importantes son:

- ¿Refleja algo significativo del material de la persona?
- ¿Revela conexiones que no eran evidentes?
- ¿Ayuda a formular mejores preguntas?
- ¿Muestra evidencia suficiente?
- ¿Evita inventar patrones?
- ¿Qué representaciones no aportan valor?

Preguntas iniciales de prueba:

- ¿Qué temas aparecen recurrentemente?
- ¿Qué preocupaciones se repiten?
- ¿Qué tensiones aparecen en mis pensamientos?
- ¿Qué ideas cambiaron con el tiempo?
- ¿Qué afirmaciones parecen contradictorias?
- ¿Qué proyectos o ideas regresan una y otra vez?
- ¿Por qué el sistema considera importante este concepto?

## No objetivos iniciales

No construir en esta POC:

- diagnóstico o recomendaciones de salud mental;
- terapia, perfiles psicológicos o puntajes de personalidad;
- conclusiones psicológicas autónomas;
- producto multiusuario, autenticación o despliegue cloud;
- interfaz móvil compleja;
- microservicios, Kubernetes o escalabilidad de producción.

## Principio rector

La IA no debe decir: “esto es quien sos”. Debe decir cosas como:

- “Esta idea aparece frecuentemente en tus notas.”
- “Estas dos afirmaciones parecen entrar en conflicto.”
- “Estos conceptos suelen aparecer juntos.”
- “Tus documentos muestran evidencia de un cambio en esta idea.”
- “Esta es una interpretación basada en estos documentos.”

La POC existe para descubrir qué representación de pensamientos personales resulta útil para una reflexión genuina. La prioridad no es completar una arquitectura: es aprender.

## Títulos de documentos

Se conservan los títulos existentes, incluidos los recuperados desde archivos de
respaldo. La ingestión no llama modelos para crear ni modificar títulos. Los
documentos sin título siguen siendo válidos; la PWA muestra un nombre a partir
del contenido. Reprocesar con `/v2/documents/{id}/processing` vuelve a persistir
el original y crea una nueva ejecución de emociones con la configuración actual.
