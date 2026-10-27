"""System-level HTTP endpoints."""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Expose process health only; dependency connectivity is checked separately."""
    return {"status": "ok"}
