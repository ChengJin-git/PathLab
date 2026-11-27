"""A handoff may narrow retrieval permissions, never widen its workspace."""

from uuid import UUID

from backend.auth.models import User
from backend.database.database import safe_session
from backend.services.workspaces import resolve_scope


async def require_connector(session, connector):
    meta = session.recovery_metadata or {}
    async with safe_session() as db:
        owner = await db.get(User, UUID(session.user_id))
        scope = await resolve_scope(db, owner, meta.get('workspace_id'))
    allowed = set(scope.enabled_connectors).intersection(meta.get('enabled_connectors', []))
    if connector not in allowed:
        raise ValueError('This connector is disabled for this task; continue with existing inputs or ask the user to change the task settings.')
