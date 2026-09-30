from types import SimpleNamespace

import pytest
from fastapi_users.exceptions import InvalidPasswordException

from src.main import app
from src.user_management.authentication import COOKIE_NAME, cookie_transport
from src.user_management.manager import UserManager


def test_user_management_routes_and_cookie_contract_are_exposed() -> None:
    paths = app.openapi()["paths"]

    assert {"/auth/register", "/auth/login", "/auth/logout", "/auth/session"} <= set(paths)
    assert cookie_transport.cookie_name == COOKIE_NAME == "el_espejo_session"
    assert cookie_transport.cookie_httponly is True
    assert cookie_transport.cookie_samesite == "strict"


@pytest.mark.anyio
async def test_user_manager_rejects_weak_and_email_derived_passwords() -> None:
    manager = UserManager(SimpleNamespace(), "test-secret")
    user = SimpleNamespace(email="alex@example.com")

    with pytest.raises(InvalidPasswordException) as short_password:
        await manager.validate_password("short", user)
    assert short_password.value.reason == "Password should be at least 12 characters"

    with pytest.raises(InvalidPasswordException) as email_password:
        await manager.validate_password("alex@example.com-password", user)
    assert email_password.value.reason == "Password should not contain the email address"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
