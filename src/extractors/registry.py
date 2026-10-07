"""Constructor registry: orchestration never switches on a layer's payload."""

from collections.abc import Callable

from src.extractors.base import Extractor


class ExtractorRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[..., Extractor]] = {}

    def register(self, name: str, factory: Callable[..., Extractor]):
        if name in self._factories:
            raise ValueError("extractor_already_registered")
        self._factories[name] = factory

    def create(self, name: str, **dependencies) -> Extractor:
        if name not in self._factories:
            raise ValueError("unknown_extractor")
        extractor = self._factories[name](**dependencies)
        if extractor.name != name:
            raise ValueError("extractor_registration_mismatch")
        return extractor
