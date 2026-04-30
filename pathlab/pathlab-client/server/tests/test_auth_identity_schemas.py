from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from backend.auth.models import User
from backend.auth.schemas import UserCreate, UserRead, UserUpdate
from backend.auth.users import UserManager
from backend.database.database import _plan_user_identity_cleanup


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


def test_startup_identity_cleanup_deduplicates_usernames_deterministically():
    duplicate_id = "22222222-2222-2222-2222-222222222222"
    collision_name = "alice_" + duplicate_id.replace("-", "")[:8]
    rows = [
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "username": collision_name,
            "created_at": datetime(2024, 1, 3),
        },
        {"id": duplicate_id, "username": "alice", "created_at": datetime(2024, 1, 2)},
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "username": "alice",
            "created_at": datetime(2024, 1, 1),
        },
    ]

    updates = _plan_user_identity_cleanup(rows)

    assert "11111111-1111-1111-1111-111111111111" not in updates
    assert updates[duplicate_id] == "alice_222222222222"


def test_startup_identity_cleanup_generates_collision_safe_blank_names_and_is_idempotent():
    blank_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rows = [
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "username": "user_aaaaaaaaaaaa",
            "created_at": None,
        },
        {"id": blank_id, "username": "  ", "created_at": datetime(2024, 1, 1)},
    ]

    updates = _plan_user_identity_cleanup(rows)
    assert updates == {blank_id: "user_aaaaaaaaaaaaaaaa"}

    cleaned_rows = [
        {**row, "username": updates.get(str(row["id"]), row["username"])}
        for row in rows
    ]
    assert _plan_user_identity_cleanup(cleaned_rows) == {}


def test_startup_identity_cleanup_preserves_dirty_user_rows():
    sql_source = (
        Path(__file__).resolve().parents[1] / "backend/database/database.py"
    ).read_text()

    assert "ALTER TABLE users ALTER COLUMN email DROP NOT NULL" in sql_source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username" in sql_source
    assert "DROP CONSTRAINT IF EXISTS" in sql_source
    assert "DROP INDEX IF EXISTS" in sql_source


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
