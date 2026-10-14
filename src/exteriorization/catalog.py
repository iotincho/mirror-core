"""Version 1 of the curated general-purpose question bank."""

from src.exteriorization.contracts import Trigger

CATALOG = tuple(
    Trigger(candidate_id=identifier, category=category, question=question)
    for identifier, category, question in (
        ("daily_01", "registro", "¿Cómo estuvo tu día?"),
        ("daily_02", "registro", "¿Qué momento de hoy te gustaría dejar escrito?"),
        ("daily_03", "registro", "¿Qué te sorprendió hoy?"),
        ("pleasant_01", "agradable", "¿Qué te hizo sentir bien hoy?"),
        ("pleasant_02", "agradable", "¿Qué disfrutaste hoy, aunque haya sido algo pequeño?"),
        ("pleasant_03", "agradable", "¿Qué te gustaría recordar de hoy?"),
        ("friction_01", "dificultad", "¿Hubo algo que te incomodó hoy y quieras contar?"),
        ("friction_02", "dificultad", "¿Qué fue difícil hoy para vos?"),
        ("friction_03", "dificultad", "¿Hay algo de hoy que todavía te esté dando vueltas?"),
        ("explore_01", "exploración", "¿Qué ocupa tu cabeza en este momento?"),
        ("explore_02", "exploración", "¿Hay alguna idea que quieras poner en palabras?"),
        ("explore_03", "exploración", "¿Qué te gustaría entender un poco mejor de tu día?"),
    )
)
