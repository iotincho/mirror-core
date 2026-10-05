"""Routes for semantic retrieval, without reflective generation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.schemas.search import SearchClaimsRequest, SearchRequest
from src.dependencies import get_search_semantically, get_search_similar_claims
from src.embeddings.contracts import SearchResult, SimilarClaim
from src.use_cases.search_semantically import (
    SearchSemantically,
)
from src.use_cases.search_semantically import (
    SemanticSearchFailedError as MixedSemanticSearchFailedError,
)
from src.use_cases.search_similar_claims import SearchSimilarClaims, SemanticSearchFailedError

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=list[SearchResult])
async def search(
    request: SearchRequest,
    use_case: Annotated[SearchSemantically, Depends(get_search_semantically)],
) -> list[SearchResult]:
    """Return score-ordered document and claim candidates for a semantic query."""
    try:
        return await use_case.execute(request.query, request.limit)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except MixedSemanticSearchFailedError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is temporarily unavailable",
        ) from error


@router.post("/claims", response_model=list[SimilarClaim])
async def search_claims(
    request: SearchClaimsRequest,
    use_case: Annotated[SearchSimilarClaims, Depends(get_search_similar_claims)],
) -> list[SimilarClaim]:
    """Return semantically close claims with their original-document evidence."""
    try:
        return await use_case.execute(request.query, request.limit)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except SemanticSearchFailedError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is temporarily unavailable",
        ) from error
