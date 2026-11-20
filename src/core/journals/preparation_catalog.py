"""Initial preparation content; these are writing invitations, not clinical assessment."""

from src.core.journals.catalogs import with_catalogs
from src.core.journals.models import CatalogPrompt
from src.core.journals.templates import PREPARATION_TEMPLATE


def prompts(*rows):
    return tuple(
        CatalogPrompt(key=f"preparation-{key}", gentle=gentle, middle=middle, deep=deep)
        for key, gentle, middle, deep in rows
    )


PREPARATION_TEMPLATE_V2 = with_catalogs(
    PREPARATION_TEMPLATE.model_copy(update={"version": 2}),
    {
        "explore": prompts(
            (
                "motivation",
                "¿Qué te gustaría explorar hoy?",
                "¿Qué te trae a esta búsqueda en este momento?",
                "¿Qué vuelve significativa para vos esta búsqueda?",
            ),
            (
                "moment",
                "¿Qué aspecto de estos días tenés presente?",
                "¿Qué de tu momento actual te gustaría comprender mejor?",
                "¿Qué relación encontrás entre tu momento actual y lo que querés explorar?",
            ),
            (
                "uncertainty",
                "¿Hay alguna duda que quieras dejar escrita?",
                "¿Qué parte de tu búsqueda todavía no sabés cómo nombrar?",
                "¿Qué te gustaría permitirte explorar sin resolverlo todavía?",
            ),
        ),
        "meaning": prompts(
            (
                "meaning",
                "¿Qué palabra de tu intención te llama la atención?",
                "¿Qué significa para vos esa palabra que elegiste?",
                "¿Cómo reconocerías en tu vida eso que querés expresar con esa palabra?",
            ),
            (
                "expectations",
                "¿Qué expectativa tenés presente hoy?",
                "¿Qué esperás encontrar en esta búsqueda?",
                "¿Qué lugar te gustaría darle a esa expectativa si el resultado fuera distinto?",
            ),
            (
                "tension",
                "¿Hay algo de tu intención que hoy quieras revisar?",
                "¿Qué dudas aparecen al volver sobre tu intención?",
                "¿Qué te gustaría comprender de esas dudas sin apurarte a resolverlas?",
            ),
        ),
        "daily-life": prompts(
            (
                "examples",
                "¿Qué momento cotidiano querés dejar anotado?",
                "¿En qué situación reciente reconocés algo de lo que querés explorar?",
                "¿Qué te permite ver esa situación sobre tu intención?",
            ),
            (
                "relationships",
                "¿Qué encuentro de estos días tenés presente?",
                "¿Cómo aparece tu intención en algún vínculo cotidiano?",
                "¿Qué te gustaría comprender de tu lugar en ese vínculo?",
            ),
            (
                "responses",
                "¿Qué reacción tuya te dio curiosidad últimamente?",
                "¿Cómo respondiste en una situación relacionada con tu intención?",
                "¿Qué necesitabas en ese momento, según lo ves hoy?",
            ),
        ),
        "intention": prompts(
            (
                "formulation",
                "¿Qué palabra llevarías hoy a tu intención?",
                "¿Cómo expresarías ahora lo que te gustaría explorar?",
                "¿Qué cambió en tu manera de nombrar tu intención desde que comenzaste?",
            ),
            (
                "supports",
                "¿Qué apoyo te gustaría tener presente?",
                "¿Qué necesitás poder expresar o pedir a quienes te acompañan?",
                "¿Qué límite te gustaría comunicar para cuidar tu proceso?",
            ),
            (
                "openness",
                "¿Qué pregunta te gustaría dejar abierta?",
                "¿Qué te gustaría explorar aunque el resultado sea incierto?",
                "¿Qué lugar querés darles a tus dudas al decidir cómo continuar?",
            ),
        ),
    },
)


# Published versions remain unchanged; presentation metadata is additive.
PREPARATION_TEMPLATE_V3 = PREPARATION_TEMPLATE_V2.model_copy(
    update={"version": 3, "short_description": "Dale forma a tu intención."}
)
