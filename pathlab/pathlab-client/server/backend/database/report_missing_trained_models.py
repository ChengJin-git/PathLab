"""Read-only audit script for completed training tasks missing trained_models rows."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.common.config import Config
from backend.database import async_session
from backend.database.models import AIResult, TrainingTask, TrainedModel


def _artifact_counts(task_id: str, training_root: Path, ai_results_root: Path) -> dict:
    ckpt_dir = training_root / task_id / "checkpoints"
    return {
        "best_model_exists": (ckpt_dir / "best_model.pth").exists(),
        "config_exists": (ckpt_dir / "config.json").exists(),
        "metrics_exists": (ckpt_dir / "metrics.json").exists(),
        "result_files": len(list(ai_results_root.glob(f"*/train_{task_id}_result.json"))),
        "attention_files": len(list(ai_results_root.glob(f"*/train_{task_id}*_attention.npy"))),
        "cam_files": len(list(ai_results_root.glob(f"*/train_{task_id}*_cam.npy"))),
        "mask_files": len(list(ai_results_root.glob(f"*/train_{task_id}*_pred_mask.npy"))),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Report completed tasks missing trained_models rows")
    parser.add_argument("--task-id", help="Only inspect a specific task")
    parser.add_argument("--only-suspect", action="store_true", help="Only output tasks that look recoverable")
    parser.add_argument("--json", help="Write JSON output to this path")
    args = parser.parse_args()

    training_root = Config.get_uploads_dir() / "training"
    ai_results_root = Config.get_uploads_dir() / "ai_results"

    async with async_session() as db:
        stmt = (
            select(TrainingTask)
            .options(selectinload(TrainingTask.data_group))
            .where(TrainingTask.status == "completed")
        )
        if args.task_id:
            stmt = stmt.where(TrainingTask.task_id == args.task_id)
        tasks = (await db.execute(stmt)).scalars().all()
        existing_task_ids = set((await db.execute(select(TrainedModel.task_id))).scalars().all())
        ai_result_task_ids = (await db.execute(select(AIResult.task_id))).scalars().all()

    ai_result_counts = defaultdict(int)
    for task_id in ai_result_task_ids:
        if task_id:
            ai_result_counts[task_id] += 1

    rows = []
    for task in tasks:
        if task.task_id in existing_task_ids:
            continue
        counts = _artifact_counts(task.task_id, training_root, ai_results_root)
        has_fs_evidence = any(counts[key] > 0 for key in ("result_files", "attention_files", "cam_files", "mask_files"))
        suspect = counts["best_model_exists"] and ai_result_counts.get(task.task_id, 0) > 0 and has_fs_evidence
        dg = task.data_group
        row = {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "user_id": task.user_id,
            "task_type": dg.task_type if dg else None,
            "data_type": dg.data_type if dg else None,
            "ai_result_rows": ai_result_counts.get(task.task_id, 0),
            "suspect_missing_model": suspect,
            **counts,
        }
        if args.only_suspect and not suspect:
            continue
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    if args.json:
        out = Path(args.json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[json] wrote {out}")

    print(f"done: reported={len(rows)} only_suspect={args.only_suspect}")


if __name__ == "__main__":
    asyncio.run(main())

