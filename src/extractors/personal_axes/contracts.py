"""Legacy HTTP error compatibility; canonical models/rules live in core."""

from src.core.extractors.personal_axes.models import AxisError as CoreAxisError


class AxisError(CoreAxisError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.status = status
