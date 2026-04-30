from pydantic import ValidationError

from backend.auth.models import User
from backend.auth.schemas import UserCreate, UserRead, UserUpdate


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
