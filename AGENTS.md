# Instrucciones para agentes · mirror-core

## Entrada mínima

- Trabajar en español. Respetar el alcance pedido; análisis/planning no autoriza implementar.
- Empezar con `git status --short`. Preservar trabajo ajeno. No publicar, migrar
  entornos con datos ni desplegar sin autorización para esa acción.
- Ubicar el área con [arquitectura](ARCHITECTURE.md) y el [índice](docs/README.md);
  leer sólo su contrato y sus pruebas. Antes de editar, leer los `AGENTS.md` del
  camino al archivo, incluso si la sesión comenzó en la raíz. No cargar todos los módulos.
- Usar `rg --files <área>` y `rg -n '<símbolo>' <área>`. Leer rangos pequeños;
  ampliar si falta evidencia. No volcar árboles, logs o suites completos al contexto.
- No leer por defecto prototipos, `build/`,
  material personal, `.env*` salvo `.env.example`, ni credenciales locales.

## Reglas comunes

- Arquitectura y criterios para nuevos módulos: [ARCHITECTURE.md](ARCHITECTURE.md).
  Consultar la sección pertinente al cambiar responsabilidades o dependencias.
- Seguir [implementación](docs/development/implementation.md) al cambiar comportamiento.
  Reutilizar contratos, casos de uso y composición existentes antes de crear abstracciones.
- API/Taskiq son adaptadores; los casos de uso no importan clientes concretos de
  proveedores o de ArcadeDB. El dominio no depende de HTTP ni de infraestructura.
- Resolver propietario desde sesión/job y workspace; nunca desde un `user_id`
  arbitrario recibido del cliente. Administración usa su aplicación separada.
- Conservar originales, identidad idempotente, checkpoints y configuración aceptada.
  Retry retoma; reprocesamiento crea otra ejecución. No añadir retries del broker.
- Cada extractor controla sus artefactos y reemplaza atómicamente sólo su proyección.
  No repetir llamadas LLM al recuperar persistencia. No hacer llamadas reales pagas
  ni enviar notas/audio privados para validar un cambio sin autorización específica.
- No registrar contenido, audio, claves, cookies o payloads de proveedores.
  Mantener errores seguros y correlación técnica por trace/job/recurso.
- Cambios pequeños con una responsabilidad; no mezclar refactors ajenos ni agregar
  dependencias o frameworks para resolver algo que ya tiene un patrón local.

## Cierre

- Elegir verificaciones en [pruebas](docs/development/testing.md). Usar
  `.venv/bin/python -m pytest` y `.venv/bin/python -m ruff check <rutas>`.
- Cambios de contratos o configuración actualizan su documento vigente; cambios
  de responsabilidades actualizan arquitectura y las referencias afectadas. Ejecutar
  `python3 scripts/check_repo_docs.py` si cambian guías, enlaces o instrucciones.
- Informar resultado, pruebas y límites reales. Un skip no es validación de
  integración; un commit/PR no acredita despliegue. No repetir pruebas aprobadas
  salvo cambios nuevos o dudas concretas.
- Para tareas largas dejar un traspaso breve (objetivo, archivos, decisiones,
  comandos/resultados y próximo paso), sin transcripciones del chat.

Configuración y medición: [guía de agentes](docs/development/agents.md).
