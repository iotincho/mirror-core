"""HTTP endpoint for auditable evidence-bound reflections."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.schemas.reflections import ResolveQuestionRequest
from src.dependencies import get_resolve_question
from src.services.reflection_store import ReflectionRun
from src.use_cases.resolve_question import ReflectionRunFailedError, ResolveQuestion

router = APIRouter(prefix="/resolve", tags=["reflection"])


@router.post("", response_model=ReflectionRun)
async def resolve_question(
    request: ResolveQuestionRequest,
    use_case: Annotated[ResolveQuestion, Depends(get_resolve_question)],
) -> ReflectionRun:
    try:
        return await use_case.execute(request.question, request.limit, request.profile_name)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ReflectionRunFailedError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Reflection is temporarily unavailable", "run_id": error.run_id},
        ) from error
