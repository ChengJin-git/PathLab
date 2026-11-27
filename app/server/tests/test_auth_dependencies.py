import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_get_user_from_token_param_uses_scoped_session_without_get_db_dependency():
    from backend.auth.dependencies import get_user_from_token_param

    params = inspect.signature(get_user_from_token_param).parameters
    assert "db" not in params

    expected_user = MagicMock()
    session = MagicMock()
    scoped_cm = AsyncMock()
    scoped_cm.__aenter__.return_value = session
    scoped_cm.__aexit__.return_value = False

    with (
        patch("backend.database.database.read_session", return_value=scoped_cm),
        patch(
            "backend.auth.dependencies._get_user_from_jwt", new_callable=AsyncMock
        ) as get_user,
    ):
        get_user.return_value = expected_user
        user = await get_user_from_token_param(token="jwt-token")

    assert user is expected_user
    get_user.assert_awaited_once_with("jwt-token", session)
    scoped_cm.__aenter__.assert_awaited_once()
    scoped_cm.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_from_header_or_param_uses_scoped_session_and_bearer_header():
    from backend.auth.dependencies import get_user_from_header_or_param

    params = inspect.signature(get_user_from_header_or_param).parameters
    assert "db" not in params

    expected_user = MagicMock()
    session = MagicMock()
    scoped_cm = AsyncMock()
    scoped_cm.__aenter__.return_value = session
    scoped_cm.__aexit__.return_value = False

    with (
        patch("backend.auth.dependencies.safe_session", return_value=scoped_cm),
        patch(
            "backend.auth.dependencies._get_user_from_jwt", new_callable=AsyncMock
        ) as get_user,
    ):
        get_user.return_value = expected_user
        user = await get_user_from_header_or_param(authorization="Bearer abc.def")

    assert user is expected_user
    get_user.assert_awaited_once_with("abc.def", session)
    scoped_cm.__aenter__.assert_awaited_once()
    scoped_cm.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_from_token_param_rejects_missing_token():
    from backend.auth.dependencies import get_user_from_token_param

    with pytest.raises(HTTPException) as exc:
        await get_user_from_token_param(token=None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_user_from_header_or_param_rejects_missing_credentials():
    from backend.auth.dependencies import get_user_from_header_or_param

    with pytest.raises(HTTPException) as exc:
        await get_user_from_header_or_param(token=None, authorization=None)

    assert exc.value.status_code == 401
