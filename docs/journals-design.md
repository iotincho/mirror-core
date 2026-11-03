# Journals · Definición de producto

Estado: referencia de exploración y diseño acordada el 2 de noviembre de 2026.
Describe la intención de producto. Las etapas 1–4 están implementadas
localmente; su alcance y límites están en [contratos](journals-contract.md).
El resto de la funcionalidad sigue pendiente.
Los contratos vigentes de pregunta diaria siguen en
[pregunta diaria v2](daily-question-v2-contract.md).
El [plan de implementación](journals-implementation-plan.md) detalla las
responsabilidades, entregas y decisiones propuestas para los aspectos abiertos.

## Propósito

Un journal es un recorrido de escritura con propósito, etapas y memoria propia.
Orienta la pregunta diaria hacia algo que el usuario quiere explorar, manteniendo
la escritura libre habitual disponible para notas fuera de ese recorrido.

El propósito general del journal y la intención personal son distintos. El primero
orienta el acompañamiento; la segunda puede empezar imprecisa, cambiar y quedar
abierta. Descubrirla es parte del proceso, no un requisito para comenzar.

El primer uso será acompañar diariamente a una persona durante la preparación
para una experiencia psicodélica, junto con tres o cuatro sesiones semanales.
Las sesiones permiten revisar la dirección y ajustar el recorrido cuando haga
falta. La app sostiene la reflexión entre sesiones. Volver sobre la intención
busca mantenerla presente; no se promete que aparezca durante la experiencia.

## Modelo conceptual reutilizable

| Concepto | Responsabilidad |
| --- | --- |
| Template de journal | Definición reutilizable: nombre, propósito general, orientación para preguntas y etapas iniciales. La biblioteca guarda templates. |
| Etapa del template | Nombre, objetivo de exploración, duración prevista e indicaciones específicas para generar preguntas. |
| Recorrido personal | Instancia de un template para un usuario: configuración propia, estado, calendario, entradas e historial. |
| Etapa del recorrido | Etapa concreta de esa instancia, con objetivo, indicaciones, duración, fechas y ajustes propios. |

Activar un template crea un recorrido independiente con una copia de su definición
y una referencia a la versión de origen. Cambiar el template no modifica recorridos
existentes; ajustar un recorrido no modifica el template. Una persona puede
realizar el mismo journal varias veces en distintos momentos de su vida.

El modelo general contempla etapas ordenadas y propósitos diversos. Las fases
«preparación» e «integración» y su contenido pertenecen al journal de psicodélicos;
no deben convertirse en estados obligatorios de todos los journals.

## Activación, calendario y etapas

- Inicialmente la activación se hace desde administración para un usuario concreto.
- Sólo un recorrido activo conduce la pregunta diaria por usuario. Pueden
  conservarse otros recorridos pausados o terminados.
- Cada etapa tiene un objetivo y una duración. El template define el recorrido
  completo y debe poder funcionar sin ajustes posteriores.
- **El avance de etapas es automático por defecto**, según el calendario del
  recorrido. No requiere una sesión ni aprobación administrativa para cada paso.
- Los ajustes desde administración son opcionales: permiten adaptar objetivos,
  indicaciones, duraciones y etapas al proceso particular.
- No responder un día no acumula preguntas pendientes ni convierte el recorrido
  en una deuda de escritura. La participación no determina el avance de etapas.
- Se debe poder pausar, extender y cerrar el recorrido conservando su historia.

Queda por precisar la semántica temporal de pausa, reanudación y cambios de
duración, así como el cierre al finalizar la última etapa. El avance automático
entre etapas es una decisión acordada, independiente de esos detalles.

## Experiencia cotidiana y pertenencia

La pregunta de hoy debe identificar claramente el journal al que pertenece.
Responderla crea una nota vinculada al recorrido, a la etapa y a la pregunta exacta.
El usuario también puede escribir o grabar espontáneamente dentro del journal sin
responder una pregunta. Las notas normales mantienen su espacio de escritura libre.

El recorrido reúne sus preguntas y entradas, incluida la escritura espontánea.
Su vista permite consultar la etapa actual, el historial y la intención en
construcción. Las entradas continúan siendo notas de Mirror: se reutilizan las
capacidades existentes de texto, audio y procesamiento.

La vinculación histórica no depende de cuál sea la etapa activa al leer o
sincronizar una respuesta. Cambiar de etapa o ajustar su definición no debe
reasignar respuestas previas ni reinterpretar preguntas ya emitidas.

## Generación de la pregunta diaria

La generación combina:

1. El propósito y la orientación general del journal.
2. El objetivo y las indicaciones de la etapa actual.
3. Los ajustes específicos del recorrido personal.
4. La intención expresada por el usuario y las entradas de ese journal.
5. Las preferencias y los límites del usuario sobre qué explorar.

El objetivo expresa para qué se pregunta; las indicaciones orientan cómo hacerlo.
Ejemplo de objetivo: comprender qué significa para esa persona la necesidad de
aprobación. Ejemplo de indicación: invitar a reconocer situaciones concretas sin
suponer sus causas ni conducir hacia una explicación familiar.

Se combina una estructura editorial con adaptación a las respuestas. Las preguntas
no son una secuencia fija que ignora al usuario, y la adaptación debe conservar
el propósito del recorrido. Las etapas anteriores siguen aportando contexto al
cambiar el foco de exploración.

Para el primer alcance, las preguntas usan las entradas del propio journal.
Las notas comunes quedan fuera por defecto; su incorporación explícita puede
diseñarse después. Se evita comenzar con una mezcla de contextos con pesos
difíciles de explicar.

Se conservan las opciones de profundidad, alternativas y feedback de la pregunta
diaria. Activar un journal, cambiar de etapa o recibir un ajuste administrativo
no levanta límites como «no quiero hablar de esto». El contenido curado y las
alternativas también deben respetar el propósito del journal y esos límites.

## Ajustes desde administración

El panel de administración permite activar un template, definir el inicio y
adaptar la copia personal del recorrido. Las acciones previstas son:

- Ajustar el propósito, los objetivos y las indicaciones del recorrido.
- Cambiar duración y configuración de la etapa actual o de etapas pendientes.
- Agregar, quitar o reordenar etapas futuras.
- Extender la etapa actual o avanzar a la siguiente de forma explícita.
- Pausar, reanudar y cerrar el recorrido.

Por ejemplo, después de una sesión el objetivo «explorar qué significa tener más
confianza» puede ajustarse a «explorar cómo vive la confianza al expresar
desacuerdo, especialmente cuando teme decepcionar».

Los ajustes orientan preguntas futuras. Las preguntas ya emitidas y sus respuestas
conservan el contexto y la versión con que fueron creadas. Se necesita un historial
acotado que permita entender cuándo y cómo cambió la dirección.

Las indicaciones para generar preguntas se distinguen de cualquier registro
privado de una sesión. Para este alcance se incorpora sólo lo necesario para
orientar el journal y acordado con el usuario. Administrar la configuración no
implica por sí mismo permiso para leer todas sus notas. Los permisos concretos
deben definirse antes de implementar, usando la aplicación administrativa separada.

## Primer template: preparación e intención

El journal de psicodélicos contempla preparación e integración como fases con
objetivos diferentes. El primer alcance se concentra en preparación. Este es
el borrador inicial de sus etapas; las duraciones son hipótesis de producto,
no un protocolo clínico.

| Etapa | Duración inicial | Objetivo | Ejemplo de pregunta |
| --- | --- | --- | --- |
| Qué quiero explorar | 7 días | Identificar una inquietud o propósito primario, todavía provisional. | ¿Qué está pasando en tu vida que vuelve significativa esta búsqueda ahora? |
| Qué significa para mí | 7 días | Explorar las palabras elegidas, los deseos, las expectativas y las tensiones que contienen. | Cuando decís que querés tener más confianza, ¿qué significa para vos? |
| Cómo aparece en mi vida | 7 días | Reconocer situaciones cotidianas, vínculos y respuestas concretas relacionadas con ese propósito. | ¿En qué momento de estos días reconociste eso que querés explorar? |
| Qué intención quiero llevar | 7 días | Revisar lo escrito y formular una intención propia, incluyendo dudas, límites y apoyos. | Con lo que escribiste hasta ahora, ¿qué te gustaría explorar, aunque el resultado sea incierto? |

Este borrador puede adaptarse para un acompañamiento de tres o cuatro semanas.
No se exige una conclusión determinada ni una formulación perfecta de la intención.
Las preguntas deben permitir al usuario nombrar su experiencia sin sugerir
diagnósticos, recuerdos, causas o resultados esperados.

La intención es editable por el usuario. Puede comenzar como «quiero dejar de
sentirme bloqueado» y evolucionar hacia «quiero comprender qué me pasa cuando
siento que decepciono a otros». Conviene conservar las formulaciones previas.
Una eventual síntesis sugerida por Mirror debe poder revisarse y apoyarse en las
entradas originales; el usuario decide si lo representa.

Posponer o decidir no realizar la experiencia son desenlaces válidos y deben
permitir un cierre con sentido. Completar el recorrido no acredita preparación
clínica. El journal acompaña la reflexión; no determina aptitud para consumir ni
recomienda sustancias, dosis o cambios de medicación.

La futura transición a integración debe ser explícita: llegar a una fecha no
confirma que ocurrió una experiencia. Se distinguirá ese cambio de fase del
avance automático ordinario entre etapas de preparación. Integración podrá
retomar la intención previa y dar espacio a lo inesperado o a la falta de una
conclusión clara; su contenido queda fuera del primer alcance.

## Alcance inicial y evolución

El primer alcance comprende templates con etapas, activación y ajustes desde
administración, un recorrido activo por usuario, avance automático de etapas,
preguntas contextualizadas y notas vinculadas al recorrido y su historia.
La intención personal editable forma parte de la experiencia propuesta.

Se difieren la biblioteca pública, la creación de journals por usuarios, el
contenido de integración y los análisis especializados. La estructura debe
permitir otros templates sin rehacer el ciclo de vida de los recorridos ni
introducir reglas de psicodélicos en las capacidades generales.

Más adelante pueden explorarse síntesis, temas recurrentes, preguntas abiertas
y cambios de intención, con referencias a las entradas y posibilidad de revisión.
No se plantea una puntuación psicológica ni un indicador de preparación.

La hipótesis a validar es si la continuidad entre preguntas, respuestas y propósito
ayuda a desarrollar una intención que el usuario reconoce como propia. Completar
todos los días no es la medida central de éxito.

## Decisiones pendientes antes de implementar

- Reglas exactas de calendario, zona horaria, pausa y reanudación, y efecto de
  ajustes de duración sobre las etapas siguientes.
- Comportamiento al terminar la última etapa y retorno a la pregunta diaria libre.
- Tratamiento de preguntas preparadas pero aún no emitidas cuando cambia la etapa
  o su configuración, conservando las que ya fueron publicadas.
- Permisos administrativos y visibilidad para el usuario de los ajustes realizados.
- Flujo de edición e historial de la intención personal.
- Contratos de pertenencia de notas y respuestas, incluida sincronización tardía,
  idempotencia y conservación del contexto histórico.

Estas decisiones se resolverán en un diseño de implementación posterior. Este
documento no fija tablas, endpoints, prompts finales ni una distribución nueva de
responsabilidades técnicas. La implementación deberá respetar la
[arquitectura vigente](../ARCHITECTURE.md) y reutilizar los contratos existentes.
