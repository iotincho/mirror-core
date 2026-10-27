# Configuración y consumo de contexto de agentes

## Qué se carga y cuándo

[AGENTS.md](../../AGENTS.md) contiene las reglas comunes. Los archivos anidados
agregan invariantes del área; buscarlos en el camino al módulo antes de editarlo.
No presuponer que cada capacidad dispone de uno.

Codex descubre instrucciones desde la raíz hasta su directorio de trabajo; los
archivos anidados no se incorporan todos por estar en el repositorio. El límite
`project_doc_max_bytes` se expresa en bytes, no en tokens. Fuentes oficiales:
[descubrimiento de instrucciones](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
y [configuración](https://learn.chatgpt.com/docs/config-file/config-reference).

Usar [arquitectura](../../ARCHITECTURE.md) para ubicar la capa y el [índice](../README.md)
para elegir el contrato. Leer después el caso de uso y una prueba cercana. Consultar
[pendientes](../pending.md) sólo al planificar trabajo de ese alcance. No cargar
toda la documentación como instrucciones.

## Configuración reproducible para Codex CLI

```bash
sh scripts/codex-backend.sh
sh scripts/codex-backend.sh 'Revisá el contrato de retry de processing; sólo análisis'
```

El launcher fija la raíz de este checkout y dos overrides por ejecución:

| Clave | Valor | Alcance |
| --- | --- | --- |
| `project_doc_max_bytes` | `16384` | Techo de instrucciones descubiertas; mantener las guías por debajo |
| `tool_output_token_limit` | `4000` | Presupuesto de cada salida de herramienta conservada en el historial |

No cambia el modelo, credenciales, permisos ni configuración global. El launcher
usa los [overrides CLI oficiales](https://developers.openai.com/codex/cli/reference).
El límite de salida requiere consultas acotadas: si se trunca un error, leer el
rango relevante, no ignorarlo. Estos valores no limitan el costo total de una tarea.

La app y otros agentes siguen usando `AGENTS.md`; el launcher sólo afecta a los
procesos CLI iniciados con él. No instala configuración en `.codex/`, que este
repositorio reserva para estado local ignorado.

## Presupuesto mantenible

```bash
python3 scripts/check_repo_docs.py
```

El chequeo valida enlaces locales de toda la documentación en `docs/` y de sus
entradas en README/instrucciones, cobertura del
índice para documentos de primer nivel y presupuestos: raíz ≤6 KiB, guía de área
≤3 KiB y cualquier cadena de instrucciones del repositorio ≤12 KiB. Queda margen
hasta el techo del launcher para instrucciones heredadas; no se puede garantizar
ese margen si la configuración global del usuario es extensa.

El chequeo informa bytes, una medida reproducible de texto. No representa tokens
facturados ni mide el contexto global, skills, herramientas, razonamiento o chat.
Si crecen las reglas, trasladar explicaciones a la referencia específica antes
de aumentar el presupuesto.

## Hábitos que reducen trabajo repetido

- Una tarea con objetivo y criterios de aceptación concretos. Ejemplo: «Corregir
  retry de la capa X; conservar IDs y no repetir proveedor; probar fallo al persistir».
- Buscar símbolos en el área, leer rangos y agrupar consultas independientes con
  salidas acotadas. No repetir lecturas salvo que haya cambios o evidencia faltante.
- Ampliar pruebas por riesgo. Después de pasar los checks pertinentes, cerrar la
  tarea; no ejecutar suites completas repetidamente sin una razón nueva.
- Mantener un solo contrato vigente por tema; eliminar planes resueltos y
  consolidar pendientes explícitos en `docs/pending.md`. Actualizar las referencias
  afectadas al mover responsabilidades.
- Para continuar una tarea larga, dejar objetivo, decisión, archivos modificados,
  verificaciones y próximo paso. Evitar resúmenes completos de cada comando.
- Evaluar delegación sólo para subtareas independientes cuando esté autorizada;
  replicar todo el contexto en varios agentes puede aumentar el consumo.

## Medir antes de atribuir ahorros

Comparar tareas equivalentes antes/después: tokens de entrada/salida reportados
por el cliente, duración, llamadas, archivos leídos y pruebas necesarias. Separar
costo de implementación de las llamadas OpenAI del producto. No hay un porcentaje
de ahorro validado por esta reorganización; el primer objetivo verificable es
reducir el texto obligatorio y las búsquedas sin dirección.
