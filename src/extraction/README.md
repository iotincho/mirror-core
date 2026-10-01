# Perfiles de extracción

Los perfiles definen el experimento de extracción: instrucciones para el LLM,
versión del prompt y versión del esquema. Están registrados en
[`profiles.py`](profiles.py). Un `ExtractionRun` guarda esas tres referencias,
por lo que cada resultado puede atribuirse al experimento que lo generó.

No se reescribe un perfil ya usado. Un cambio en instrucciones, contrato o
criterio de evidencia crea un perfil nuevo. Esto permite comparar resultados y
reprocesar documentos sin perder la explicación de por qué una corrida anterior
produjo otro resultado.

## Perfiles disponibles

| Perfil | Esquema | Prompt | Estado | Decisión |
| --- | --- | --- | --- | --- |
| `v1` | `v1` | `v1` | Histórico | Pedía al LLM `start_char` y `end_char`. Falló porque el modelo no calcula offsets de caracteres de forma fiable. |
| `v2` | `v2` | `v2` | Histórico | El LLM devuelve `quote`; la aplicación calcula offsets y líneas. Falló en algunos textos porque el modelo corrigió capitalización o typos al citar. |
| `v3` | `v2` | `v3` | Histórico | Conserva el esquema de `v2` y añade una regla fuerte: cada `quote` debe ser un substring literal y contiguo del documento, sin corregir ni normalizar caracteres. |
| `v4` | `v2` | `v4` | Predeterminado | Refuerza la copia mecánica y literal de las citas. |
| `v5` | `v3` | `v5` | Experimental | Extrae emociones expresadas como entidades locales y relaciones semánticas acotadas; la comparación entre documentos ocurre después. Véase [experimento de constelación](../../docs/constellation-experiment-v1.md). |

## Contrato de evidencia

El LLM entrega solamente `quote`. Para una cita única y exacta, la aplicación
deriva y guarda:

```json
{
  "quote": "fragmento original, incluido un typo si existe",
  "start_char": 42,
  "end_char": 86,
  "start_line": 3,
  "end_line": 3
}
```

Los offsets y líneas son datos derivados: nunca son autoridad del proveedor. Si
el modelo los envía, la aplicación los descarta y recalcula desde `Document.content`.

La resolución sigue este orden:

1. Busca una coincidencia literal de `quote` en el contenido original.
2. Si existe una única coincidencia, calcula el localizador y persiste la cita
   tomada del documento.
3. Si no existe o aparece más de una vez, la corrida falla de forma auditable.

No se aplica matching difuso ni normalización de acentos, puntuación o typos. De
otro modo una paráfrasis del modelo podría quedar registrada como evidencia del
usuario.

## Incidente que motivó `v2` y `v3`

El 2026-09-22 se observaron dos fallas consecutivas durante cargas de notas:

1. `v1` recibió respuestas estructuradas válidas, pero las posiciones informadas
   por el modelo no coincidían con las posiciones reales del texto.
2. `v2` eliminó esa responsabilidad del modelo, pero algunas citas no se
   encontraron porque el modelo alteró el original: por ejemplo, capitalizó el
   inicio de una oración o corrigió una falta de ortografía.

`v3` es el experimento actual: primero se busca mejorar la fidelidad mediante
prompt y se mantiene la validación exacta. Si falla, el log conserva el resultado
estructurado generado y el `ExtractionRun` queda marcado como `failed`, sin
persistir una evidencia no verificable.

## Crear el siguiente perfil

1. No modifiques un perfil existente.
2. Crea `V<N>_PROFILE` con un nombre y `prompt_version` nuevos. Incrementa
   `schema_version` solo si cambia el contrato de datos.
3. Regístralo en `PROFILES`.
4. Añade tests para la conducta que motivó el cambio.
5. Cambia el valor por defecto solo cuando el experimento anterior deba dejar de
   recibir tráfico nuevo.

El proveedor actual usa `responses.parse` con el modelo Pydantic del contrato.
Structured Outputs asegura la forma de la respuesta; la fidelidad semántica y
literal de una cita sigue siendo responsabilidad de las instrucciones y de la
validación local. Consulta la [guía de Structured Outputs de OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
