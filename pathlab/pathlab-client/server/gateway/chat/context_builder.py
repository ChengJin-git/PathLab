"""
chat_context_builder.py
=======================
Aggregates per-user stats from multiple Repositories into the kwargs dict
consumed by chat_context_cache.set_cached_context_kwargs().

Extracted from gateway/main.py to keep gateway startup logic focused on
lifecycle management only.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import async_session
from backend.database.models import TrainingTask
from backend.database.repositories import (
    AITaskRepository,
    DatasetGrantRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    WSIRepository,
)

logger = logging.getLogger(__name__)


async def build_chat_context_for_user(user_id: str | None) -> dict[str, Any]:
    """
    Build context kwargs for a single user, or admin global scope when user_id is None.

    Returns the dict passed to set_cached_context_kwargs() / set_cached_context_kwargs_admin().
    """
    async with async_session() as db:
        elevated_dataset_ids = None
        if user_id is not None:
            elevated_dataset_ids = (
                await DatasetGrantRepository.list_read_dataset_ids_for_user(db, user_id)
            )
        stats = await WSIRepository.get_chat_context_stats(
            db, user_id=user_id, elevated_dataset_ids=elevated_dataset_ids or None
        )
        trained_models = await TrainedModelRepository.get_all(
            db, limit=200, offset=0, user_id=user_id
        )
        trained_models_total = await TrainedModelRepository.count(db, user_id=user_id)
        training_tasks = await TrainingTaskRepository.get_all(
            db, limit=10, offset=0, user_id=user_id
        )
        training_tasks_stats = await TrainingTaskRepository.get_status_counts(
            db, user_id=user_id
        )
        inference_tasks = await AITaskRepository.get_recent(
            db, limit=10, user_id=user_id
        )
        inference_tasks_stats = await AITaskRepository.get_status_counts(
            db, user_id=user_id
        )

    wsi_count = stats.get("total_count", 0)
    data_type_dist = stats.get("data_types", {})
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val}"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val}"
    else:
        data_types_info = "None"

    own_public_datasets_count = 0
    own_private_datasets_count = 0
    elevated_datasets_count = 0
    other_public_datasets_count = 0
    datasets_details = []
    for d in stats.get("datasets") or []:
        access_type = d.get("access_type", "own")
        name = d.get("dataset_name", "unknown")
        did = d.get("dataset_id", "unknown")
        fc = d.get("file_count", 0)
        dt = d.get("data_type", "unknown")
        if access_type == "elevated":
            elevated_datasets_count += 1
            marker = " [ELEVATED ACCESS - temporary permission]"
        elif access_type == "public":
            other_public_datasets_count += 1
            marker = " [PUBLIC ACCESS - shared by other user]"
        elif access_type == "other_user":
            marker = " [OTHER USER'S DATA - admin view]"
        else:
            if d.get("is_public"):
                own_public_datasets_count += 1
            else:
                own_private_datasets_count += 1
            marker = ""
        _d_source = d.get("source_organ") or "unknown"
        _d_task_type = d.get("group_task_type")
        task_type_suffix = f", task_type={_d_task_type}" if _d_task_type else ""
        labels_suffix = ""
        _d_labels = d.get("labels") or {}
        if _d_labels:
            _label_parts = [f"{lbl}:{cnt}" for lbl, cnt in sorted(_d_labels.items())]
            labels_suffix = f", labels={{{', '.join(_label_parts)}}}"
        survival_suffix = ""
        _d_survival = d.get("survival_count", 0)
        if _d_survival:
            _d_event = d.get("event_status") or {}
            _ev = _d_event.get("event", 0)
            _cens = _d_event.get("censored", 0)
            survival_suffix = (
                f", survival_data={_d_survival} (event={_ev}, censored={_cens})"
            )
        split_suffix = ""
        if d.get("has_predefined_splits"):
            sc = d.get("predefined_split_counts", {})
            unit = "cases" if d.get("aggregation_level") == "case" else "slides"
            split_suffix = (
                f", predefined_split_distribution({unit}):"
                f" train={sc.get('train', 0)}, val={sc.get('val', 0)}, test={sc.get('test', 0)}"
            )
        datasets_details.append(
            f"  - {name} (dataset_id={did}): {fc} files, type={dt}, source={_d_source}{task_type_suffix}{labels_suffix}{survival_suffix}{marker}{split_suffix}"
        )
    if datasets_details:
        datasets_list = "\n".join(datasets_details)
    else:
        datasets_list = "  None"

    _task_ids = list({str(m.task_id) for m in trained_models if m.task_id})
    _task_meta: dict[str, tuple[str, str, str]] = {}
    if _task_ids:
        async with async_session() as _db:
            _stmt = (
                select(TrainingTask)
                .options(selectinload(TrainingTask.data_group))
                .where(TrainingTask.task_id.in_(_task_ids))
            )
            _result = await _db.execute(_stmt)
            for _task in _result.scalars().all():
                _dg = _task.data_group
                _task_meta[str(_task.task_id)] = (
                    str((_dg.task_type if _dg else None) or "unknown"),
                    str((_dg.data_type if _dg else None) or "unknown"),
                    str(_task.task_name or ""),
                )

    model_summaries = []
    for m in trained_models:
        _tt, _dt, _tn = _task_meta.get(
            str(m.task_id) if m.task_id else "", ("unknown", "unknown", "")
        )
        model_summaries.append(
            {
                "id": m.model_id,
                "task_type": _tt,
                "data_type": _dt,
                "classes": [c.lower() for c in (m.classes or [])],
                "dataset_names": [],
                "dataset_sources": [],
                "task_name": _tn.lower(),
                "line": f"  - {m.model_name} (id={m.model_id}, task_type={_tt}, data_type={_dt}, trained_on_task={m.task_id}, task_name={_tn or 'unknown'}, feature_extractor={m.feature_extractor or 'unknown'}, aggregator={m.aggregator or 'unknown'}, classes={[c.lower() for c in (m.classes or [])]})",
                # embedding field populated below (after batch encode)
                "embedding": None,
            }
        )

    # Batch-encode model descriptions for semantic retrieval at query time.
    # We encode the full `line` string so the embedding captures model name,
    # task_type, data_type and task_id — all the fields a user might ask about.
    if model_summaries:
        try:
            from gateway.routes.chat_pdf_vectorstore import _embed_texts

            _lines = [s["line"] for s in model_summaries]
            _vecs = _embed_texts(_lines)  # shape: (N, 384)
            for _i, _s in enumerate(model_summaries):
                _s["embedding"] = _vecs[_i].tolist()
        except Exception as _emb_exc:
            logger.warning(f"[ChatCtxCache] model embedding failed: {_emb_exc}")

    training_tasks_total = training_tasks_stats.get("total", 0)
    training_tasks_completed = training_tasks_stats.get("completed", 0)
    training_tasks_running = training_tasks_stats.get("running", 0)
    training_tasks_failed = training_tasks_stats.get("failed", 0)

    if training_tasks:
        training_tasks_list = "\n".join(
            [
                f"  - [{str(t.status).upper()}] {t.task_name} (id={t.task_id})"
                for t in training_tasks
            ]
        )
    else:
        training_tasks_list = "  None - user has not created any training tasks yet"

    inference_tasks_total = inference_tasks_stats.get("total", 0)
    inference_tasks_completed = inference_tasks_stats.get("completed", 0)
    inference_tasks_running = inference_tasks_stats.get("running", 0)

    if inference_tasks:
        inference_tasks_list = "\n".join(
            [
                f"  - [{str(t.status).upper()}] {t.task_type} on {t.wsi_id} (id={t.task_id})"
                for t in inference_tasks
            ]
        )
    else:
        inference_tasks_list = "  None - user has not run any inference tasks yet"

    return {
        "wsi_count": wsi_count,
        "data_types_info": data_types_info,
        "datasets_list": datasets_list,
        "own_public_datasets_count": own_public_datasets_count,
        "own_private_datasets_count": own_private_datasets_count,
        "elevated_datasets_count": elevated_datasets_count,
        "other_public_datasets_count": other_public_datasets_count,
        "trained_models_total": trained_models_total,
        "model_summaries": model_summaries,
        "training_tasks_total": training_tasks_total,
        "training_tasks_completed": training_tasks_completed,
        "training_tasks_running": training_tasks_running,
        "training_tasks_failed": training_tasks_failed,
        "training_tasks_list": training_tasks_list,
        "inference_tasks_total": inference_tasks_total,
        "inference_tasks_completed": inference_tasks_completed,
        "inference_tasks_running": inference_tasks_running,
        "inference_tasks_list": inference_tasks_list,
    }
