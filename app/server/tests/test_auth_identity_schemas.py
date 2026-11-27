from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from backend.auth.models import User
from backend.auth.schemas import UserCreate, UserRead, UserUpdate
from backend.auth.users import UserManager


def test_user_read_exposes_username_and_contact_email_fields():
    payload = {
        "id": "2f00557d-3fcf-4d6b-9886-13e5f977f79e",
        "username": "alice",
        "email": "alice@example.edu",
        "is_active": True,
        "is_superuser": False,
        "is_verified": True,
        "role": "guest",
    }

    model = UserRead.model_validate(payload)
    assert model.username == "alice"
    assert model.email == "alice@example.edu"


def test_user_create_rejects_contact_email_without_username():
    try:
        UserCreate.model_validate(
            {
                "email": "legacy_user",
                "password": "secret123",
                "role": "guest",
            }
        )
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError when username is missing")


def test_user_create_keeps_email_as_contact_email():
    model = UserCreate.model_validate(
        {
            "username": " alice ",
            "email": "alice@example.edu",
            "password": "secret123",
            "role": "guest",
        }
    )
    assert model.username == "alice"
    assert model.email == "alice@example.edu"


def test_user_create_rejects_missing_username_and_email():
    try:
        UserCreate.model_validate({"password": "secret123", "role": "guest"})
    except ValidationError:
        return
    raise AssertionError("Expected ValidationError when identity is missing")


def test_user_update_email_is_contact_email_only():
    model = UserUpdate.model_validate({"email": "new_contact@example.edu"})
    assert model.email == "new_contact@example.edu"


def test_user_model_identity_and_contact_email_column_metadata():
    email_col = User.__table__.columns["email"]
    username_col = User.__table__.columns["username"]

    assert email_col.nullable is True
    assert email_col.unique is not True
    assert username_col.nullable is False
    assert username_col.unique is True
    assert username_col.index is True


def test_user_manager_hooks_log_username_not_email():
    """UserManager lifecycle hooks must identify users by username, not email."""
    user_db = MagicMock()
    user_db.update = AsyncMock(return_value=None)
    manager = UserManager(user_db)

    user = MagicMock()
    user.id = "test-id"
    user.username = "alice"
    user.email = "alice@example.edu"
    user.role = "guest"

    import asyncio
    import logging

    logs: list[str] = []
    logger = logging.getLogger("backend.auth.users")

    with patch.object(logger, "info", side_effect=logs.append):
        asyncio.run(manager.on_after_register(user))
        asyncio.run(manager.on_after_forgot_password(user, "token123"))
        asyncio.run(manager.on_after_request_verify(user, "token456"))
        asyncio.run(manager.on_after_login(user))

    for msg in logs:
        # Principal identity must be username, not email
        assert not msg.startswith("User alice@example.edu"), f"Hook log used email as principal identity: {msg}"
        assert "User alice" in msg, f"Hook log missing username identity: {msg}"


def test_user_manager_hooks_include_contact_email_when_present():
    """When user has an email, hooks should include it explicitly as contact_email."""
    user_db = MagicMock()
    user_db.update = AsyncMock(return_value=None)
    manager = UserManager(user_db)

    user = MagicMock()
    user.id = "test-id"
    user.username = "bob"
    user.email = "bob@example.edu"
    user.role = "admin"

    import asyncio
    import logging

    logs: list[str] = []
    logger = logging.getLogger("backend.auth.users")

    with patch.object(logger, "info", side_effect=logs.append):
        asyncio.run(manager.on_after_register(user))
        asyncio.run(manager.on_after_login(user))

    for msg in logs:
        assert "contact_email=bob@example.edu" in msg, f"Missing contact_email in: {msg}"


def test_user_manager_hooks_omit_contact_email_when_missing():
    """When user has no email, hooks should not include a contact_email fragment."""
    user_db = MagicMock()
    user_db.update = AsyncMock(return_value=None)
    manager = UserManager(user_db)

    user = MagicMock()
    user.id = "test-id"
    user.username = "charlie"
    user.email = None
    user.role = "guest"

    import asyncio
    import logging

    logs: list[str] = []
    logger = logging.getLogger("backend.auth.users")

    with patch.object(logger, "info", side_effect=logs.append):
        asyncio.run(manager.on_after_register(user))
        asyncio.run(manager.on_after_login(user))

    for msg in logs:
        assert "contact_email" not in msg, f"Unexpected contact_email in: {msg}"
