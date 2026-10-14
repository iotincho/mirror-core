"""Selection has no persistence, network, workspace or model dependencies."""

import random
from collections.abc import Callable, Sequence

from src.exteriorization.catalog import CATALOG
from src.exteriorization.contracts import EngineContext, Trigger


def select_trigger(
    context: EngineContext,
    *,
    choose: Callable[[Sequence[Trigger]], Trigger] = random.choice,
    catalog: tuple[Trigger, ...] = CATALOG,
) -> Trigger:
    if not catalog:
        raise ValueError("empty_catalog")
    if not context.history:
        return next((item for item in catalog if item.candidate_id == "daily_01"), catalog[0])
    recent = {item.candidate_id for item in context.history[:7]}
    # Relax recency first if the catalog has changed or has been exhausted.
    candidates = tuple(item for item in catalog if item.candidate_id not in recent) or catalog
    different = tuple(item for item in candidates if item.category != context.history[0].category)
    # Relax category preference only when there is no alternative.
    return choose(different or candidates)
