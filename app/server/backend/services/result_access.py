"""Authoritative ownership for model outputs, independent of input dataset grants."""

from fastapi import HTTPException
from sqlalchemy import or_, select

from backend.database.models import AIResult, AITask, TrainingTask


def owned_result_clause(user):
    if user.is_admin():
        from sqlalchemy import true

        return true()
    uid = str(user.id)
    return or_(
        AIResult.task_id.in_(
            select(TrainingTask.task_id).where(TrainingTask.user_id == uid)
        ),
        AIResult.task_id.in_(select(AITask.task_id).where(AITask.user_id == uid)),
    )


async def authorized_task_ids(db, user, task_ids):
    identities = set(task_ids)
    if not identities:
        return set()
    training = select(TrainingTask.task_id).where(TrainingTask.task_id.in_(identities))
    inference = select(AITask.task_id).where(AITask.task_id.in_(identities))
    if not user.is_admin():
        training = training.where(TrainingTask.user_id == str(user.id))
        inference = inference.where(AITask.user_id == str(user.id))
    return set((await db.scalars(training.union(inference))).all())


async def require_result_task(db, user, task_id):
    if task_id not in await authorized_task_ids(db, user, [task_id]):
        raise HTTPException(404, "Prediction task not found")


async def select_result_artifact(db, user, wsi_id, task_id, artifact, fold_key=None):
    """Resolve an owned bundle before preprocessing can select any default result."""
    import asyncio
    from backend.ai.result_store import AIResultStore
    from backend.common.config import Config

    store = AIResultStore(Config.get_uploads_dir())
    if task_id:
        await require_result_task(db, user, task_id)
        return task_id
    artifacts = await asyncio.to_thread(store.list_wsi_artifacts, wsi_id)
    candidates = [
        item["task_id"]
        for item in artifacts
        if item["artifact"] == artifact
        and (fold_key is None or item.get("fold_key") == fold_key)
    ]
    allowed = await authorized_task_ids(db, user, candidates)
    selected = next(
        (identity for identity in reversed(candidates) if identity in allowed), None
    )
    if selected is None:
        raise HTTPException(
            404, "No prediction from your tasks is available for this image"
        )
    return selected
