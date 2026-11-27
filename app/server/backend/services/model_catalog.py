"""Model catalog presentation: preserve metric split names and inference readiness."""

from __future__ import annotations

import math
from pathlib import Path


def metric_groups(metrics: dict | None) -> list[dict]:
    flattened = {}

    def visit(value, prefix=""):
        for key, item in (value or {}).items():
            name = f"{prefix}.{key}" if prefix else key
            if isinstance(item, dict):
                visit(item, name)
            elif (
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and math.isfinite(item)
            ):
                flattened[name] = item

    visit(metrics)
    groups = {}
    for key, value in flattened.items():
        # Keep OOF, validation, holdout, patient and slide metrics distinct.
        split, _, name = key.rpartition(".")
        if not split:
            name = key
            for prefix in [
                "train_patient",
                "val_patient",
                "test_patient",
                "train_slide",
                "val_slide",
                "test_slide",
                "train",
                "val",
                "test",
                "oof",
            ]:
                if key.startswith(prefix + "_"):
                    split, name = prefix, key[len(prefix) + 1 :]
                    break
        if name not in {
            "auc",
            "auroc",
            "macro_auc",
            "accuracy",
            "balanced_accuracy",
            "f1",
            "c_index",
            "dice",
            "iou",
            "miou",
            "loss",
            "log_loss",
        }:
            continue
        groups.setdefault(split or "validation", {})[name] = value
    return [
        {"split": name, "metrics": values}
        for name, values in sorted(
            groups.items(),
            key=lambda pair: (
                0
                if pair[0].startswith("oof")
                else 1
                if pair[0].startswith(("val", "validation"))
                else 2
                if pair[0].startswith(("test", "holdout"))
                else 3,
                pair[0],
            ),
        )
    ]


def model_capability(model, task=None) -> dict:
    metadata = (getattr(task, "model_config", None) or {}) if task else {}
    research = metadata.get("source") == "autoresearch"
    # Research artifacts are not automatically native predictor checkpoints.
    # Only a positively validated native contract can opt into normal inference.
    ready = not research or metadata.get("inference_contract") in {'pathlab-native-v1', 'pathlab-predictor-v1'}
    return {
        "source": "autoresearch" if research else "training",
        "research_session_id": metadata.get("session_id") if research else None,
        "inference_ready": ready,
        "inference_reason": None
        if ready
        else (
            "unsupported_format"
            if Path(model.model_path).suffix.lower() not in {".pt", ".pth"}
            else "unverified_contract"
        ),
        "metric_groups": metric_groups(model.val_metrics),
    }


def validate_research_checkpoint(
    model_path: Path, config_path: Path | None, aggregator: str, feature_extractor: str
) -> dict | None:
    """Validate the actual native WSI predictor structure, not just its extension.

    Custom pickle/joblib objects remain research artifacts. weights_only refuses
    their code; only the platform's own registered aggregator class is constructed.
    """
    if (
        config_path is None
        or model_path.suffix not in {".pt", ".pth"}
        or model_path.stat().st_size > 256 * 1024**2
    ):
        return None
    try:
        import json

        import torch

        from backend.ai.aggregators import get_aggregator

        config = json.loads(config_path.read_text())
        if (
            config.get("model") != aggregator
            or config.get("feature_extractor") != feature_extractor
            or config.get("split_type") == "kfold"
        ):
            return None
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
        if not isinstance(checkpoint, dict) or not isinstance(
            checkpoint.get("state_dict"), dict
        ):
            return None
        dimension, count = checkpoint.get("in_dim"), checkpoint.get("num_classes")
        classes = config.get("classes")
        if (
            not isinstance(dimension, int)
            or not 1 <= dimension <= 8192
            or not isinstance(count, int)
            or not 2 <= count <= 1024
        ):
            return None
        if (
            not isinstance(classes, list)
            or len(classes) != count
            or any(not isinstance(label, str) for label in classes)
        ):
            return None
        network = get_aggregator(aggregator, in_dim=dimension, num_classes=count)
        network.load_state_dict(checkpoint["state_dict"], strict=True)
        return config
    except Exception:  # noqa: BLE001 - arbitrary artifact formats fail closed at this validation boundary
        return None
