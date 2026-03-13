"""One-off script to backfill missing trained_models rows from historical training tasks."""
from __future__ import annotations
import argparse, asyncio, json, sys, uuid
from collections import defaultdict
from pathlib import Path
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.common.config import Config
from backend.database import async_session
from backend.database.models import AIResult, TrainingTask, TrainedModel
from backend.database.utils.json_utils import sanitize_for_json

def _load_json(path: Path):
    if not path.exists() or not path.is_file(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return None

def _infer_model_identity(task: TrainingTask) -> tuple[str, str, str]:
    model_cfg = task.model_config or {}
    task_type = task.data_group.task_type if task.data_group else None
    if task_type == "patch_segmentation":
        arch, backbone = str(model_cfg.get("architecture") or "unet"), str(model_cfg.get("backbone") or "resnet50")
        return f"{arch}+{backbone}", backbone, arch
    if task_type == "survival":
        fe, ag = str(model_cfg.get("feature_extractor") or "resnet50"), str(model_cfg.get("aggregator") or "abmil")
        return f"{fe}+{ag}_survival", fe, ag
    if task.data_group and task.data_group.data_type == "patch":
        fe = str(model_cfg.get("feature_extractor") or "resnet50")
        clf = str(model_cfg.get("classifier") or model_cfg.get("aggregator") or "linear_probe")
        return f"{fe}+{clf}", fe, clf
    fe, ag = str(model_cfg.get("feature_extractor") or "resnet50"), str(model_cfg.get("aggregator") or "abmil")
    return f"{fe}+{ag}", fe, ag

def _artifact_status(task_id: str, training_root: Path, ai_results_root: Path, strict: bool, ultra_strict: bool, ai_result_count: int) -> dict:
    ckpt = training_root / task_id / "checkpoints"
    model_path, config_path, metrics_path = ckpt / "best_model.pth", ckpt / "config.json", ckpt / "metrics.json"
    result_files = list(ai_results_root.glob(f"*/train_{task_id}_result.json"))
    attention_files = list(ai_results_root.glob(f"*/train_{task_id}*_attention.npy"))
    cam_files = list(ai_results_root.glob(f"*/train_{task_id}*_cam.npy"))
    mask_files = list(ai_results_root.glob(f"*/train_{task_id}*_pred_mask.npy"))
    has_fs_evidence = bool(result_files or attention_files or cam_files or mask_files)
    if ultra_strict and ai_result_count <= 0:
        return {"eligible": False, "reason": "no_ai_result_rows"}
    if (strict or ultra_strict) and not has_fs_evidence:
        return {"eligible": False, "reason": "no_ai_result_artifacts"}
    if not model_path.exists():
        return {"eligible": False, "reason": "missing_best_model"}
    return {
        "eligible": True, "model_path": model_path, "config_path": config_path, "metrics_path": metrics_path,
        "result_files": result_files, "attention_files": attention_files, "cam_files": cam_files, "mask_files": mask_files,
    }

def _build_model_row(task: TrainingTask, artifact: dict) -> dict:
    metrics_payload = _load_json(artifact["metrics_path"]) or {}
    history = metrics_payload.get("history") if isinstance(metrics_payload, dict) else {}
    train_loss = history.get("train_loss") if isinstance(history, dict) else None
    val_metrics = metrics_payload.get("best_val_metrics") or metrics_payload.get("val_metrics") if isinstance(metrics_payload, dict) else None
    model_name, feature_extractor, aggregator = _infer_model_identity(task)
    created_at = task.finished_at or task.updated_at or task.created_at
    return {
        "model_id": f"legacy_{task.task_id}_{uuid.uuid4().hex[:8]}", "task_id": task.task_id, "user_id": task.user_id,
        "model_name": model_name, "model_path": str(artifact["model_path"]), "config_path": str(artifact["config_path"]),
        "classes": task.classes or [], "feature_extractor": feature_extractor, "aggregator": aggregator,
        "train_metrics": sanitize_for_json({"loss": train_loss}) if train_loss is not None else {},
        "val_metrics": sanitize_for_json(val_metrics) if val_metrics is not None else None,
        "is_default": False, "is_active": True, "created_at": created_at,
    }

def _audit_line(task: TrainingTask, artifact: dict, ai_result_count: int) -> dict:
    dg = task.data_group
    return {
        "task_id": task.task_id, "task_name": task.task_name, "user_id": task.user_id, "status": task.status,
        "task_type": dg.task_type if dg else None, "data_type": dg.data_type if dg else None,
        "has_db_model": False, "ai_result_rows": ai_result_count,
        "result_files": len(artifact.get("result_files", [])), "attention_files": len(artifact.get("attention_files", [])),
        "cam_files": len(artifact.get("cam_files", [])), "mask_files": len(artifact.get("mask_files", [])),
        "model_path": str(artifact.get("model_path")) if artifact.get("model_path") else None,
        "reason": artifact.get("reason", "candidate"),
    }

async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill missing trained_models rows from training_tasks")
    p.add_argument("--task-id", help="Only process a specific training task")
    p.add_argument("--apply", action="store_true", help="Actually write to DB (default dry-run)")
    p.add_argument("--strict", action="store_true", help="Require file-system AI result/heatmap artifacts in addition to best_model.pth")
    p.add_argument("--ultra-strict", action="store_true", help="Require both ai_results DB rows and file-system AI artifacts, plus best_model.pth")
    p.add_argument("--audit-json", help="Write audit report JSON to this path")
    args = p.parse_args()
    if args.ultra_strict:
        args.strict = True
    training_root, ai_results_root = Config.get_uploads_dir() / "training", Config.get_uploads_dir() / "ai_results"
    async with async_session() as db:
        stmt = select(TrainingTask).options(selectinload(TrainingTask.data_group)).where(TrainingTask.status == "completed")
        if args.task_id: stmt = stmt.where(TrainingTask.task_id == args.task_id)
        tasks = (await db.execute(stmt)).scalars().all()
        existing_task_ids = set((await db.execute(select(TrainedModel.task_id))).scalars().all())
        ai_results = (await db.execute(select(AIResult.task_id))).scalars().all()
        ai_result_counts = defaultdict(int)
        for task_id in ai_results:
            if task_id: ai_result_counts[task_id] += 1
        inserted = skipped_existing = skipped_ineligible = 0
        audit = []
        for task in tasks:
            if task.task_id in existing_task_ids:
                skipped_existing += 1
                print(f"[skip-existing] {task.task_id}")
                continue
            ai_result_count = ai_result_counts.get(task.task_id, 0)
            artifact = _artifact_status(task.task_id, training_root, ai_results_root, args.strict, args.ultra_strict, ai_result_count)
            audit_item = _audit_line(task, artifact, ai_result_count)
            audit.append(audit_item)
            if not artifact["eligible"]:
                skipped_ineligible += 1
                print(f"[skip-{artifact['reason']}] {task.task_id}")
                continue
            model_row = _build_model_row(task, artifact)
            print(f"[candidate] {task.task_id} -> {model_row['model_id']} | ai_results={audit_item['ai_result_rows']} result={audit_item['result_files']} attention={audit_item['attention_files']} cam={audit_item['cam_files']} mask={audit_item['mask_files']}")
            if args.apply:
                db.add(TrainedModel(**model_row))
                existing_task_ids.add(task.task_id)
                inserted += 1
        if args.apply: await db.commit()
        else: await db.rollback()
    if args.audit_json:
        out = Path(args.audit_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[audit] wrote {out}")
    mode = "apply" if args.apply else "dry-run"
    flavor = "ultra-strict" if args.ultra_strict else ("strict" if args.strict else "normal")
    print(f"done ({mode}, {flavor}): inserted={inserted} skipped_existing={skipped_existing} skipped_ineligible={skipped_ineligible} audited={len(audit)}")

if __name__ == "__main__":
    asyncio.run(main())

