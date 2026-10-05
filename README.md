# El Espejo

> Un instrumento de introspección personal asistido por IA.

El diseño del próximo flujo de ingreso está en
[Procesamiento diferido: contratos y diseño](docs/deferred-processing.md).
Define Taskiq + RabbitMQ, máquinas de estados por caso de uso y recuperación
durable; corresponde a la etapa 1 y todavía no modifica el comportamiento actual.
La [etapa 2: pipeline async](docs/async-pipeline.md) documenta la migración de
los contratos de I/O, el lifecycle de clientes y los límites de concurrencia.
La [etapa 3: ejecución durable](docs/processing-runtime.md) agrega PostgreSQL,
outbox, workers Taskiq/RabbitMQ y recuperación. Los uploads se conectan en etapa 4.

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

## Extracción estructurada con LLM

El primer componente de IA recibe un `Document` y devuelve una estructura validable:

```json
{
  "concepts": [],
  "entities": [],
  "claims": [],
  "relationships": []
}
```

Ejemplo de material:

> Estoy pensando en dejar mi trabajo. Me gusta cuánto aprendo, pero siento que pierdo libertad. Al mismo tiempo me preocupa perder estabilidad económica.

Posible extracción:

```json
{
  "concepts": ["trabajo", "aprendizaje", "libertad", "estabilidad económica"],
  "claims": [
    {"text": "Estoy considerando dejar mi trabajo", "type": "desire"},
    {"text": "Aprendo mucho en mi trabajo", "type": "observation"},
    {"text": "Siento que pierdo libertad", "type": "concern"},
    {"text": "Me preocupa perder estabilidad económica", "type": "concern"}
  ],
  "relationships": []
}
```

El esquema y el prompt del extractor son el principal espacio de experimentación. No se debe pedir análisis psicológico ni atribuir rasgos de personalidad. La historia, los contratos y el criterio para crear una nueva variante están en el [README de perfiles](src/extraction/README.md).

## Sentimiento y emoción

El análisis de sentimiento o emoción no debe definir automáticamente el grafo. Puede añadirse luego como metadato de documentos, afirmaciones o relaciones si demuestra ser útil.

```text
Claim
- sentiment
- emotion
- intensity
- confidence
```

## Recuperación y reflexión

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

## Estructura sugerida

```text
el_espejo/
├── src/
│   ├── ingestion/
│   ├── extraction/
│   ├── graph/
│   ├── embeddings/
│   └── query/
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

## Fases de implementación

1. **Foundation:** proyecto Python, dependencias, Docker Compose, ArcadeDB, configuración, logging y tests básicos. Sin LLM.
2. **Ingestion:** Markdown/TXT a `Document`, con IDs estables, contenido original, fecha y metadatos de fuente.
3. **Knowledge extraction:** `Document` a conceptos, entidades, afirmaciones y relaciones mediante salida estructurada.
4. **Graph persistence:** persistencia en ArcadeDB y consultas de inspección manual.
5. **Embeddings:** embeddings de documentos o afirmaciones y búsqueda semántica básica.
6. **Reflection:** una función `answer(question)` que combine grafo, vectores, evidencia y LLM.
7. **Experiments:** batería de preguntas reales para evaluar utilidad, precisión y alucinaciones.
8. **Mobile/API:** únicamente cuando el motor demuestre valor.

La persistencia de grafo está documentada en el [README de grafo](src/graph/README.md),
la recuperación vectorial en el [README de embeddings](src/embeddings/README.md) y la
resolución en el [README de reflexión](src/reflection/README.md).

## Primer hito técnico

Con 20–50 notas personales reales, el sistema debe poder:

1. Ingerir las notas.
2. Extraer conceptos, entidades, afirmaciones y relaciones.
3. Persistirlos en ArcadeDB.
4. Mantener enlaces de evidencia a los documentos originales.
5. Generar embeddings.
6. Hacer búsqueda semántica.
7. Responder algunas preguntas reflexivas con recuperación por grafo y vectores.
8. Exponer la evidencia utilizada por cada observación.

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

La extracción genera `title` en la misma llamada al modelo: entre 3 y 8 palabras,
con un máximo de 80 caracteres y en el idioma de la nota. El título se guarda
como campo propio del documento y de la extracción. No modifica `content`,
la identidad, los metadatos ni las fechas originales.

`POST /documents`, `POST /documents/files` y `GET /documents` incluyen el título
en el documento devuelto. Las transcripciones usan el mismo procesamiento.
Los perfiles registran las versiones de prompt y esquema con el sufijo
`-title-v1`; el esquema de ArcadeDB pasa a `v4` para agregar `Document.title`
también en bases existentes, mediante la reconciliación de workspaces.

Los JSON antiguos siguen siendo válidos y devuelven `title: null`. Al reprocesar
con `POST /documents/{id}/extractions` se genera y actualiza el título. No se
reprocesan notas anteriores automáticamente ni se generan llamadas adicionales
al modelo para listar documentos.
