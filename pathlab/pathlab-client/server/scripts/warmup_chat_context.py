import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import select

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from backend.auth.models import User
from backend.common.chat_context_cache import set_cached_context_kwargs
from backend.database import async_session
from backend.database.repositories import (
    AITaskRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    WSIRepository,
)


async def _build_for_user(user_id: str) -> dict:
    async with async_session() as db:
        stats = await WSIRepository.get_chat_context_stats(
            db, user_id=user_id, elevated_dataset_ids=None
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

        if stats.get("datasets"):
            datasets_list = "\n".join(
                [
                    f"  - {d.get('dataset_name', 'unknown')} (dataset_id={d.get('dataset_id', 'unknown')}): {d.get('file_count', 0)} files, type={d.get('data_type', 'unknown')}"
                    for d in stats["datasets"]
                ]
            )
        else:
            datasets_list = "  None"

        model_summaries = []
        for m in trained_models:
            model_summaries.append(
                {
                    "id": m.model_id,
                    "task_type": "unknown",
                    "data_type": "unknown",
                    "classes": [c.lower() for c in (m.classes or [])],
                    "dataset_names": [],
                    "dataset_sources": [],
                    "task_name": "",
                    "line": f"  - {m.model_name} (id={m.model_id}, trained_on_task={m.task_id})",
                }
            )

        recent_model_summaries = model_summaries[:20]
        if recent_model_summaries:
            models_list = "\n".join(
                ["  CANDIDATE MODELS:"]
                + [summary["line"] for summary in recent_model_summaries]
            )
            models_count = trained_models_total
        else:
            models_list = "  None - user needs to train a model first"
            models_count = 0

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


async def main() -> None:
    start = time.monotonic()
    async with async_session() as db:
        result = await db.execute(select(User.id))
        user_ids = [str(row[0]) for row in result.all()]

    total = len(user_ids)
    warmed = 0
    failed = 0

    for uid in user_ids:
        try:
            kwargs = await _build_for_user(uid)
            await set_cached_context_kwargs(uid, kwargs)
            warmed += 1
        except Exception as exc:
            failed += 1
            print(f"[warmup] failed user={uid}: {exc}")

    elapsed = time.monotonic() - start
    print(
        f"[warmup] done total={total} warmed={warmed} failed={failed} elapsed={elapsed:.2f}s"
    )


if __name__ == "__main__":
    asyncio.run(main())
