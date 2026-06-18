"""Register prepared PathScientist datasets in the PathLab database."""
from __future__ import annotations

import csv
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from backend.database.repositories import (
    DataGroupRepository,
    DatasetRepository,
    WSIRepository,
)
from backend.database.repositories.dataset_stats import DatasetStatsRepository

from .types import DatasetManifest

logger = logging.getLogger(__name__)

_WSI_EXTS = {
    ".svs",
    ".svslide",
    ".ndpi",
    ".scn",
    ".mrxs",
    ".bif",
    ".vsi",
    ".vms",
    ".vmu",
    ".kfb",
    ".sdpc",
    ".tmap",
    ".mds",
    ".mdsx",
    ".qptiff",
    ".tron",
    ".isyntax",
    ".dyj",
    ".dyqx",
    ".ibl",
    ".zyp",
    ".tif",
    ".tiff",
}

_KNOWN_DATASET_NAMES = {
    "kaggle:prostate-cancer-grade-assessment": "PANDA - Prostate cANcer graDe Assessment",
}


def _dataset_name(manifest: DatasetManifest) -> str:
    if manifest.dataset_id in _KNOWN_DATASET_NAMES:
        return _KNOWN_DATASET_NAMES[manifest.dataset_id]
    raw = (manifest.dataset_id or "pathscientist-dataset").strip()
    raw = raw.replace(":", " - ").replace("/", " - ")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:255]


def _task_type_for_pathlab(manifest: DatasetManifest) -> str:
    task = (
        (manifest.prepared_contract or {}).get("task_type")
        or manifest.selected_for_task
        or ""
    )
    return "survival" if "survival" in str(task).lower() else "classification"


def _slide_roots(manifest: DatasetManifest) -> list[Path]:
    contract = manifest.prepared_contract or {}
    roots: list[Path] = []
    for key in ("wsi_dir", "wsi_files_dir", "slides_dir"):
        value = str(contract.get(key) or "").strip()
        if value:
            roots.append(Path(value))
    if manifest.raw_root:
        roots.append(Path(manifest.raw_root))
    return roots


def _iter_wsi_files(manifest: DatasetManifest) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for root in _slide_roots(manifest):
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            if not path.is_file():
                continue
            if path.suffix.lower() not in _WSI_EXTS:
                continue
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(path)
    return out


def _read_labels(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    with p.open("r", newline="", encoding="utf-8") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel
        rows = csv.DictReader(fh, dialect=dialect)
        out: dict[str, str] = {}
        for row in rows:
            lowered = {str(k or "").strip().lower(): v for k, v in row.items()}
            slide = ""
            for key in ("slide_id", "wsi_id", "image_id", "case_id", "slide", "filename", "file"):
                value = lowered.get(key)
                if value:
                    slide = Path(str(value).strip()).stem
                    break
            label = ""
            for key in ("label", "class", "grade", "isup_grade", "gleason_score"):
                value = lowered.get(key)
                if value is not None and str(value).strip() != "":
                    label = str(value).strip()
                    break
            if slide and label:
                out[slide] = label
        return out


def _read_splits(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return out
    for split in ("train", "val", "test"):
        values = data.get(split) or []
        if not isinstance(values, list):
            continue
        for slide in values:
            out[Path(str(slide)).stem] = split
    return out


def _stable_wsi_id(dataset_id: str, path: Path) -> str:
    try:
        key = f"{dataset_id}:{path.resolve()}"
    except OSError:
        key = f"{dataset_id}:{path}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


async def register_manifest_with_pathlab(
    *,
    db,
    manifest: DatasetManifest,
    session_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create/reuse PathLab dataset rows for a prepared manifest.

    The operation is idempotent: WSI IDs are derived from dataset_id + resolved
    path, so repeated registration skips existing rows.
    """
    if manifest.status != "prepared":
        return {"status": "skipped", "reason": f"manifest_status:{manifest.status}"}

    wsi_files = _iter_wsi_files(manifest)
    if not wsi_files:
        return {"status": "skipped", "reason": "no_wsi_files"}

    task_type = _task_type_for_pathlab(manifest)
    data_group = await DataGroupRepository.get_or_create(
        db,
        data_type="wsi",
        aggregation_level="file",
        task_type=task_type,
        name=f"WSI File-level {task_type.capitalize()}",
    )
    name = _dataset_name(manifest)
    dataset = await DatasetRepository.get_by_name(db, name, user_id=user_id)
    if dataset is None:
        dataset = await DatasetRepository.get_or_create(
            db,
            name=name,
            group_id=data_group.group_id,
            user_id=user_id,
            source_organ="",
            is_public=user_id is None,
            reuse_existing=True,
        )

    contract = manifest.prepared_contract or {}
    labels = _read_labels(contract.get("labels_file"))
    splits = _read_splits(contract.get("splits_file"))

    created = 0
    skipped = 0
    for path in wsi_files:
        wsi_id = _stable_wsi_id(dataset.dataset_id, path)
        if await WSIRepository.get_by_id(db, wsi_id):
            skipped += 1
            continue
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
        except OSError:
            file_size = 0
        slide_id = path.stem
        await WSIRepository.create(
            db,
            wsi_id=wsi_id,
            original_filename=path.name,
            dataset_id=dataset.dataset_id,
            case_id=slide_id,
            label=labels.get(slide_id),
            wsi_path=str(path),
            user_id=user_id,
            source="",
            split=splits.get(slide_id),
            file_size=file_size,
            data_type="wsi",
            feature_extracted=False,
        )
        created += 1

    await DatasetStatsRepository.recompute(db, dataset.dataset_id)
    return {
        "status": "registered",
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.name,
        "created_wsi_count": created,
        "skipped_wsi_count": skipped,
        "total_wsi_count": len(wsi_files),
        "session_id": session_id,
    }
