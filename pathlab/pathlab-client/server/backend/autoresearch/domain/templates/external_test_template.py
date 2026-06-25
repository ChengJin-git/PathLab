"""
AutoResearch External Test Script
==================================

Evaluate a fixed model artifact on an external dataset. This script is
separate from ``train.py`` so the coding agent can adapt model loading or
dataset adapters without changing training code.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score


OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
MODEL_PATH = Path(os.getenv("AUTORESEARCH_MODEL_PATH", ""))
MODEL_METADATA_PATH = Path(os.getenv("AUTORESEARCH_MODEL_METADATA_PATH", ""))
EXTERNAL_TASK_TYPE = os.getenv("AUTORESEARCH_EXTERNAL_TASK_TYPE", "")
EXTERNAL_FEATURES_DIR = Path(os.getenv("EXTERNAL_FEATURES_DIR", ""))
EXTERNAL_IMAGES_DIR = Path(os.getenv("EXTERNAL_IMAGES_DIR", ""))
EXTERNAL_MASKS_DIR = Path(os.getenv("EXTERNAL_MASKS_DIR", ""))
EXTERNAL_PREDICTIONS_DIR = Path(os.getenv("EXTERNAL_PREDICTIONS_DIR", ""))
EXTERNAL_SPLITS_FILE = Path(os.getenv("EXTERNAL_SPLITS_FILE", ""))
EXTERNAL_LABELS_FILE = Path(os.getenv("EXTERNAL_LABELS_FILE", ""))
MAX_EXTERNAL_SAMPLES = int(os.getenv("PATHLAB_MAX_EXTERNAL_SAMPLES", "0") or "0")
QUICK_CHECK = os.getenv("PATHLAB_QUICK_CHECK", "").lower() in {"1", "true", "yes"}


def _path_is_configured(path: Path) -> bool:
    return str(path).strip() not in {"", "."}


def _fail_if_missing(path: Path, label: str) -> None:
    if not _path_is_configured(path) or not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def normalize_external_task_type(value: str | None) -> str:
    """Normalize external task aliases to the execution branch names."""
    task = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": "mil_classification",
        "classification": "mil_classification",
        "mil": "mil_classification",
        "mil_classification": "mil_classification",
        "wsi_classification": "mil_classification",
        "slide_classification": "mil_classification",
        "patch": "patch_classification",
        "patch_classification": "patch_classification",
        "image_classification": "patch_classification",
        "survival": "survival",
        "survival_analysis": "survival",
        "wsi_survival": "survival",
        "patch_segmentation": "segmentation",
        "segmentation": "segmentation",
        "semantic_segmentation": "segmentation",
    }
    if task not in aliases:
        raise ValueError(
            f"Unsupported AUTORESEARCH_EXTERNAL_TASK_TYPE={value!r}. "
            "Expected mil_classification, patch_classification, survival, or segmentation."
        )
    return aliases[task]


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _fail_if_missing(path, label)
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object.")
    return data


def _read_csv_labels(path: Path) -> dict[str, Any]:
    _fail_if_missing(path, "external labels file")
    labels: dict[str, Any] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sample_id = ""
            for key in ("sample_id", "slide_id", "slide", "filename", "file_name", "wsi", "wsi_id"):
                value = str(row.get(key) or "").strip()
                if value:
                    sample_id = Path(value).stem if Path(value).suffix else value
                    break
            label_value = ""
            for key in ("label", "class", "target", "y", "diagnosis"):
                value = str(row.get(key) or "").strip()
                if value:
                    label_value = value
                    break
            if sample_id and label_value:
                labels[sample_id] = label_value
    if not labels:
        raise ValueError(f"external labels CSV did not contain usable sample ids and labels: {path}")
    return {"external": list(labels), "labels": labels}


def _read_structured_labels(path: Path, label: str) -> dict[str, Any]:
    _fail_if_missing(path, label)
    if path.suffix.lower() == ".csv":
        return _read_csv_labels(path)
    return _read_json(path, label)


def _merge_external_labels(data: dict[str, Any]) -> dict[str, Any]:
    if not _path_is_configured(EXTERNAL_LABELS_FILE):
        return data
    labels_data = _read_structured_labels(EXTERNAL_LABELS_FILE, "external labels file")
    merged = dict(data)
    for key in ("external", "sample_ids", "labels", "survival_times", "times", "event_status", "events"):
        if key in labels_data and key not in merged:
            merged[key] = labels_data[key]
    return merged


def _split_sample_ids(data: dict[str, Any]) -> list[str]:
    for key in ("external", "test", "val", "validation", "samples", "sample_ids"):
        value = data.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    for key in ("labels", "survival_times", "times", "event_status", "events"):
        value = data.get(key)
        if isinstance(value, dict) and value:
            return [str(item) for item in value.keys()]
    return []


def load_splits(path: Path, *, require_labels: bool = True) -> dict[str, Any]:
    if _path_is_configured(path) and path.exists():
        data = _merge_external_labels(_read_json(path, "external splits file"))
    elif _path_is_configured(EXTERNAL_LABELS_FILE):
        data = _read_structured_labels(EXTERNAL_LABELS_FILE, "external labels file")
    else:
        data = _merge_external_labels(_read_json(path, "external splits file"))
    labels = data.get("labels") or {}
    if require_labels and (not isinstance(labels, dict) or not labels):
        raise ValueError("External splits file must include a non-empty labels object.")
    sample_ids = _split_sample_ids(data)
    if not sample_ids:
        raise ValueError("External splits file did not provide sample ids.")
    if QUICK_CHECK and MAX_EXTERNAL_SAMPLES > 0:
        sample_ids = sample_ids[:MAX_EXTERNAL_SAMPLES]
    return {"sample_ids": sample_ids, "labels": labels, "raw": data}


def _feature_candidates(sample_id: str) -> list[Path]:
    sample_path = Path(sample_id)
    candidates: list[Path] = []
    if sample_path.suffix in {".pt", ".pth"}:
        candidates.append(sample_path if sample_path.is_absolute() else EXTERNAL_FEATURES_DIR / sample_path)
    for suffix in (".pt", ".pth"):
        candidates.append(EXTERNAL_FEATURES_DIR / f"{sample_id}{suffix}")
        candidates.append(EXTERNAL_FEATURES_DIR / sample_id / f"features{suffix}")
    return candidates


def load_feature(sample_id: str) -> torch.Tensor:
    for path in _feature_candidates(sample_id):
        if path.exists():
            tensor = torch.load(path, map_location="cpu", weights_only=True)
            if isinstance(tensor, dict):
                for key in ("features", "feats", "embedding", "x"):
                    if key in tensor:
                        tensor = tensor[key]
                        break
                else:
                    tensor = next(iter(tensor.values()))
            if not torch.is_tensor(tensor):
                raise TypeError(f"Feature file for {sample_id} did not contain a tensor.")
            return tensor.float()
    raise FileNotFoundError(sample_id)


def _image_candidates(sample_id: str) -> list[Path]:
    sample_path = Path(sample_id)
    candidates: list[Path] = []
    if sample_path.suffix:
        candidates.append(sample_path if sample_path.is_absolute() else EXTERNAL_IMAGES_DIR / sample_path)
    for suffix in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"):
        candidates.append(EXTERNAL_IMAGES_DIR / f"{sample_id}{suffix}")
    return candidates


def load_patch_image_feature(sample_id: str, *, extractor, transform, device: str) -> torch.Tensor:
    for path in _image_candidates(sample_id):
        if not path.exists():
            continue
        from PIL import Image

        image = Image.open(path).convert("RGB")
        tensor = transform(image)
        if not torch.is_tensor(tensor):
            raise TypeError("Patch image transform must return a torch.Tensor.")
        if tensor.dim() == 3:
            tensor = tensor.unsqueeze(0)
        with torch.no_grad():
            features = extractor(tensor.to(device))
        if isinstance(features, (tuple, list)):
            features = features[0]
        if not torch.is_tensor(features):
            raise TypeError(f"Extractor output for {sample_id} was not a tensor.")
        return features.squeeze(0).detach().cpu().flatten().float()
    raise FileNotFoundError(sample_id)


def infer_feature_dim(sample_ids: list[str]) -> int:
    missing: list[str] = []
    for sample_id in sample_ids:
        try:
            return int(load_feature(sample_id).shape[-1])
        except FileNotFoundError:
            missing.append(sample_id)
    raise RuntimeError(f"No external feature tensors found. Missing examples: {missing[:5]}")


def build_patch_feature_extractor(device: str):
    train = load_training_module()
    if hasattr(train, "build_external_feature_extractor"):
        built = train.build_external_feature_extractor()
        if isinstance(built, tuple) and len(built) == 2:
            extractor, transform = built
        else:
            extractor = built
            transform = extractor.get_transforms() if hasattr(extractor, "get_transforms") else None
    else:
        extractor_name = os.getenv("PATHLAB_EXTRACTOR", "") or getattr(train, "DEFAULT_EXTRACTOR", "")
        if hasattr(train, "_resolve_extractor"):
            extractor = train._resolve_extractor(extractor_name)
        elif hasattr(train, "resolve_extractor"):
            extractor = train.resolve_extractor(extractor_name)
        else:
            raise RuntimeError(
                "Patch image external_test requires train.py to expose "
                "_resolve_extractor(), resolve_extractor(), or build_external_feature_extractor()."
            )
        transform = extractor.get_transforms() if hasattr(extractor, "get_transforms") else None
    if transform is None:
        raise RuntimeError("Patch image external_test could not resolve an image transform.")
    if hasattr(extractor, "eval"):
        extractor.eval()
    if hasattr(extractor, "to"):
        extractor.to(device)
    return extractor, transform


def infer_patch_image_feature_dim(sample_ids: list[str], *, extractor, transform, device: str) -> int:
    missing: list[str] = []
    for sample_id in sample_ids:
        try:
            return int(load_patch_image_feature(
                sample_id,
                extractor=extractor,
                transform=transform,
                device=device,
            ).shape[-1])
        except FileNotFoundError:
            missing.append(sample_id)
    raise RuntimeError(f"No external patch images found. Missing examples: {missing[:5]}")


def load_training_module():
    sys.path.insert(0, str(Path.cwd()))
    import train  # type: ignore

    return train


def _call_builder(fn, *, num_classes: int | None = None, feature_dim: int, num_bins: int | None = None):
    attempts: list[dict[str, Any]] = []
    if num_bins is not None:
        attempts.extend([
            {"in_dim": feature_dim, "num_bins": num_bins},
            {"feature_dim": feature_dim, "num_bins": num_bins},
        ])
    if num_classes is not None:
        attempts.extend([
            {"in_dim": feature_dim, "num_classes": num_classes},
            {"in_dim": feature_dim, "n_classes": num_classes},
            {"feature_dim": feature_dim, "num_classes": num_classes},
            {"feature_dim": feature_dim, "n_classes": num_classes},
        ])
    attempts.append({"in_dim": feature_dim})
    attempts.append({"feature_dim": feature_dim})
    for kwargs in attempts:
        try:
            return fn(**kwargs)
        except TypeError:
            continue
    if num_bins is not None:
        return fn(feature_dim, num_bins)
    if num_classes is not None:
        return fn(feature_dim, num_classes)
    return fn(feature_dim)


def build_model(num_classes: int, feature_dim: int):
    train = load_training_module()
    if hasattr(train, "build_mil_model"):
        return _call_builder(train.build_mil_model, num_classes=num_classes, feature_dim=feature_dim)
    if hasattr(train, "MILAggregator"):
        return _call_builder(train.MILAggregator, num_classes=num_classes, feature_dim=feature_dim)
    raise AttributeError(
        "Could not build MIL model from train.py. Expected build_mil_model() or MILAggregator."
    )


def build_patch_classification_model(num_classes: int, feature_dim: int):
    train = load_training_module()
    for name in ("build_patch_classification_model", "build_patch_model", "build_model"):
        if hasattr(train, name):
            return _call_builder(getattr(train, name), num_classes=num_classes, feature_dim=feature_dim)
    if hasattr(train, "LinearHead"):
        return _call_builder(train.LinearHead, num_classes=num_classes, feature_dim=feature_dim)
    raise RuntimeError(
        "Patch external_test refused to use fallback linear head. "
        "Expose build_patch_classification_model(), build_patch_model(), "
        "build_model(), or LinearHead in train.py so the external evaluation "
        "loads the same architecture used during training."
    )


def _load_checkpoint_state(device: str) -> dict[str, Any]:
    _fail_if_missing(MODEL_PATH, "model checkpoint")
    state = torch.load(MODEL_PATH, map_location=device, weights_only=True)
    if isinstance(state, dict):
        for key in ("state_dict", "model_state_dict", "model"):
            if key in state and isinstance(state[key], dict):
                state = state[key]
                break
    if not isinstance(state, dict):
        raise TypeError(f"Model checkpoint did not contain a state dict: {MODEL_PATH}")
    if all(isinstance(key, str) and key.startswith("module.") for key in state):
        state = {key.removeprefix("module."): value for key, value in state.items()}
    return state


def _load_model_state(model: nn.Module, state: dict[str, Any]) -> nn.Module:
    model.load_state_dict(state)
    return model


def load_model(num_classes: int, feature_dim: int, device: str):
    state = _load_checkpoint_state(device)
    model = build_model(num_classes=num_classes, feature_dim=feature_dim)
    _load_model_state(model, state)
    model.to(device)
    model.eval()
    return model


def _label_to_int_map(labels: dict[str, Any]) -> tuple[dict[str, int], dict[str, int]]:
    values = list(labels.values())
    if all(isinstance(v, int) for v in values):
        classes = sorted(set(int(v) for v in values))
        return {str(k): int(v) for k, v in labels.items()}, {str(v): int(v) for v in classes}
    class_names = sorted({str(v) for v in values})
    mapping = {name: idx for idx, name in enumerate(class_names)}
    return {str(k): mapping[str(v)] for k, v in labels.items()}, mapping


def _as_logits(output) -> torch.Tensor:
    logits = output[0] if isinstance(output, (tuple, list)) else output
    if logits.dim() == 1:
        logits = logits.unsqueeze(0)
    return logits


def run_inference(model, sample_ids: list[str], labels: dict[str, int], device: str):
    y_true: list[int] = []
    y_pred: list[int] = []
    y_score: list[float] = []
    rows: list[dict[str, Any]] = []
    missing_features: list[str] = []

    with torch.no_grad():
        for sample_id in sample_ids:
            if sample_id not in labels:
                continue
            try:
                features = load_feature(sample_id).to(device)
            except FileNotFoundError:
                missing_features.append(sample_id)
                continue
            logits = _as_logits(model(features))
            probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()[0]
            pred = int(np.argmax(probs))
            label = int(labels[sample_id])
            score = float(probs[1]) if len(probs) > 1 else float(probs[0])
            y_true.append(label)
            y_pred.append(pred)
            y_score.append(score)
            rows.append({
                "sample_id": sample_id,
                "label": label,
                "prediction": pred,
                "score": score,
            })

    return y_true, y_pred, y_score, rows, missing_features


def run_patch_classification_inference(model, sample_ids: list[str], labels: dict[str, int], device: str):
    y_true: list[int] = []
    y_pred: list[int] = []
    y_score: list[float] = []
    rows: list[dict[str, Any]] = []
    missing_features: list[str] = []

    with torch.no_grad():
        for sample_id in sample_ids:
            if sample_id not in labels:
                continue
            try:
                features = load_feature(sample_id).flatten().unsqueeze(0).to(device)
            except FileNotFoundError:
                missing_features.append(sample_id)
                continue
            logits = _as_logits(model(features))
            probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()[0]
            pred = int(np.argmax(probs))
            label = int(labels[sample_id])
            score = float(probs[1]) if len(probs) > 1 else float(probs[0])
            y_true.append(label)
            y_pred.append(pred)
            y_score.append(score)
            rows.append({
                "sample_id": sample_id,
                "label": label,
                "prediction": pred,
                "score": score,
            })

    return y_true, y_pred, y_score, rows, missing_features


def run_patch_image_classification_inference(
    model,
    sample_ids: list[str],
    labels: dict[str, int],
    device: str,
    *,
    extractor,
    transform,
):
    y_true: list[int] = []
    y_pred: list[int] = []
    y_score: list[float] = []
    rows: list[dict[str, Any]] = []
    missing_images: list[str] = []

    with torch.no_grad():
        for sample_id in sample_ids:
            if sample_id not in labels:
                continue
            try:
                features = load_patch_image_feature(
                    sample_id,
                    extractor=extractor,
                    transform=transform,
                    device=device,
                ).unsqueeze(0).to(device)
            except FileNotFoundError:
                missing_images.append(sample_id)
                continue
            logits = _as_logits(model(features))
            probs = torch.softmax(logits, dim=-1).detach().cpu().numpy()[0]
            pred = int(np.argmax(probs))
            label = int(labels[sample_id])
            score = float(probs[1]) if len(probs) > 1 else float(probs[0])
            y_true.append(label)
            y_pred.append(pred)
            y_score.append(score)
            rows.append({
                "sample_id": sample_id,
                "label": label,
                "prediction": pred,
                "score": score,
            })

    return y_true, y_pred, y_score, rows, missing_images


def compute_metrics(y_true: list[int], y_pred: list[int], y_score: list[float]) -> dict[str, Any]:
    if not y_true:
        raise RuntimeError("No external samples were evaluated.")
    average = "binary" if len(set(y_true)) == 2 else "macro"
    auc = None
    if len(set(y_true)) == 2:
        try:
            auc = float(roc_auc_score(y_true, y_score))
        except ValueError:
            auc = None
    return {
        "auc": round(auc, 4) if auc is not None else None,
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "f1": round(float(f1_score(y_true, y_pred, average=average, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, y_pred, average=average, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, average=average, zero_division=0)), 4),
    }


def _survival_maps(raw: dict[str, Any]) -> tuple[dict[str, float], dict[str, int]]:
    times_raw = raw.get("survival_times") or raw.get("times") or raw.get("survival_time")
    events_raw = raw.get("event_status") or raw.get("events") or raw.get("event")
    if not isinstance(times_raw, dict) or not times_raw:
        raise ValueError("External survival splits must include survival_times or times.")
    if not isinstance(events_raw, dict) or not events_raw:
        raise ValueError("External survival splits must include event_status or events.")
    times = {str(k): float(v) for k, v in times_raw.items()}
    events = {str(k): int(v) for k, v in events_raw.items()}
    return times, events


def infer_survival_num_bins_from_state(state: dict[str, Any], default: int = 4) -> int:
    for key in ("fc.3.weight", "fc.2.weight", "survival_head.weight"):
        value = state.get(key)
        if torch.is_tensor(value) and value.ndim == 2:
            return int(value.shape[0])
    for key, value in sorted(state.items()):
        if "fc" in str(key) and str(key).endswith("weight") and torch.is_tensor(value) and value.ndim == 2:
            return int(value.shape[0])
    return default


def build_survival_model(feature_dim: int, num_bins: int):
    train = load_training_module()
    if hasattr(train, "build_survival_model"):
        return _call_builder(train.build_survival_model, feature_dim=feature_dim, num_bins=num_bins)
    if hasattr(train, "SurvivalAggregator"):
        return _call_builder(train.SurvivalAggregator, feature_dim=feature_dim, num_bins=num_bins)
    raise AttributeError(
        "Could not build survival model from train.py. Expected build_survival_model() or SurvivalAggregator."
    )


def compute_survival_metrics_from_scores(
    times: list[float],
    events: list[int],
    risks: list[float],
) -> dict[str, Any]:
    if not risks:
        raise RuntimeError("No external survival samples were evaluated.")
    concordant = 0.0
    comparable = 0
    n = len(risks)
    for i in range(n):
        for j in range(i + 1, n):
            if times[i] == times[j]:
                continue
            if times[i] < times[j] and events[i] == 1:
                shorter, longer = i, j
            elif times[j] < times[i] and events[j] == 1:
                shorter, longer = j, i
            else:
                continue
            comparable += 1
            if risks[shorter] > risks[longer]:
                concordant += 1.0
            elif risks[shorter] == risks[longer]:
                concordant += 0.5
    c_index = concordant / comparable if comparable else 0.5
    return {
        "c_index": round(float(c_index), 4),
        "n_external_evaluated": int(n),
        "comparable_pairs": int(comparable),
    }


def _risk_from_hazards(hazards: torch.Tensor) -> float:
    hazards = hazards.squeeze(0)
    return float(torch.sigmoid(hazards).sum().detach().cpu())


def run_survival_inference(model, sample_ids: list[str], times: dict[str, float], events: dict[str, int], device: str):
    evaluated_times: list[float] = []
    evaluated_events: list[int] = []
    risks: list[float] = []
    rows: list[dict[str, Any]] = []
    missing_features: list[str] = []

    with torch.no_grad():
        for sample_id in sample_ids:
            if sample_id not in times or sample_id not in events:
                continue
            try:
                features = load_feature(sample_id).to(device)
            except FileNotFoundError:
                missing_features.append(sample_id)
                continue
            if features.dim() == 1:
                features = features.unsqueeze(0)
            hazards = _as_logits(model(features))
            risk = _risk_from_hazards(hazards)
            evaluated_times.append(float(times[sample_id]))
            evaluated_events.append(int(events[sample_id]))
            risks.append(risk)
            rows.append({
                "sample_id": sample_id,
                "survival_time": float(times[sample_id]),
                "event_status": int(events[sample_id]),
                "risk_score": risk,
            })
    return evaluated_times, evaluated_events, risks, rows, missing_features


def _array_candidates(root: Path, sample_id: str) -> list[Path]:
    sample_path = Path(sample_id)
    candidates: list[Path] = []
    if sample_path.suffix:
        candidates.append(sample_path if sample_path.is_absolute() else root / sample_path)
    for suffix in (".pt", ".pth", ".npy", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        candidates.append(root / f"{sample_id}{suffix}")
    return candidates


def _load_array_file(path: Path) -> np.ndarray:
    if path.suffix.lower() in {".pt", ".pth"}:
        obj = torch.load(path, map_location="cpu", weights_only=True)
        if isinstance(obj, dict):
            for key in ("mask", "prediction", "pred", "logits", "array"):
                if key in obj:
                    obj = obj[key]
                    break
            else:
                obj = next(iter(obj.values()))
        if torch.is_tensor(obj):
            return obj.detach().cpu().numpy()
        return np.asarray(obj)
    if path.suffix.lower() == ".npy":
        return np.load(path)
    from PIL import Image

    return np.asarray(Image.open(path))


def load_array(root: Path, sample_id: str, label: str) -> np.ndarray:
    for path in _array_candidates(root, sample_id):
        if path.exists():
            return _load_array_file(path)
    raise FileNotFoundError(f"{label}: {sample_id}")


def _binary_mask(array: np.ndarray) -> np.ndarray:
    arr = np.asarray(array)
    if arr.ndim > 2 and arr.shape[0] <= 16:
        arr = np.argmax(arr, axis=0)
    elif arr.ndim > 2:
        arr = np.squeeze(arr)
    if arr.dtype.kind == "f":
        return arr > 0.5
    return arr > 0


def compute_segmentation_pair_metrics(prediction: np.ndarray, target: np.ndarray) -> dict[str, float]:
    pred = _binary_mask(prediction)
    truth = _binary_mask(target)
    intersection = float(np.logical_and(pred, truth).sum())
    pred_sum = float(pred.sum())
    truth_sum = float(truth.sum())
    union = float(np.logical_or(pred, truth).sum())
    dice = 1.0 if pred_sum + truth_sum == 0 else (2.0 * intersection) / (pred_sum + truth_sum)
    iou = 1.0 if union == 0 else intersection / union
    return {"dice": float(dice), "iou": float(iou)}


def compute_segmentation_metrics_for_arrays(
    predictions: list[np.ndarray],
    targets: list[np.ndarray],
) -> dict[str, Any]:
    if not predictions:
        raise RuntimeError("No external segmentation samples were evaluated.")
    pairs = [
        compute_segmentation_pair_metrics(prediction, target)
        for prediction, target in zip(predictions, targets)
    ]
    return {
        "dice": round(float(np.mean([item["dice"] for item in pairs])), 4),
        "iou": round(float(np.mean([item["iou"] for item in pairs])), 4),
        "n_external_evaluated": len(pairs),
    }


def _sample_ids_from_array_dirs() -> list[str]:
    suffixes = {".pt", ".pth", ".npy", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    ids: set[str] = set()
    if _path_is_configured(EXTERNAL_MASKS_DIR) and EXTERNAL_MASKS_DIR.exists():
        ids.update(path.stem for path in EXTERNAL_MASKS_DIR.iterdir() if path.suffix.lower() in suffixes)
    if _path_is_configured(EXTERNAL_PREDICTIONS_DIR) and EXTERNAL_PREDICTIONS_DIR.exists():
        ids.update(path.stem for path in EXTERNAL_PREDICTIONS_DIR.iterdir() if path.suffix.lower() in suffixes)
    sample_ids = sorted(ids)
    if QUICK_CHECK and MAX_EXTERNAL_SAMPLES > 0:
        sample_ids = sample_ids[:MAX_EXTERNAL_SAMPLES]
    return sample_ids


def write_predictions(rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path = OUTPUT_DIR / "predictions.csv"
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else ["sample_id"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_metrics(metrics: dict[str, Any]) -> None:
    (OUTPUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (OUTPUT_DIR / "external_test_report.json").write_text(json.dumps(metrics, indent=2))


def run_external_classification(*, patch_level: bool) -> None:
    splits = load_splits(EXTERNAL_SPLITS_FILE)
    labels, class_mapping = _label_to_int_map(splits["labels"])
    sample_ids = [str(item) for item in splits["sample_ids"]]
    num_classes = max(labels.values()) + 1
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_patch_images = False
    extractor = None
    transform = None

    if patch_level and (
        not _path_is_configured(EXTERNAL_FEATURES_DIR) or not EXTERNAL_FEATURES_DIR.exists()
    ):
        _fail_if_missing(EXTERNAL_IMAGES_DIR, "external images directory")
        extractor, transform = build_patch_feature_extractor(device)
        feature_dim = infer_patch_image_feature_dim(
            sample_ids,
            extractor=extractor,
            transform=transform,
            device=device,
        )
        use_patch_images = True
    else:
        _fail_if_missing(EXTERNAL_FEATURES_DIR, "external features directory")
        feature_dim = infer_feature_dim(sample_ids)

    state = _load_checkpoint_state(device)
    if patch_level:
        model = build_patch_classification_model(num_classes=num_classes, feature_dim=feature_dim)
    else:
        model = build_model(num_classes=num_classes, feature_dim=feature_dim)
    _load_model_state(model, state)
    model.to(device)
    model.eval()

    if use_patch_images:
        y_true, y_pred, y_score, rows, missing_features = run_patch_image_classification_inference(
            model,
            sample_ids,
            labels,
            device,
            extractor=extractor,
            transform=transform,
        )
    else:
        runner = run_patch_classification_inference if patch_level else run_inference
        y_true, y_pred, y_score, rows, missing_features = runner(model, sample_ids, labels, device)
    external_metrics = compute_metrics(y_true, y_pred, y_score)
    coverage = {
        "n_external_total": len(sample_ids),
        "n_external_evaluated": len(y_true),
        "missing_features": 0 if use_patch_images else len(missing_features),
        "missing_feature_examples": [] if use_patch_images else missing_features[:20],
        "missing_images": len(missing_features) if use_patch_images else 0,
        "missing_image_examples": missing_features[:20] if use_patch_images else [],
    }
    metrics = {
        **external_metrics,
        "external": external_metrics,
        "coverage": coverage,
        "class_mapping": class_mapping,
        "quick_check": QUICK_CHECK,
        "external_task_type": "patch_classification" if patch_level else "mil_classification",
    }
    write_metrics(metrics)
    write_predictions(rows)


def run_external_survival() -> None:
    _fail_if_missing(EXTERNAL_FEATURES_DIR, "external features directory")
    splits = load_splits(EXTERNAL_SPLITS_FILE, require_labels=False)
    sample_ids = [str(item) for item in splits["sample_ids"]]
    times, events = _survival_maps(splits["raw"])
    feature_dim = infer_feature_dim(sample_ids)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    state = _load_checkpoint_state(device)
    num_bins = infer_survival_num_bins_from_state(state)
    model = build_survival_model(feature_dim=feature_dim, num_bins=num_bins)
    _load_model_state(model, state)
    model.to(device)
    model.eval()

    evaluated_times, evaluated_events, risks, rows, missing_features = run_survival_inference(
        model, sample_ids, times, events, device
    )
    external_metrics = compute_survival_metrics_from_scores(
        times=evaluated_times,
        events=evaluated_events,
        risks=risks,
    )
    coverage = {
        "n_external_total": len(sample_ids),
        "n_external_evaluated": len(risks),
        "missing_features": len(missing_features),
        "missing_feature_examples": missing_features[:20],
    }
    metrics = {
        "c_index": external_metrics["c_index"],
        "external": external_metrics,
        "coverage": coverage,
        "num_bins": num_bins,
        "quick_check": QUICK_CHECK,
        "external_task_type": "survival",
    }
    write_metrics(metrics)
    write_predictions(rows, ["sample_id", "survival_time", "event_status", "risk_score"])


def run_external_segmentation() -> None:
    _fail_if_missing(EXTERNAL_MASKS_DIR, "external masks directory")
    if not _path_is_configured(EXTERNAL_PREDICTIONS_DIR) or not EXTERNAL_PREDICTIONS_DIR.exists():
        raise RuntimeError(
            "Segmentation external_test currently requires EXTERNAL_PREDICTIONS_DIR "
            "with saved masks/logits. If you need model-driven segmentation inference, "
            "adapt the model_loading and dataset_adapter zones in external_test.py."
        )
    if _path_is_configured(EXTERNAL_SPLITS_FILE) and EXTERNAL_SPLITS_FILE.exists():
        splits = load_splits(EXTERNAL_SPLITS_FILE, require_labels=False)
        sample_ids = [str(item) for item in splits["sample_ids"]]
    else:
        sample_ids = _sample_ids_from_array_dirs()
    if not sample_ids:
        raise RuntimeError("No external segmentation sample ids found.")

    predictions: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for sample_id in sample_ids:
        try:
            pred = load_array(EXTERNAL_PREDICTIONS_DIR, sample_id, "prediction")
            target = load_array(EXTERNAL_MASKS_DIR, sample_id, "mask")
        except FileNotFoundError:
            missing.append(sample_id)
            continue
        pair = compute_segmentation_pair_metrics(pred, target)
        predictions.append(pred)
        targets.append(target)
        rows.append({"sample_id": sample_id, "dice": round(pair["dice"], 4), "iou": round(pair["iou"], 4)})

    external_metrics = compute_segmentation_metrics_for_arrays(predictions, targets)
    coverage = {
        "n_external_total": len(sample_ids),
        "n_external_evaluated": len(predictions),
        "missing_masks_or_predictions": len(missing),
        "missing_examples": missing[:20],
    }
    metrics = {
        **external_metrics,
        "external": external_metrics,
        "coverage": coverage,
        "quick_check": QUICK_CHECK,
        "external_task_type": "segmentation",
    }
    write_metrics(metrics)
    write_predictions(rows, ["sample_id", "dice", "iou"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    task_type = normalize_external_task_type(EXTERNAL_TASK_TYPE)
    if task_type == "mil_classification":
        run_external_classification(patch_level=False)
    elif task_type == "patch_classification":
        run_external_classification(patch_level=True)
    elif task_type == "survival":
        run_external_survival()
    elif task_type == "segmentation":
        run_external_segmentation()
    else:
        raise AssertionError(f"Unhandled task type: {task_type}")


if __name__ == "__main__":
    main()
