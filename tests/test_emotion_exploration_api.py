"""Scoped emotion exploration routes, bounded inputs and safe storage errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_graph_store
from src.graph.contracts import EmotionCatalog, EmotionExploration
from src.main import app
from src.services.graph_store import EmotionNotFoundError, GraphPersistenceError
from src.user_management.authentication import get_database_strategy
from src.user_management.manager import get_user_manager


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def api():
    graph = SimpleNamespace(
        list_emotions=AsyncMock(
            return_value=EmotionCatalog(emotions=[], total=0, next_offset=None)
        ),
        explore_emotion=AsyncMock(
            return_value=EmotionExploration(
                root_id="EmotionGroup:miedo",
                depth=2,
                limit=100,
                nodes=[],
                edges=[],
                truncated=False,
                next_limit=None,
            )
        ),
    )
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield client, graph
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_catalog_and_exploration_forward_only_bound_workspace_parameters(api):
    client, graph = api
    response = await client.get("/graph/emotions?offset=5&limit=20")
    assert response.status_code == 200 and response.json()["total"] == 0
    graph.list_emotions.assert_awaited_once_with(offset=5, limit=20)
    response = await client.get(
        "/graph/emotions/explore", params={"emotion": "miedo", "depth": 2, "limit": 100}
    )
    assert response.status_code == 200 and response.json()["depth"] == 2
    graph.explore_emotion.assert_awaited_once_with("miedo", depth=2, limit=100)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params",
    [{"depth": 0}, {"depth": 4}, {"limit": 1}, {"limit": 501}, {"emotion": " "}, {"emotion": ""}],
)
async def test_exploration_rejects_unbounded_or_blank_inputs(api, params):
    client, graph = api
    response = await client.get("/graph/emotions/explore", params={"emotion": "miedo", **params})
    assert response.status_code == 422
    graph.explore_emotion.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,status",
    [(EmotionNotFoundError("absent"), 404), (GraphPersistenceError("truncated"), 502)],
)
async def test_missing_emotion_and_incomplete_graph_never_report_success(api, error, status):
    client, graph = api
    graph.explore_emotion.side_effect = error
    assert (await client.get("/graph/emotions/explore?emotion=miedo")).status_code == status


@pytest.mark.anyio
async def test_catalog_failure_never_reports_no_emotions(api):
    client, graph = api
    graph.list_emotions.side_effect = GraphPersistenceError("unavailable")
    assert (await client.get("/graph/emotions")).status_code == 502


@pytest.mark.anyio
@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 201}])
async def test_catalog_rejects_invalid_pagination(api, params):
    client, graph = api
    assert (await client.get("/graph/emotions", params=params)).status_code == 422
    graph.list_emotions.assert_not_awaited()


@pytest.mark.anyio
async def test_emotion_routes_require_authentication():
    app.dependency_overrides.update(
        {get_user_manager: lambda: object(), get_database_strategy: lambda: object()}
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get("/graph/emotions")).status_code == 401
            assert (await client.get("/graph/emotions/explore?emotion=miedo")).status_code == 401
    finally:
        app.dependency_overrides.clear()
