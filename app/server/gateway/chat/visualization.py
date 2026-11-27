"""Bounded, authorized evidence for result-dependent image cards."""

import asyncio
from collections import defaultdict
from zipfile import BadZipFile

from sqlalchemy import select, union_all

from backend.database.models import AIResult, WSISlide


def _artifact_evidence(rows):
    if not rows:
        return {}
    from backend.ai.result_store import AIResultStore
    from backend.common.config import Config

    store = AIResultStore(Config.get_uploads_dir())
    evidence = {}
    by_task = defaultdict(list)
    for dataset_id, task_id, wsi_id in rows:
        by_task[task_id].append((dataset_id, wsi_id))
    for task_id, items in by_task.items():
        try:
            artifacts_by_slide = store.list_task_artifacts_for_wsis(
                task_id, [wsi_id for _, wsi_id in items]
            )
        except (OSError, ValueError, BadZipFile):
            continue
        for dataset_id, wsi_id in items:
            kinds = {item["artifact"] for item in artifacts_by_slide.get(wsi_id, [])}
            if kinds:
                evidence.setdefault(dataset_id, []).append(
                    {
                        "task_id": task_id,
                        "wsi_id": wsi_id,
                        "has_heatmap": bool(kinds & {"attention", "cam"}),
                        "has_prediction_mask": "pred_mask" in kinds,
                        "has_result": "result" in kinds,
                    }
                )
    return evidence


async def browsing_evidence(db, user, dataset_ids):
    """Inspect only three recent result items per already-authorized dataset."""
    queries = []
    for dataset_id in dataset_ids:
        query = (
            select(WSISlide.dataset_id, AIResult.task_id, AIResult.wsi_id)
            .join(WSISlide, WSISlide.wsi_id == AIResult.wsi_id)
            .where(WSISlide.dataset_id == dataset_id, AIResult.task_id.isnot(None))
        )
        if not user.is_admin():
            from backend.services.result_access import owned_result_clause
            query = query.where(owned_result_clause(user))
        queries.append(
            query.order_by(AIResult.created_at.desc(), AIResult.id.desc()).limit(3)
        )
    if not queries:
        return {}
    rows = (await db.execute(union_all(*queries))).all()
    return await asyncio.to_thread(_artifact_evidence, rows)
