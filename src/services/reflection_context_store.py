"""Graph boundary for contextualizing retrieved claims."""

from typing import Protocol

from src.reflection.contracts import ClaimRelation


class ReflectionContextStore(Protocol):
    async def get_claim_relations(self, claim_ids: list[str]) -> list[ClaimRelation]: ...


class ReflectionContextStoreError(RuntimeError):
    """Raised when graph context cannot be loaded."""
