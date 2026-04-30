from pathlib import Path


FORBIDDEN_PATTERNS = [
    'uploads_dir / "ai_results"',
    'uploads_root / "ai_results"',
    'self.uploads_root / "ai_results"',
    'Config.get_uploads_dir() / "ai_results"',
    '_uploads_dir() / "ai_results"',
    '"ai_results" / wsi_id',
    'glob("*_attention.npy")',
    'glob("*_cam.npy")',
    'glob("*_pred_mask.npy")',
    'f"train_{task_id}_result.json"',
    'f"train_{task_id}_attention.npy"',
    'f"train_{task_id}_attention_raw.npy"',
    'f"train_{task_id}_cam.npy"',
    'f"train_{task_id}_pred_mask.npy"',
]

ALLOWED_FILES = {
    Path("backend/ai/ai_result_migration.py"),
    Path("backend/ai/result_store.py"),
    Path("backend/ai/routes/inference.py"),
    Path("backend/ai/tasks/wsi_classification/trainer.py"),
    Path("backend/ai/tasks/wsi_survival/trainer.py"),
    Path("backend/ai/tasks/patch_classification/trainer.py"),
    Path("backend/common/config.py"),
    Path("backend/storage/manager.py"),
    Path("backend/storage/orphan_mixin.py"),
    Path("gateway/routes/external_validation_analysis.py"),
    Path("gateway/routes/inference_external_validation.py"),
    Path("gateway/routes/results.py"),
}


def test_production_train_ai_result_apis_do_not_use_legacy_paths():
    server_root = Path(__file__).resolve().parents[1]
    checked_roots = [server_root / "backend", server_root / "gateway"]
    offenders: list[str] = []

    for root in checked_roots:
        for path in root.rglob("*.py"):
            rel_path = path.relative_to(server_root)
            if rel_path in ALLOWED_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in text:
                    offenders.append(f"{rel_path}: {pattern}")

    assert offenders == []
