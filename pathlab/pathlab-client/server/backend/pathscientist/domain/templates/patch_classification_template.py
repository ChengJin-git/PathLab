"""PathLab patch classification training template.

Plan T5 (docs/plans/2026-04-28-pathscientist-latest-session-review-fixes-plan.md):
this template was missing — `domain/skills/patch_classification.yaml` pointed
at it but the file didn't exist, so `skill_browser load patch_classification`
crashed and grounding fell back to free mode (session_a70dd3a564c1).

Contracts (do NOT change without updating the skill yaml):
  - Default extractor: ``DEFAULT_EXTRACTOR = os.getenv("PATHLAB_EXTRACTOR", "uni2")``
    A pathology foundation model. **Never** silently fall back to ImageNet.
  - ``PATHLAB_QUICK_CHECK=1`` → 2 epochs, small subsample, write
    ``"quick_check": True`` in metrics.json so the orchestrator can refuse
    full-run promotion.
  - ``PATHLAB_MAX_EPOCHS`` → integer, default 50
  - Metrics: write to ``OUTPUT_DIR/metrics.json``, include
    ``auc / accuracy / quick_check / extractor / epochs / feature_dim``.
  - Best model checkpoint: ``OUTPUT_DIR/best_model.pth``.

Two input shapes are supported:
  0. PathLab DB export manifest: ``PATHLAB_TRAINING_MANIFEST`` or
     ``DATA_DIR/pathlab_training_manifest.json`` with records containing
     ``wsi_id``, ``wsi_path``, ``label``, and ``split``. This mirrors the
     PathLab TrainingTaskWSI + WSISlide tables for sandbox/offline runs.
  1. Pre-extracted features: ``DATA_DIR/features/<class>/<patch_id>.pt``
     and ``DATA_DIR/splits.json``. Tensor must be 1D ``(D,)``.
  2. Raw images: ``DATA_DIR/images/<class>/<patch_id>.{png,jpg,tif}``.
     The template loads ``common.extractors.get_extractor(DEFAULT_EXTRACTOR)``
     and computes features once per patch (frozen extractor, no fine-tune).
     This remains patch-level classification: feature extraction only converts
     each patch image into its representation; it is not a separate task
     objective and not a slide-level MIL pipeline.

The classifier head is a linear probe by default. The Code Agent may swap
in a small MLP under the ``# MODIFIABLE: model`` block; the contract is
``forward(features) -> logits[B, n_classes]``.
"""
from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any


def _ensure_template_common_on_path() -> None:
    """Make domain/templates/common importable from copied sandbox scripts."""
    candidates: list[Path] = []
    here = Path(__file__).resolve()
    candidates.append(here.parent)
    for parent in here.parents:
        candidates.append(parent / "server" / "backend" / "pathscientist" / "domain" / "templates")

    for candidate in candidates:
        registry = candidate / "common" / "extractors" / "registry.py"
        if registry.exists():
            value = str(candidate)
            if value not in sys.path:
                sys.path.insert(0, value)
            return


_ensure_template_common_on_path()

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
# sklearn imported lazily inside _evaluate so module-level helpers are
# unit-testable in environments without sklearn (e.g. the development
# venv outside the apptainer sandbox).

# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_EXTRACTOR = os.getenv("PATHLAB_EXTRACTOR", "uni2")
EPOCHS = int(os.getenv("PATHLAB_MAX_EPOCHS", "50"))
EARLY_STOPPING_PATIENCE = int(os.getenv("PATHLAB_EARLY_STOPPING_PATIENCE", "10"))
BATCH_SIZE = int(os.getenv("PATHLAB_BATCH_SIZE", "64"))
LR = float(os.getenv("PATHLAB_LR", "1e-4"))
WEIGHT_DECAY = float(os.getenv("PATHLAB_WD", "1e-5"))
QUICK_CHECK = os.getenv("PATHLAB_QUICK_CHECK", "") == "1"
RUN_MODE = os.getenv("PATHLAB_RUN_MODE", "full")
SEED = int(os.getenv("PATHLAB_SEED", "42"))

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

# Quick-check caps from the orchestrator (Plan T6). Hard cap epochs to 2 in
# quick-check regardless of PATHLAB_MAX_EPOCHS so a stuck script can't blow
# the iteration budget.
if QUICK_CHECK:
    EPOCHS = min(EPOCHS, 2)

MAX_TRAIN_SAMPLES = int(os.getenv("PATHLAB_MAX_TRAIN_SAMPLES", "0")) or None
MAX_VAL_SAMPLES = int(os.getenv("PATHLAB_MAX_VAL_SAMPLES", "0")) or None
MAX_TEST_SAMPLES = int(os.getenv("PATHLAB_MAX_TEST_SAMPLES", "0")) or None

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("patch_classification")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(OUTPUT_DIR / "train.log", mode="w"),
    ],
)


def _seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ── Data loading ───────────────────────────────────────────────────────────
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
_FEATURE_EXTS = (".pt",)


def _list_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)


class FeatureDataset(Dataset):
    """Reads pre-extracted .pt feature tensors. ``features[i]`` returns
    a (feature_vec, label_int) pair."""

    def __init__(self, items: list[tuple[Path, int]], cap: int | None = None):
        if cap and len(items) > cap:
            items = items[:cap]
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        path, label = self._items[idx]
        feat = torch.load(path, map_location="cpu")
        if feat.dim() != 1:
            feat = feat.flatten()
        return feat.float(), label


class ImageDataset(Dataset):
    """Reads raw image patches. Used only when no .pt features are
    available; pairs with a frozen extractor for online feature
    extraction."""

    def __init__(self, items: list[tuple[Path, int]], transform, cap: int | None = None):
        if cap and len(items) > cap:
            items = items[:cap]
        self._items = items
        self._transform = transform

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        from PIL import Image
        path, label = self._items[idx]
        img = Image.open(path).convert("RGB")
        return self._transform(img), label


def _build_class_index(class_dir: Path, exts: tuple[str, ...]) -> tuple[list[tuple[Path, int]], list[str]]:
    classes = sorted(
        d.name for d in class_dir.iterdir() if d.is_dir()
    )
    class_to_idx = {c: i for i, c in enumerate(classes)}
    items: list[tuple[Path, int]] = []
    for cls in classes:
        for f in _list_files(class_dir / cls, exts):
            items.append((f, class_to_idx[cls]))
    return items, classes


def _load_label_csv(
    csv_path: Path,
    items_root: Path,
) -> tuple[dict[str, list[tuple[Path, int]]], list[str]] | None:
    """Plan-2026-04-28 P1 #4: first-class support for ``label.csv`` /
    ``labels.csv`` patch datasets.

    Expected schema (any of):
      - ``filename,label`` — flat list, no split column → deterministic
        70/15/15 stratified split.
      - ``filename,label,split`` — split is one of train/val/test (case
        insensitive); used directly. Missing splits are inferred from
        the present ones (e.g. only TRAIN/TEST → val borrowed from
        train tail).
      - ``image,label`` / ``patch,label`` — alias columns for filename.

    Returns ``(splits, classes)`` or ``None`` if the file isn't usable.
    """
    if not csv_path.is_file():
        return None
    import csv

    try:
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        logger.warning("label csv %s unreadable: %s", csv_path, e)
        return None
    if not rows:
        return None

    fields = {k.lower(): k for k in rows[0].keys()}
    fname_field = next(
        (fields[k] for k in ("filename", "image", "patch", "path", "file") if k in fields),
        None,
    )
    label_field = next(
        (fields[k] for k in ("label", "class", "y") if k in fields),
        None,
    )
    split_field = next(
        (fields[k] for k in ("split", "fold") if k in fields),
        None,
    )
    if not fname_field or not label_field:
        logger.warning(
            "label csv %s missing required columns (need filename + label, got %s)",
            csv_path, list(rows[0].keys()),
        )
        return None

    classes: list[str] = []
    class_to_idx: dict[str, int] = {}
    by_split: dict[str, list[tuple[Path, int]]] = {"train": [], "val": [], "test": []}

    for r in rows:
        fname = (r.get(fname_field) or "").strip()
        label_str = (r.get(label_field) or "").strip()
        if not fname or not label_str:
            continue
        if label_str not in class_to_idx:
            class_to_idx[label_str] = len(class_to_idx)
            classes.append(label_str)
        label_idx = class_to_idx[label_str]

        # Resolve filename → absolute path. Try items_root/fname first,
        # then a glob fallback (some CSVs reference filenames without
        # subdirs but the actual file lives in a class subdir).
        candidate = items_root / fname
        if not candidate.exists():
            # Search for matching basename within items_root.
            matches = list(items_root.rglob(Path(fname).name))
            if matches:
                candidate = matches[0]
            else:
                continue

        split_name = "train"
        if split_field:
            sv = (r.get(split_field) or "").strip().lower()
            if sv in ("val", "valid", "validation"):
                split_name = "val"
            elif sv in ("test", "eval"):
                split_name = "test"
            elif sv in ("train", "training"):
                split_name = "train"
        by_split[split_name].append((candidate, label_idx))

    # Plan-2026-04-28 P1 #4: when the CSV has only TRAIN/TEST (no val),
    # carve val from the tail of train deterministically so MIL-style
    # 80/10/10 splits don't end up with empty val (which breaks early-
    # stopping selection).
    if not by_split["val"] and by_split["train"]:
        # Stratified borrow: take the last 15% of each class from train.
        new_train: list[tuple[Path, int]] = []
        new_val: list[tuple[Path, int]] = []
        by_class: dict[int, list[tuple[Path, int]]] = {}
        for it in by_split["train"]:
            by_class.setdefault(it[1], []).append(it)
        for cls_items in by_class.values():
            cls_items.sort(key=lambda x: str(x[0]))
            n_val = max(1, int(len(cls_items) * 0.15)) if len(cls_items) >= 4 else 0
            new_val.extend(cls_items[-n_val:] if n_val else [])
            new_train.extend(cls_items[:-n_val] if n_val else cls_items)
        by_split["train"] = new_train
        by_split["val"] = new_val

    if not any(by_split.values()):
        return None
    return by_split, classes


def _stratified_cap(items: list[tuple[Path, int]], cap: int) -> list[tuple[Path, int]]:
    """Plan-2026-04-28 P1 #4: stratified subsample for quick-check caps.

    Replaces the naive ``items[:cap]`` slice that could drop a whole
    class when the dataset is sorted by label. Preserves deterministic
    ordering within each class.
    """
    if cap <= 0 or len(items) <= cap:
        return items
    by_class: dict[int, list[tuple[Path, int]]] = {}
    for it in items:
        by_class.setdefault(it[1], []).append(it)
    n_classes = len(by_class)
    if n_classes == 0:
        return items[:cap]
    per_class = max(1, cap // n_classes)
    out: list[tuple[Path, int]] = []
    for cls_items in by_class.values():
        cls_items.sort(key=lambda x: str(x[0]))
        out.extend(cls_items[:per_class])
    # Deterministic order: by class index then path.
    out.sort(key=lambda x: (x[1], str(x[0])))
    return out[:cap]


def _split_items(items: list[tuple[Path, int]], train_ratio=0.7, val_ratio=0.15) -> dict[str, list[tuple[Path, int]]]:
    """Deterministic split when no splits.json is provided. Stratified by
    class so each split has ≥1 sample of each class when possible."""
    by_class: dict[int, list[tuple[Path, int]]] = {}
    for it in items:
        by_class.setdefault(it[1], []).append(it)
    train, val, test = [], [], []
    for cls_items in by_class.values():
        cls_items = sorted(cls_items, key=lambda x: str(x[0]))  # deterministic
        n = len(cls_items)
        n_train = max(1, int(n * train_ratio))
        n_val = max(1, int(n * val_ratio)) if n - n_train >= 2 else 0
        train.extend(cls_items[:n_train])
        val.extend(cls_items[n_train:n_train + n_val])
        test.extend(cls_items[n_train + n_val:])
    return {"train": train, "val": val, "test": test}


def _ensure_validation_split_from_train(
    splits: dict[str, list[tuple[Path, int]]],
    val_ratio: float = 0.1,
) -> dict[str, list[tuple[Path, int]]]:
    """Match PathLab PatchClassificationTrainer for train/test-only splits.

    Native PathLab patch classification auto-creates validation data from
    train when ``val`` is absent. It must not reuse the held-out test split
    for model selection or early stopping.
    """
    train_items = list(splits.get("train", []))
    val_items = list(splits.get("val", []))
    test_items = list(splits.get("test", []))
    if val_items or len(train_items) <= 1:
        return {"train": train_items, "val": val_items, "test": test_items}

    n_val = max(1, int(len(train_items) * val_ratio))
    rng = random.Random(SEED)
    rng.shuffle(train_items)
    return {
        "train": train_items[n_val:],
        "val": train_items[:n_val],
        "test": test_items,
    }


def _load_splits_json(splits_file: Path, items_root: Path) -> dict[str, list[tuple[Path, int]]] | None:
    if not splits_file.exists():
        return None
    try:
        raw = json.loads(splits_file.read_text())
    except Exception as e:
        logger.warning("splits.json unparseable: %s", e)
        return None
    out: dict[str, list[tuple[Path, int]]] = {"train": [], "val": [], "test": []}
    classes_seen: dict[str, int] = {}

    def _coerce(entry, default_label: int = 0) -> tuple[Path, int] | None:
        if isinstance(entry, dict):
            p = items_root / entry.get("path", "")
            label = entry.get("label", default_label)
            if isinstance(label, str):
                if label not in classes_seen:
                    classes_seen[label] = len(classes_seen)
                label = classes_seen[label]
        else:
            return None
        return (p, int(label)) if p.exists() else None

    for split in ("train", "val", "test"):
        for entry in raw.get(split, []) or []:
            ce = _coerce(entry)
            if ce is not None:
                out[split].append(ce)
    if not any(out.values()):
        return None
    return out


def _load_pathlab_training_manifest(
    manifest_path: Path,
) -> tuple[dict[str, list[tuple[Path, int]]], list[str]] | None:
    """Load a PathLab DB/training-task export for sandbox/offline patch runs.

    Expected records mirror TrainingTaskWSI + WSISlide:
    ``wsi_id``, ``wsi_path`` or ``path``, ``label``, and ``split``.
    """
    if not manifest_path.is_file():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("PathLab manifest %s unparseable: %s", manifest_path, e)
        return None
    records = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        return None

    labels = sorted(
        {
            str(item.get("label") or "").strip()
            for item in records
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        }
    )
    positive_label = os.getenv("PATHLAB_POSITIVE_CLASS", "MSIH")
    if positive_label in labels and len(labels) == 2:
        labels = [label for label in labels if label != positive_label] + [positive_label]
    if not labels:
        return None
    class_to_idx = {label: idx for idx, label in enumerate(labels)}
    splits: dict[str, list[tuple[Path, int]]] = {"train": [], "val": [], "test": []}

    for item in records:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        path_text = str(
            item.get("wsi_path")
            or item.get("image_path")
            or item.get("path")
            or ""
        ).strip()
        if not label or not path_text:
            continue
        image_path = Path(path_text)
        if not image_path.exists():
            continue
        split = str(item.get("split") or "train").strip().lower()
        if split in {"valid", "validation"}:
            split = "val"
        if split not in splits:
            split = "train"
        splits[split].append((image_path, class_to_idx[label]))

    if not any(splits.values()):
        return None
    return splits, labels


# ── Feature extractor wiring ───────────────────────────────────────────────
def _resolve_extractor(name: str):
    """Load the pathology foundation model. Hard-fail if it can't load —
    do NOT silently fall back to ResNet (Plan T5 contract)."""
    try:
        # PYTHONPATH-relative under the workspace at runtime.
        from common.extractors.registry import get_extractor
    except Exception as e:
        raise RuntimeError(
            f"common.extractors.registry not importable: {e}. "
            "This template requires the PathLab common library on PYTHONPATH."
        )
    try:
        ext = get_extractor(name)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load pathology extractor {name!r}: {e}. "
            "Pick another from the installed list — DO NOT silently use "
            "ImageNet weights."
        )
    return ext


# ── Model ──────────────────────────────────────────────────────────────────
# MODIFIABLE: model — Code Agent may swap LinearHead for a small MLP.
class LinearHead(nn.Module):
    def __init__(self, in_dim: int, n_classes: int):
        super().__init__()
        self.fc = nn.Linear(in_dim, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc(x)


# MODIFIABLE: loss — Code Agent may swap CrossEntropyLoss for focal/etc.
def _build_loss(class_counts: list[int]) -> nn.Module:
    """Build a class-balanced CrossEntropy loss.

    Plan-2026-04-28 P1 #4: a quick-check that subsamples train data can
    drop a class entirely → class_counts[i]==0 → ZeroDivisionError. Guard
    against that by treating zero-count classes as if they had 1 sample
    (effectively no boost) so training still proceeds with stratified
    weights for the remaining classes.
    """
    if class_counts and len(class_counts) > 1:
        total = sum(class_counts)
        n_classes = len(class_counts)
        # Replace 0 with 1 to avoid div-by-zero. This produces a finite
        # weight for the absent class; since no batch contains it, the
        # weight is never used.
        safe_counts = [c if c > 0 else 1 for c in class_counts]
        weights = torch.tensor(
            [total / (n_classes * c) for c in safe_counts],
            dtype=torch.float,
        )
        return nn.CrossEntropyLoss(weight=weights)
    return nn.CrossEntropyLoss()


# ── Training loop ──────────────────────────────────────────────────────────
def _evaluate(model, loader, device, n_classes) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, roc_auc_score
    model.eval()
    all_logits, all_labels = [], []
    with torch.no_grad():
        for feats, labels in loader:
            feats = feats.to(device)
            logits = model(feats)
            all_logits.append(logits.cpu())
            all_labels.append(labels)
    if not all_logits:
        return {"auc": 0.0, "accuracy": 0.0, "f1": 0.0, "confusion_matrix": []}
    logits = torch.cat(all_logits)
    labels = torch.cat(all_labels)
    preds = logits.argmax(dim=1).numpy()
    probs = F.softmax(logits, dim=1).numpy()
    metrics: dict[str, Any] = {}
    metrics["accuracy"] = float(accuracy_score(labels, preds))
    metrics["f1"] = float(f1_score(labels, preds, average="macro", zero_division=0))
    metrics["confusion_matrix"] = confusion_matrix(
        labels, preds, labels=list(range(n_classes))
    ).astype(int).tolist()
    if n_classes == 2:
        try:
            metrics["auc"] = float(roc_auc_score(labels, probs[:, 1]))
        except ValueError:
            metrics["auc"] = 0.0
    else:
        try:
            metrics["auc"] = float(roc_auc_score(labels, probs, multi_class="ovr"))
        except ValueError:
            metrics["auc"] = 0.0
    return metrics


def _split_class_counts(
    splits: dict[str, list[tuple[Path, int]]],
    classes: list[str],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for split_name, items in splits.items():
        split_counts = {label: 0 for label in classes}
        for _path, label_idx in items:
            if 0 <= int(label_idx) < len(classes):
                split_counts[classes[int(label_idx)]] += 1
        counts[split_name] = split_counts
    return counts


def _build_metrics_payload(
    *,
    test_metrics: dict[str, Any],
    best_val_metrics: dict[str, Any],
    feature_dim: int | None,
    classes: list[str],
    train_items: list[tuple[Path, int]],
    val_items: list[tuple[Path, int]],
    test_items: list[tuple[Path, int]],
    classifier_head_name: str,
    checkpoint_path: Path,
    epochs_completed: int,
    training_duration: float,
    wall_duration: float,
) -> dict[str, Any]:
    positive_class = os.getenv("PATHLAB_POSITIVE_CLASS", "MSIH")
    if positive_class not in classes and classes:
        positive_class = classes[-1]
    split_items = {"train": train_items, "val": val_items, "test": test_items}
    return {
        "auc": test_metrics.get("auc", 0.0),
        "accuracy": test_metrics.get("accuracy", 0.0),
        "f1": test_metrics.get("f1", 0.0),
        "val_auc": best_val_metrics.get("auc", 0.0),
        "val_accuracy": best_val_metrics.get("accuracy", 0.0),
        "val_f1": best_val_metrics.get("f1", 0.0),
        "epochs": epochs_completed if epochs_completed else EPOCHS,
        "epochs_max": EPOCHS,
        "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        "early_stopped": epochs_completed < EPOCHS if epochs_completed else False,
        "feature_dim": int(feature_dim or 0),
        "extractor": DEFAULT_EXTRACTOR,
        "classifier_head": classifier_head_name,
        "n_classes": len(classes),
        "classes": classes,
        "positive_class": positive_class,
        "n_train": len(train_items),
        "n_val": len(val_items),
        "n_test": len(test_items),
        "split_class_counts": _split_class_counts(split_items, classes),
        "val_metrics": best_val_metrics,
        "test_metrics": test_metrics,
        "confusion_matrix": test_metrics.get("confusion_matrix", []),
        "checkpoint_path": str(checkpoint_path),
        "task_level": "patch",
        "mil_aggregation": False,
        "duration_sec": round(training_duration, 2),
        "training_duration_sec": round(training_duration, 2),
        "wall_duration_sec": round(wall_duration, 2),
        "quick_check": QUICK_CHECK,
        "run_mode": RUN_MODE,
    }


def main() -> None:
    _seed_all(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(
        "patch_classification: extractor=%s epochs=%d quick_check=%s mode=%s device=%s",
        DEFAULT_EXTRACTOR, EPOCHS, QUICK_CHECK, RUN_MODE, device,
    )

    # 1. Locate the dataset. Prefer pre-extracted features; fall back to images.
    feature_root = DATA_DIR / "features"
    image_root = DATA_DIR / "images"
    splits_path = DATA_DIR / "splits.json"

    # Plan-2026-04-28 P2 #8: track wall-clock start so we can report
    # both training_duration_sec (the inner training loop only) AND
    # wall_duration_sec (everything from data loading + feature
    # materialization to test eval). The orchestrator should prefer the
    # wall-time value for scheduling decisions.
    wall_started = time.time()

    items: list[tuple[Path, int]] = []
    classes: list[str] = []
    use_features_directly = False
    feature_dim: int | None = None

    pathlab_manifest = Path(
        os.getenv("PATHLAB_TRAINING_MANIFEST", str(DATA_DIR / "pathlab_training_manifest.json"))
    )
    pathlab_loaded = _load_pathlab_training_manifest(pathlab_manifest)
    if pathlab_loaded is not None:
        splits, classes = pathlab_loaded
        items = splits["train"] + splits["val"] + splits["test"]
        logger.info(
            "Using PathLab training manifest %s: train=%d val=%d test=%d classes=%d",
            pathlab_manifest,
            len(splits["train"]),
            len(splits["val"]),
            len(splits["test"]),
            len(classes),
        )
    elif feature_root.is_dir():
        items, classes = _build_class_index(feature_root, _FEATURE_EXTS)
        if items:
            use_features_directly = True
            sample = torch.load(items[0][0], map_location="cpu")
            feature_dim = sample.flatten().shape[0]
            logger.info("Using pre-extracted features: dim=%d, n=%d", feature_dim, len(items))

    if not items and image_root.is_dir():
        items, classes = _build_class_index(image_root, _IMAGE_EXTS)
        logger.info("Using raw images: n=%d", len(items))

    if not items:
        raise RuntimeError(
            "No data found. Expected PATHLAB_TRAINING_MANIFEST / "
            "DATA_DIR/pathlab_training_manifest.json, DATA_DIR/features/<class>/*.pt, "
            f"or DATA_DIR/images/<class>/*.{{png,jpg,...}}; got DATA_DIR={DATA_DIR}"
        )

    n_classes = max(len({i[1] for i in items}), 2)

    # 2. Splits. PathLab manifest wins when present; otherwise try label.csv
    # first (common
    # patch-dataset shape), then splits.json, then deterministic fallback.
    splits = locals().get("splits")
    images_root_for_csv = image_root if not use_features_directly else feature_root
    for csv_name in ("label.csv", "labels.csv"):
        csv_path = DATA_DIR / csv_name
        if csv_path.exists():
            csv_loaded = _load_label_csv(csv_path, images_root_for_csv)
            if csv_loaded is not None:
                splits, classes = csv_loaded
                # Refresh items list from the CSV-derived splits so
                # downstream class-count math sees the same population.
                items = splits["train"] + splits["val"] + splits["test"]
                n_classes = max(len({i[1] for i in items}), 2)
                logger.info(
                    "Loaded label CSV %s: train=%d val=%d test=%d classes=%d",
                    csv_name, len(splits["train"]), len(splits["val"]),
                    len(splits["test"]), len(classes),
                )
                break
    if splits is None:
        splits = _load_splits_json(splits_path, images_root_for_csv)
    if splits is None:
        splits = _split_items(items)
    splits = _ensure_validation_split_from_train(splits)
    train_items = splits["train"]
    val_items = splits["val"]
    test_items = splits["test"] or splits["val"]

    # Plan-2026-04-28 P1 #4: stratified caps so a class with few samples
    # doesn't get dropped entirely under quick-check (which would then
    # ZeroDivisionError in _build_loss).
    if MAX_TRAIN_SAMPLES is not None:
        train_items = _stratified_cap(train_items, MAX_TRAIN_SAMPLES)
    if MAX_VAL_SAMPLES is not None:
        val_items = _stratified_cap(val_items, MAX_VAL_SAMPLES)
    if MAX_TEST_SAMPLES is not None:
        test_items = _stratified_cap(test_items, MAX_TEST_SAMPLES)

    logger.info("Splits: train=%d val=%d test=%d", len(train_items), len(val_items), len(test_items))

    # 3. Extractor + datasets.
    if use_features_directly:
        train_ds: Dataset = FeatureDataset(train_items)
        val_ds: Dataset = FeatureDataset(val_items)
        test_ds: Dataset = FeatureDataset(test_items)
    else:
        ext = _resolve_extractor(DEFAULT_EXTRACTOR)
        ext.eval().to(device)
        transform = ext.get_transforms() if hasattr(ext, "get_transforms") else None
        if transform is None:
            raise RuntimeError(
                f"Extractor {DEFAULT_EXTRACTOR!r} has no get_transforms; "
                "cannot construct image preprocessing pipeline."
            )

        # Online feature extraction: wrap each split's images so __getitem__
        # returns the extractor's output. Frozen extractor — no grad.
        class _OnlineFeatures(Dataset):
            def __init__(self, items, transform, ext, device):
                self._items = items
                self._transform = transform
                self._ext = ext
                self._device = device

            def __len__(self):
                return len(self._items)

            def __getitem__(self, idx):
                from PIL import Image
                path, label = self._items[idx]
                img = Image.open(path).convert("RGB")
                t = self._transform(img).unsqueeze(0).to(self._device)
                with torch.no_grad():
                    feat = self._ext(t).squeeze(0).cpu()
                return feat.float(), label

        train_ds = _OnlineFeatures(train_items, transform, ext, device)
        val_ds = _OnlineFeatures(val_items, transform, ext, device)
        test_ds = _OnlineFeatures(test_items, transform, ext, device)
        # Probe one item to get feature_dim.
        sample_feat, _ = train_ds[0] if len(train_ds) else (torch.zeros(1), 0)
        feature_dim = sample_feat.shape[0]

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    # 4. Model + loss + optimizer.
    model = LinearHead(feature_dim or 1024, n_classes).to(device)

    class_counts: list[int] = [0] * n_classes
    for _, lbl in train_items:
        class_counts[lbl] += 1
    criterion = _build_loss(class_counts).to(device)
    optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)

    # 5. Train.
    best_val_auc = -1.0
    best_val_metrics: dict[str, Any] = {}
    best_state: dict[str, Any] | None = None
    epochs_without_improvement = 0
    last_epoch_completed = 0
    started = time.time()
    for epoch in range(EPOCHS):
        model.train()
        running_loss = 0.0
        for feats, labels in train_loader:
            feats = feats.to(device)
            labels = labels.to(device)
            optimizer.zero_grad()
            logits = model(feats)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * feats.size(0)
        avg_loss = running_loss / max(len(train_ds), 1)
        val_metrics = _evaluate(model, val_loader, device, n_classes)
        logger.info(
            "epoch %d/%d  loss=%.4f  val_auc=%.4f  val_acc=%.4f",
            epoch + 1, EPOCHS, avg_loss, val_metrics["auc"], val_metrics["accuracy"],
        )
        last_epoch_completed = epoch + 1
        if val_metrics["auc"] > best_val_auc:
            best_val_auc = val_metrics["auc"]
            best_val_metrics = dict(val_metrics)
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= EARLY_STOPPING_PATIENCE:
                logger.info(
                    "Early stopping at epoch %d "
                    "(no val_auc improvement for %d epochs)",
                    epoch + 1, EARLY_STOPPING_PATIENCE,
                )
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    torch.save(model.state_dict(), OUTPUT_DIR / "best_model.pth")

    # 6. Test + emit metrics.
    test_metrics = _evaluate(model, test_loader, device, n_classes)
    training_duration = time.time() - started
    wall_duration = time.time() - wall_started
    checkpoint_path = OUTPUT_DIR / "best_model.pth"
    metrics = _build_metrics_payload(
        test_metrics=test_metrics,
        best_val_metrics=best_val_metrics or {"auc": best_val_auc},
        feature_dim=feature_dim,
        classes=classes,
        train_items=train_items,
        val_items=val_items,
        test_items=test_items,
        classifier_head_name=type(model).__name__,
        checkpoint_path=checkpoint_path,
        epochs_completed=last_epoch_completed if last_epoch_completed else EPOCHS,
        training_duration=training_duration,
        wall_duration=wall_duration,
    )
    (OUTPUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    logger.info("Wrote metrics.json: %s", json.dumps(metrics))


if __name__ == "__main__":
    main()
