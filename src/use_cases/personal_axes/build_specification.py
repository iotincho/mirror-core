"""Request a semantic criterion and construct the exact evaluated profile."""

from src.core.extractors.personal_axes.models import AxisSpecification, PreviewRequest
from src.core.extractors.personal_axes.ports import CriterionGenerator
from src.core.extractors.personal_axes.profiles import specification_from_criterion


async def build_specification(
    provider: CriterionGenerator,
    request: PreviewRequest,
    configuration: dict,
    previous: AxisSpecification | None = None,
):
    criterion, metadata = await provider.generate_criterion(
        {
            "purpose": request.purpose,
            "adjustments": request.adjustments,
            "previous_instructions": previous.profile.instructions if previous else None,
        }
    )
    return specification_from_criterion(criterion, configuration), metadata
