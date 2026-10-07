# Extracción por capas: requerimientos y plan

Fecha: 2026-10-06.
Estado: etapa 1 implementada y validada localmente. Contrato común y extractor
de emociones de prueba implementados; ver [alcance y uso](emotion-extractor.md). La limpieza de bases de
usuario queda para el despliegue, según la decisión posterior del usuario.
El detalle del código y procedimiento está en [Retiro de la extracción](extraction-retirement.md).
La integración de emociones al pipeline está implementada mediante etapas
recuperables del workflow de documento v3. El paralelismo entre ramas sigue pendiente. Las consultas por capas disponen
de una primera vista de conexiones inmediatas en Constelaciones.
Quedan la selección de varias capas simultáneas y otras consultas. Se completó la eliminación del runtime exploratorio, conservando
la API de lectura y el visor del grafo.

## Objetivo

Reemplazar la extracción genérica exploratoria por extractores con propósitos
claros e independientes. El documento original es la fuente estable. Cada
extractor administra una capa derivada dentro del mismo grafo, que puede
consultarse sola o junto con otras capas.

Una capa corresponde a un tipo de extracción, no a una versión del prompt.
Seleccionar varias capas permite consultar sus resultados juntos; no implica
crear relaciones entre ellas ni inferir causalidad.

## Decisiones acordadas

- Una interfaz común encapsula la ejecución de los extractores. Cada
  implementación define su método, modelos, entidades, relaciones, validaciones
  y lógica de persistencia. Una clase base es opcional para compartir código;
  no debe imponer el mismo algoritmo a todas las implementaciones.
- El extractor es dueño de toda su capa. La conexión y las operaciones reales
  de base de datos permanecen desacopladas mediante el puerto de ArcadeDB.
- Extracción y persistencia son operaciones invocables por separado. Puede
  existir una operación de conveniencia con `dry_run`, sin perder esa separación.
- El pipeline recibe uno o varios extractores configurados. Son ortogonales y
  pueden ejecutarse en paralelo o en etapas diferidas.
- Cada extractor lee el documento completo. No consume ni modifica resultados
  de otro extractor, ni modifica el documento compartido.
- No se incorpora un gestor de versiones, selección de ejecución vigente ni
  comparación entre versiones. El profile puede evolucionar mediante mejoras
  del prompt; su identificador se registra en los resultados del grafo.
- Las extracciones actuales se pueden eliminar porque los documentos permiten
  recrearlas. Es válido dejar únicamente documentos en el grafo.

## Punto de partida histórico (antes del retiro)

El código anterior tenía un único `ExtractionResult` con título, conceptos,
entidades, afirmaciones y relaciones. Los perfiles `v1` a `v5` cambian las
instrucciones, pero `OpenAIExtractor` siempre utiliza ese mismo contrato.

`ExtractDocument` ejecuta y valida la extracción, guarda archivos de ejecuciones
y actualiza el título. Las composiciones síncronas agregan persistencia en el
grafo y embeddings. `ProcessDocument` implementa la ruta diferida con etapas
`extraction → graph_persistence → claim_embeddings → document_embedding`.

El runtime durable ya dispone de registros en PostgreSQL, outbox, leases,
reintentos y artefactos. Su exclusión actual por usuario y recurso serializa
trabajos del mismo documento: agregar varios jobs sin revisar esa exclusión
no habilitaría paralelismo entre extractores.

La búsqueda utilizada por reflexión consulta afirmaciones sin un selector de
capa. Constelación y sus consumidores también dependen de los contratos actuales.
La PWA tiene llamadas que seleccionan explícitamente `v4` y `v5`.

Referencias locales:

- Los contratos y perfiles exploratorios se eliminaron; consultar el historial Git.
- [Workflow de documento](../src/use_cases/process_document.py).
- [Configuración de submissions](../src/use_cases/submit_processing.py).
- [Runtime durable](processing-runtime.md).
- [Diseño de procesamiento diferido](deferred-processing.md).

## Requerimientos funcionales

| ID | Requerimiento | Criterio de aceptación |
| --- | --- | --- |
| R01 | Conservar originales, identidad, fechas, metadatos y vínculos con audio | Ingestión y recuperación funcionan aun sin extractores configurados |
| R02 | Definir una interfaz común sin contrato semántico único | Dos implementaciones con modelos diferentes usan el mismo pipeline |
| R03 | Admitir métodos de extracción diferentes | El contrato no exige LLM, una sola llamada ni un proveedor particular |
| R04 | Mantener cada capa bajo responsabilidad de su extractor | Su implementación define modelos, validación y representación en el grafo |
| R05 | Separar extracción de persistencia | Un resultado durable puede persistirse después, sin volver a extraer |
| R06 | Admitir dry run | Devuelve resultado validado sin nodos, relaciones ni índices nuevos en el grafo |
| R07 | Seleccionar cero, uno o varios extractores | Configuración explícita del pipeline; nombres desconocidos se rechazan |
| R08 | Ejecutar extractores ortogonales en paralelo | Dos capas del mismo documento progresan concurrentemente sin pisarse |
| R09 | Recuperar etapas de manera independiente | Un fallo de persistencia no repite la extracción; una rama fallida no cancela las exitosas |
| R10 | Consultar por capas | Consultas aceptan una capa, varias o todas, con aislamiento de workspace |
| R11 | Registrar procedencia | Nodos y relaciones derivados identifican capa, ejecución, documento y profile utilizado |
| R12 | Limpiar derivados históricos | El inventario posterior muestra originales preservados y ausencia de los derivados incluidos en la limpieza |

## Contratos y responsabilidades

Contrato público implementado en `src/extractors/base.py` (firma abreviada):

```python
class Extractor(ABC):
    name: str

    async def extract(self, document: Document, *, dry_run=True, run_id=None) -> ExtractionOutput: ...

    async def persist(self, output: ExtractionOutput) -> None: ...
```

`ExtractionOutput` es un envoltorio serializable. Contiene identidad de
ejecución, documento y huella de su contenido, nombre del extractor/capa,
identificador y huella del profile, datos propios del extractor y metadatos
de proveedor cuando corresponda. El workspace se obtiene del contexto confiable,
no de un identificador arbitrario recibido en el resultado.

Cada extractor conoce cómo validar y reconstruir su payload al leer el
artefacto. El envoltorio no vuelve a imponer arrays genéricos de conceptos,
entidades o afirmaciones.

El profile identifica las instrucciones efectivamente usadas. En ejecución
diferida debe verificarse la configuración guardada: un cambio de prompt no
puede aplicarse silenciosamente a un trabajo ya aceptado. Esto es trazabilidad
de ejecución, no gestión de versiones de resultados.

El pipeline coordina selección, scheduling, checkpoints y errores; no contiene
condicionales sobre emociones, eventos u otras entidades de cada capa.
La composición de dependencias construye extractores con proveedores y acceso
al workspace. Ningún extractor depende directamente de HTTP o del broker.

El dry run puede guardar un artefacto y estado operativo para inspección y
recuperación. Significa ausencia de persistencia de la capa en el grafo, no
ausencia de llamadas a proveedores o de todo efecto de infraestructura.

## Ejecución diferida y paralelismo

```text
Documento durable → documento disponible en el grafo
                  ├─ extractor A → artefacto A → persistencia A
                  └─ extractor B → artefacto B → persistencia B
```

El documento debe existir en el grafo independientemente de una extracción.
El pipeline puede terminar allí si no hay extractores seleccionados.

Cada rama conserva estado, artefacto, intentos y error propios. La persistencia
se programa inmediatamente o en una ejecución posterior. Un modo diferido debe
permitir persistir el artefacto existente, además de extraer más tarde.
Los índices/embeddings adicionales son opcionales y definidos por la capa;
no se impone una etapa global de embeddings de afirmaciones.

Reutilizar el runtime existente. Como diseño inicial a concretar en la etapa 2,
usar un procesamiento coordinador y trabajos por extractor, con etapas propias
y agregación del estado del conjunto. La coordinación debe soportar varios
hijos; no asumir que el vínculo singular actual padre/hijo alcanza.

La concurrencia debe estar acotada. Diferentes capas pueden trabajar sobre el
mismo documento; los reintentos de una misma ejecución no pueden competir sin
protección. Revisar los locks actuales y mantener coordinación con borrado,
suspensión del workspace y workers con lease vencido. No quitar simplemente
el lock por documento.

La entrega duplicada y los commits ambiguos deben tolerarse con identidades
estables y persistencia idempotente verificada. Las transacciones se limitan a
una capa; no se exige rollback conjunto de todas las ramas.

Un conjunto con ramas exitosas y fallidas debe mostrar progreso parcial y
errores por extractor. La representación HTTP exacta se define en la etapa 2.
Reintentar una rama no vuelve a ejecutar las ya exitosas.

## Modelo del grafo y consultas

- El documento es el punto común entre capas.
- Cada nodo derivado tiene pertenencia explícita a una capa y documento, e
  identidad que evita colisiones entre extractores y ejecuciones.
- Las relaciones propias de una capa conservan esa misma procedencia.
- No fusionar entidades entre capas ni generar relaciones entre ellas en esta
  implementación. Una vista conjunta puede compartir los documentos fuente.
- La pertenencia a una capa no depende de la versión del profile.
- El filtro de capa se aplica también a búsquedas semánticas, recorridos y
  recuperaciones de contexto, no sólo a la visualización.
- Los filtros de capa nunca reemplazan el aislamiento de usuario/workspace.

No se crea una política automática de resultados vigentes. Los reintentos
reutilizan la ejecución existente. Antes de habilitar reextracción deliberada,
definir su semántica mínima —reemplazo de la capa del documento o acumulación—
sin introducir un gestor de versiones.

## Limpieza y transición

Inventariar por workspace y entorno los nodos, relaciones, índices/vectores,
archivos de extracción y artefactos históricos. Incluir los suplementos y links
de Constelación que dependan de elementos a eliminar. Los registros operativos
de procesamiento se tratan aparte de los resultados: pueden conservarse como
historial terminal, sin ofrecer reintentos hacia artefactos retirados.

La migración de limpieza debe ofrecer inventario/dry run masivo y comprobación
posterior. Descubre automáticamente todos los workspaces de la instancia configurada
y se ejecuta al desplegar, antes de arrancar la aplicación nueva. No borrar originales, audio,
transcripciones, metadatos, usuarios ni configuración de workspaces. No ejecutar
una limpieza global del esquema si afecta documentos o datos ajenos al alcance.

Antes del corte, detener nuevas ejecuciones antiguas y drenar o resolver las
pendientes: un worker viejo no debe recrear derivados después de la limpieza.
Un respaldo permite recuperación mientras se valida la preservación de fuentes.

Tratar explícitamente el embedding de documento: puede conservarse como índice
del original o retirarse para dejar sólo documentos. No confundirlo con vectores
de afirmaciones. La generación de título pasa a una responsabilidad separada,
conservando títulos existentes; no agregar un extractor de título sin decidirlo.

Reflexión, exploración y Constelación no deben presentar éxito vacío o usar
contratos antiguos silenciosamente. Adaptar los consumidores compatibles y
retirar/deshabilitar explícitamente los que requieren una capa aún no definida.
Preservar la recuperación de audio y documentos de la PWA durante el cambio.

## Plan de implementación

La limpieza precede a la construcción de los nuevos extractores. La primera
etapa debe dejar un sistema funcional de documentos sin extracción automática;
no depende de elegir el primer extractor ni de migrar a capas nuevas.

### Etapa 1 — Retiro del proceso exploratorio y limpieza

1. Inventariar dependencias y datos derivados por entorno/workspace, incluyendo
   consumidores de API/PWA y trabajos pendientes del pipeline antiguo.
2. Desacoplar la ingestión y la persistencia del documento en ArcadeDB de la
   extracción. Conservar audio → transcripción → documento y recuperación de
   originales, sin ejecutar perfiles antiguos ni embeddings de afirmaciones.
3. Retirar rutas, composiciones y modelos exploratorios sin consumidores activos;
   retirar reflexión y análisis de Constelación que requieren resultados retirados,
   conservando la API de navegación y el visor del grafo. Adaptar la PWA para conservar ingestión,
   estados y recuperación sin exigir una extracción.
4. Preparar migración masiva de inventario/dry run, respaldo, limpieza y verificación,
   con descubrimiento automático de workspaces, registro de avance y recuperación.
   Definir si se conservan embeddings de documentos o sólo documentos en el
   grafo. Conservar títulos existentes; no generar nuevos mediante el extractor
   retirado.
5. Validar la transición y la limpieza en datos aislados, verificando fuentes
   antes y después y la ingestión de nuevos documentos sin extractores.
6. Integrar la migración al despliegue: detener escritores anteriores, migrar
   todos los workspaces y arrancar la nueva aplicación sólo si termina bien.
   Convertir trabajos pendientes al flujo de documentos, conservando historial
   e invalidando leases y mensajes del flujo retirado.
7. Verificar documentos, audio, transcripciones, metadatos y vínculos preservados;
   ausencia de derivados retirados y ausencia de recreación por workers antiguos.

Salida: base limpia y flujo operativo de documentos sin extractores. Los nuevos
extractores se incorporan en etapas posteriores. El corte sobre una base concreta
se aplica masivamente al desplegar mediante `mirror-deploy/deploy.sh`; este documento
no ejecuta la limpieza.

### Etapa 2 — Cerrar contratos y alcance

1. Elegir el primer extractor real: propósito, payload, evidencia, relaciones,
   persistencia e índices necesarios. El primer extractor aprobado es emociones: ocurrencias
   expresadas por el autor y respaldadas por citas literales, sin inferencias.
2. Definir interfaz, envoltorio durable y registro de extractores.
3. Concretar jobs por capa, agregación, locks, API de selección/dry run/
   persistencia diferida y proyección de estado para PWA.
4. Resolver semántica mínima de reextracción, títulos, embeddings del documento
   y los consumidores a reintroducir sobre las nuevas capas.

Salida: contratos revisables, transiciones y alcance de migración concretos.
La infraestructura común puede avanzar sin elegir taxonomías de negocio;
la implementación del primer extractor requiere su propósito definido.

### Etapa 3 — Núcleo de extractores y grafo de documentos

Implementado para emociones y conectado al procesamiento automático de notas.
Las ramas independientes y las consultas por capas siguen en las etapas 4 y 5.

1. Incorporar interfaz, envoltorio, serialización y composición de dependencias.
2. Reutilizar la persistencia independiente del documento incorporada en la etapa 1.
3. Implementar el primer extractor con su payload y persistencia propia, usando
   el puerto de base existente; extenderlo donde lo requiera la capa.
4. Incorporar procedencia e identidades estables, validación de evidencia según
   el propósito y operación dry run.

Salida: extracción y persistencia invocables separadamente, sin depender del
contrato genérico antiguo, sobre la base limpia de la etapa 1.

### Etapa 4 — Pipeline durable por capas

Implementada la primera integración para emociones: workflow v3 con persistencia
original, extracción y persistencia de capa separadas; configuración aceptada,
artefactos con identidad estable, retries y handoff desde audio. Se mantiene el
workflow v2 de los trabajos anteriores. Pendientes jobs por capa, paralelismo,
estados agregados y API de selección de extractores.

1. Adaptar submissions y workflow de documento para cero o varios extractores.
2. Integrar ramas concurrentes, artefactos y checkpoints por extractor.
3. Adaptar coordinación/locks para permitir capas paralelas y proteger borrados.
4. Implementar persistencia diferida, errores parciales y retry de una rama.
5. Mantener audio → transcripción → documento como flujo previo independiente.

Salida: procesamiento recuperable con paralelismo acotado y sin repetir etapas
ya confirmadas. Reutilizar broker, outbox y runner actuales.

### Etapa 5 — Consultas y clientes

Implementada la lectura de conexiones inmediatas de una nota con filtro por capa,
y la visualización de entidades y evidencia en Constelaciones. `/graph` proyecta
los contenedores administrativos sin modificar la persistencia. El visor ya no
usa filtros por relaciones exploratorias ni un límite de 40 nodos.

1. Agregar filtros de capas a lecturas del grafo y búsquedas aplicables.
2. Adaptar API, eventos, snapshots y PWA a resultados/estados por extractor.
3. Resolver las dependencias de reflexión y Constelación; retirar selección
   implícita de `v4`/`v5` donde deje de tener sentido.
4. Actualizar documentación y contratos públicos afectados.

Salida: vistas de una o varias capas y recuperación de estado sin dependencia
del resultado genérico. No requiere construir una nueva visualización completa.

## Validación exigida

- Dos extractores con contratos diferentes funcionan con el mismo coordinador;
  puede usarse una implementación de prueba para demostrar independencia.
- Evidencia inválida se rechaza cuando la capa exige citas; vacío válido no se
  confunde con un fallo.
- Dry run no escribe derivados ni embeddings de capa en ArcadeDB.
- Un artefacto se reconstruye y persiste en otro proceso sin repetir extracción.
- Dos capas avanzan concurrentemente; una caída no cancela la otra.
- Reinicio después de extracción conserva artefacto; commit ambiguo y entrega
  duplicada no duplican nodos/relaciones.
- Reintento de una rama no repite ramas exitosas ni altera otro workspace.
- Borrado y worker obsoleto no dejan resultados reapareciendo.
- Filtros de una/varias/todas las capas devuelven conjuntos correctos.
- Audio/transcripción se conservan y continúan generando el documento.
- Limpieza en datos de prueba verifica originales antes/después y contempla
  relaciones, vectores, archivos y ejecuciones pendientes.

Usar pruebas unitarias para contratos y coordinación, y entornos aislados de
PostgreSQL/ArcadeDB para concurrencia y persistencia reales. Build y validaciones
de PWA corresponden a sus cambios. Separar evidencia local, integración y
validación desplegada; ninguna sustituye a las otras.

## Fuera de alcance inicial

Gestor de versiones, elección automática de ejecución vigente, fusión de
entidades entre capas, relaciones inferidas entre capas, análisis conjunto
automático, nuevos proveedores obligatorios y rediseño del runtime durable.
