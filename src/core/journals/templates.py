"""Versioned initial content; no product-specific states enter the journal engine."""

from uuid import NAMESPACE_URL, uuid5

from src.core.journals.models import JournalTemplate, StageDefinition

PREPARATION_TEMPLATE = JournalTemplate(
    id=uuid5(NAMESPACE_URL, "el-espejo:journal:preparation-intention"),
    version=1,
    name="Preparación e intención",
    purpose="Acompañar la exploración de una intención personal durante la preparación.",
    instructions=(
        "Invitar a explorar sin inducir recuerdos, causas ni resultados esperados. "
        "Respetar límites y dar lugar a posponer o decidir no continuar. "
        "No evaluar aptitud clínica ni recomendar sustancias, dosis o cambios de medicación."
    ),
    stages=(
        StageDefinition(
            key="explore",
            name="Qué quiero explorar",
            duration_days=7,
            objective="Identificar una inquietud o propósito primario, todavía provisional.",
            instructions="Permitir que la intención empiece imprecisa y permanezca abierta.",
        ),
        StageDefinition(
            key="meaning",
            name="Qué significa para mí",
            duration_days=7,
            objective="Explorar las palabras elegidas, los deseos, expectativas y tensiones.",
            instructions="No suponer causas ni conducir hacia una explicación particular.",
        ),
        StageDefinition(
            key="daily-life",
            name="Cómo aparece en mi vida",
            duration_days=7,
            objective="Reconocer situaciones cotidianas y vínculos relacionados con el propósito.",
            instructions="Invitar a nombrar ejemplos concretos sin exigir profundizar.",
        ),
        StageDefinition(
            key="intention",
            name="Qué intención quiero llevar",
            duration_days=7,
            objective="Revisar lo escrito y formular una intención propia, flexible y revisable.",
            instructions="Incluir dudas, límites y apoyos, sin exigir una conclusión perfecta.",
        ),
    ),
)
