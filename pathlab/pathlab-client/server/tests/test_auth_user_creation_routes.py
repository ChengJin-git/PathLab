import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from backend.auth.models import User
from gateway.routes import auth as auth_routes


class _ScalarResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _FakeSession:
    def __init__(self, existing_user=None):
        self.existing_user = existing_user
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, _statement):
        return _ScalarResult(self.existing_user)

    def add(self, user):
        if getattr(user, "notify_on_success", None) is None:
            user.notify_on_success = True
        if getattr(user, "notify_on_failed", None) is None:
            user.notify_on_failed = False
        if getattr(user, "notify_on_cancelled", None) is None:
            user.notify_on_cancelled = False
        self.added.append(user)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _user):
        return None


class _FakeAdminLookupSession:
    def __init__(self, admins):
        self.admins = admins

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def execute(self, _statement):
        return _ScalarsResult(self.admins)


def _admin_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.username = "admin"
    user.role = "admin"
    user.is_active = True
    return user


def _make_user(username="existing"):
    return User(
        id=uuid.uuid4(),
        username=username,
        email=None,
        hashed_password="hashed",
        password_sha256="0" * 64,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role="guest",
    )


def _make_admin_user(username, *, registration_email=None, email=None, is_active=True):
    return User(
        id=uuid.uuid4(),
        username=username,
        email=email,
        hashed_password="hashed",
        password_sha256="0" * 64,
        is_active=is_active,
        is_superuser=False,
        is_verified=True,
        role="admin",
        registration_email=registration_email,
    )


def _make_app(session: _FakeSession, *, admin=True):
    app = FastAPI()
    app.include_router(auth_routes.router)

    async def get_db_override():
        return session

    def require_admin_override():
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return _admin_user()

    app.dependency_overrides[auth_routes.get_db] = get_db_override
    app.dependency_overrides[auth_routes.require_admin] = require_admin_override
    return app


async def _post(app: FastAPI, path: str, payload: dict):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=payload)


@pytest.mark.asyncio
async def test_public_register_is_disabled_and_does_not_create_user():
    session = _FakeSession()
    response = await _post(
        _make_app(session),
        "/auth/register",
        {
            "username": "direct_user",
            "password": "secret123",
            "role": "guest",
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"] == "REGISTER_ENDPOINT_DISABLED_USE_REQUEST_ACCESS"
    assert session.added == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_request_access_still_creates_inactive_guest_with_educational_email():
    session = _FakeSession()
    app = _make_app(session)

    with (
        pytest.MonkeyPatch.context() as mp,
    ):
        mp.setattr(auth_routes.Config, "get_global_settings", lambda: {})
        mp.setattr(auth_routes, "_send_application_received_email", AsyncMock())
        mp.setattr(auth_routes, "_send_admin_application_email", AsyncMock())
        response = await _post(
            app,
            "/auth/request-access",
            {
                "username": "self_service_user",
                "password": "secret123",
                "registration_email": "Student@Example.edu",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "self_service_user"
    assert payload["role"] == "guest"
    assert payload["is_active"] is False
    assert payload["registration_email"] == "student@example.edu"

    assert len(session.added) == 1
    created = session.added[0]
    assert created.email == "student@example.edu"
    assert created.registration_email == "student@example.edu"


@pytest.mark.asyncio
async def test_request_access_rejects_non_educational_email():
    response = await _post(
        _make_app(_FakeSession()),
        "/auth/request-access",
        {
            "username": "self_service_user",
            "password": "secret123",
            "registration_email": "student@example.com",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "REGISTRATION_EMAIL_NOT_EDUCATIONAL"


@pytest.mark.asyncio
async def test_admin_application_email_sends_to_active_admin_user_emails():
    applicant = _make_user("self_service_user")
    applicant.nickname = "Self Service"
    applicant.registration_email = "student@example.edu"
    admins = [
        _make_admin_user("primary_admin", registration_email="Primary@Example.edu"),
        _make_admin_user("contact_admin", email="Contact@Example.edu"),
        _make_admin_user("inactive_admin", registration_email="inactive@example.edu", is_active=False),
        _make_admin_user("no_email_admin"),
    ]
    send_templated_email = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            auth_routes,
            "async_session",
            lambda: _FakeAdminLookupSession(admins),
            raising=False,
        )
        mp.setattr(auth_routes, "send_templated_email", send_templated_email)
        await auth_routes._send_admin_application_email(applicant)

    assert send_templated_email.await_count == 2
    recipients = [call.kwargs["to_email"] for call in send_templated_email.await_args_list]
    assert recipients == ["primary@example.edu", "contact@example.edu"]
    for call in send_templated_email.await_args_list:
        assert call.kwargs["template_key"] == "admin_new_user_registration_notice"
        assert call.kwargs["for_admin"] is True
        assert call.kwargs["context"]["username"] == "self_service_user"


@pytest.mark.asyncio
async def test_admin_create_user_creates_active_user_without_registration_email():
    session = _FakeSession()

    with pytest.MonkeyPatch.context() as mp:
        activation_email = AsyncMock()
        application_email = AsyncMock()
        admin_email = AsyncMock()
        mp.setattr(auth_routes, "_send_activation_email", activation_email)
        mp.setattr(auth_routes, "_send_application_received_email", application_email)
        mp.setattr(auth_routes, "_send_admin_application_email", admin_email)
        response = await _post(
            _make_app(session),
            "/auth/users",
            {
                "username": " created_by_admin ",
                "password": "secret123",
                "nickname": "Admin Created",
                "role": "pathologist",
                "registration_email": "   ",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "created_by_admin"
    assert payload["role"] == "pathologist"
    assert payload["is_active"] is True
    assert payload["registration_email"] is None

    assert len(session.added) == 1
    created = session.added[0]
    assert created.first_activated_at is not None
    assert created.password_sha256 is not None
    assert len(created.password_sha256) == 64
    activation_email.assert_not_called()
    application_email.assert_not_called()
    admin_email.assert_not_called()


@pytest.mark.asyncio
async def test_admin_create_user_normalizes_registration_email():
    session = _FakeSession()
    response = await _post(
        _make_app(session),
        "/auth/users",
        {
            "username": "notify_user",
            "password": "secret123",
            "role": "guest",
            "registration_email": " Notify@Example.EDU ",
        },
    )

    assert response.status_code == 200
    assert response.json()["registration_email"] == "notify@example.edu"
    assert session.added[0].registration_email == "notify@example.edu"


@pytest.mark.asyncio
async def test_admin_create_user_rejects_short_password_and_duplicates():
    short_response = await _post(
        _make_app(_FakeSession()),
        "/auth/users",
        {"username": "short_password", "password": "12345", "role": "guest"},
    )
    assert short_response.status_code == 400
    assert short_response.json()["detail"] == "REGISTER_PASSWORD_TOO_SHORT"

    duplicate_response = await _post(
        _make_app(_FakeSession(existing_user=_make_user("duplicate_user"))),
        "/auth/users",
        {"username": "duplicate_user", "password": "secret123", "role": "guest"},
    )
    assert duplicate_response.status_code == 400
    assert duplicate_response.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_user():
    response = await _post(
        _make_app(_FakeSession(), admin=False),
        "/auth/users",
        {"username": "blocked", "password": "secret123", "role": "guest"},
    )

    assert response.status_code == 403
