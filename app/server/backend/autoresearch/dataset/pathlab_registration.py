"""Register prepared AutoResearch datasets in the PathLab database."""

from __future__ import annotations

import csv
import json
import logging
import math
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
    if manifest.metadata.get("name"):
        return str(manifest.metadata["name"])[:255]
    if manifest.dataset_id in _KNOWN_DATASET_NAMES:
        return _KNOWN_DATASET_NAMES[manifest.dataset_id]
    raw = (manifest.dataset_id or "autoresearch-dataset").strip()
    raw = raw.replace(":", " - ").replace("/", " - ")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:255]


def _task_type_for_pathlab(manifest: DatasetManifest) -> str:
    task = (
        manifest.selected_for_task
        or (manifest.prepared_contract or {}).get("task_type")
        or ""
    )
    if "survival" in str(task).lower():
        return "wsi_survival"
    if "segmentation" in str(task).lower():
        return "patch_segmentation"
    if task == "patch_detection":
        return "patch_detection"
    return (
        "patch_classification"
        if _data_type_for_manifest(manifest) == "patch"
        else "wsi_classification"
    )


def _data_type_for_manifest(manifest: DatasetManifest) -> str:
    return "patch" if "patch" in manifest.selected_for_task else "wsi"


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
            extensions = _WSI_EXTS | (
                {".png", ".jpg", ".jpeg", ".bmp"}
                if _data_type_for_manifest(manifest) == "patch"
                else set()
            )
            if path.suffix.lower() not in extensions:
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
            for key in (
                "slide_id",
                "wsi_id",
                "image_id",
                "case_id",
                "slide",
                "filename",
                "file",
            ):
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
    owner_id = str(user_id or "").strip()
    if not owner_id:
        return {"status": "skipped", "reason": "no_owner"}
    metadata = manifest.metadata
    visibility = metadata.get("visibility")
    public = visibility == "public" if visibility else manifest.access == "public"
    organs = [
        str(value).strip() for value in metadata.get("organs", []) if str(value).strip()
    ]
    organ = "; ".join(dict.fromkeys(organs))[:100] or "Unknown"
    aggregation_level = metadata.get("aggregation_level", "file")
    source_url = metadata.get("source_url") or next(
        iter((metadata.get("download") or {}).get("urls", [])), ""
    )
    contract = manifest.prepared_contract or {}
    task_type = _task_type_for_pathlab(manifest)
    coco = None
    if task_type in {"patch_segmentation", "patch_detection"} and contract.get("annotations_file"):
        coco = json.loads(Path(contract["annotations_file"]).read_text())
        if (
            not all(
                isinstance(coco.get(key), list)
                for key in ["images", "annotations", "categories"]
            )
            or not coco["images"]
            or not coco["categories"]
        ):
            raise ValueError(
                "Segmentation requires COCO images, categories and an annotations list (empty for negative images)"
            )
        image_ids = {image["id"] for image in coco["images"]}
        category_ids = {category["id"] for category in coco["categories"]}
        if (
            len(image_ids) != len(coco["images"])
            or len(category_ids) != len(coco["categories"])
            or any(
                annotation.get("image_id") not in image_ids
                or annotation.get("category_id") not in category_ids
                or ("bbox" if task_type == "patch_detection" else "segmentation") not in annotation
                for annotation in coco["annotations"]
            )
        ):
            raise ValueError("Invalid COCO IDs or segmentation references")
        if task_type == "patch_detection":
            from backend.ai.utils.detection_dataset import coco_targets
            coco_targets(coco, [category["name"] for category in coco["categories"]])
    description = metadata.get("description") or ""
    description = "\n".join(
        filter(
            None,
            [
                description,
                f"Source: {source_url}" if source_url else "",
                f"License: {metadata.get('license') or 'Unknown'}",
                f"Provider: {manifest.provider}",
                f"Access: {manifest.access}",
            ],
        )
    )

    wsi_files = _iter_wsi_files(manifest)
    if coco is not None:
        names = {str(image["file_name"]) for image in coco["images"]}
        # Never register segmentation mask files as input images.
        wsi_files = [
            p
            for p in wsi_files
            if p.name in names or any(str(p).endswith("/" + name) for name in names)
        ]
    if not wsi_files:
        return {"status": "skipped", "reason": "no_wsi_files"}

    data_group = await DataGroupRepository.get_or_create(
        db,
        data_type=_data_type_for_manifest(manifest),
        aggregation_level=aggregation_level,
        task_type=task_type,
        name=f"{_data_type_for_manifest(manifest).upper()} {aggregation_level} {task_type}",
    )
    name = _dataset_name(manifest)
    dataset = await DatasetRepository.get_by_acquisition(
        db, user_id=owner_id, provider=manifest.provider, source_id=manifest.dataset_id
    )
    if dataset is None:
        dataset = await DatasetRepository.get_by_name(db, name, user_id=owner_id)
        if dataset is not None:
            raise ValueError(
                "Dataset name is already in use; choose a distinct name for this source"
            )
    previous = {}
    if dataset is not None:
        previous = getattr(dataset, "acquisition_metadata", None) or {}
        if previous.get("dataset_id") and previous["dataset_id"] != manifest.dataset_id:
            raise ValueError(
                "Dataset name is already registered to a different source; choose a distinct name"
            )
        if previous.get("provider") and previous["provider"] != manifest.provider:
            raise ValueError("Dataset name belongs to another provider")
        if (
            previous.get("aggregation_level")
            and previous["aggregation_level"] != aggregation_level
        ):
            raise ValueError(
                "Use a new dataset name when changing its aggregation level"
            )
        if dataset.data_type != _data_type_for_manifest(manifest) or task_type not in {task.task_type for task in dataset.tasks}:
            raise ValueError(
                "An acquired source cannot change its task or aggregation level"
            )
        stored_organ = getattr(dataset, "source_organ", None)
        previous_organ = (
            "; ".join(dict.fromkeys(previous.get("organs", [])))[:100] or "Unknown"
        )
        if (
            stored_organ
            and stored_organ.lower() != "unknown"
            and (organ.lower() == "unknown" or stored_organ != previous_organ)
        ):
            organ = stored_organ
        # Re-imports respect the current Data Repo visibility unless explicitly overridden.
        if visibility is None:
            public = dataset.is_public
        if not metadata.get("license") or metadata["license"].lower() == "unknown":
            metadata = {**metadata, "license": previous.get("license") or "Unknown"}
    if dataset is None:
        dataset = await DatasetRepository.get_or_create(
            db,
            name=name,
            data_type=_data_type_for_manifest(manifest),
            aggregation_level=aggregation_level,
            task_types=[task_type],
            user_id=owner_id,
            source_organ=organ,
            is_public=public,
            reuse_existing=True,
        )
    dataset.source_organ = organ
    dataset.is_public = public
    if not getattr(dataset, "description", None) or dataset.description == previous.get(
        "registration_description"
    ):
        dataset.description = description
    dataset.acquisition_metadata = {
        **metadata,
        "dataset_id": manifest.dataset_id,
        "provider": manifest.provider,
        "access": manifest.access,
        "source_url": source_url,
        "checksum_sha256": manifest.checksum_sha256,
        "registration_session": session_id,
        "registration_description": description,
    }

    labels = _read_labels(contract.get("labels_file"))
    splits = _read_splits(contract.get("splits_file"))
    patch_rows = {}
    if _data_type_for_manifest(manifest) == "patch" and contract.get("splits_file"):
        try:
            payload = json.loads(Path(contract["splits_file"]).read_text())
            for split, items in payload.items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and item.get("path"):
                            patch_rows[str(Path(item["path"]).resolve())] = (
                                item.get("label"),
                                split,
                            )
        except (OSError, ValueError):
            pass

    table_metadata = {}
    label_file = contract.get("labels_file")
    if label_file and Path(label_file).is_file():
        with Path(label_file).open(encoding="utf-8-sig", newline="") as stream:
            columns = metadata.get("annotation_columns") or {}
            reader = csv.DictReader(
                stream, delimiter="\t" if str(label_file).endswith(".tsv") else ","
            )
            for row in reader:
                slide = (
                    row.get(columns.get("slide_id", "slide_id"))
                    or row.get("wsi_id")
                    or row.get("filename")
                )
                if slide:
                    table_metadata[Path(slide).stem] = {
                        key: row.get(columns.get(key, key))
                        for key in ["label", "case_id", "event_time", "event_status"]
                    }
    created = 0
    skipped = 0
    missing_labels = missing_cases = missing_survival = 0
    image_map = {}
    label_values = set()
    missing_splits = 0
    cases = {}
    for path in wsi_files:
        wsi_id = _stable_wsi_id(dataset.dataset_id, path)
        if coco is not None and path.name in image_map:
            raise ValueError(
                "Duplicate image basenames require unambiguous COCO paths before registration"
            )
        image_map[path.name] = wsi_id
        existing = await WSIRepository.get_by_id(db, wsi_id)
        try:
            stat = path.stat()
            file_size = int(stat.st_size)
        except OSError:
            file_size = 0
        slide_id = path.stem
        annotations = table_metadata.get(slide_id, {})
        label = (
            (getattr(existing, "label", None) if existing else None)
            or annotations.get("label")
            or patch_rows.get(str(path.resolve()), (labels.get(slide_id), None))[0]
            or (getattr(existing, "label", None) if existing else None)
        )
        case_id = (
            getattr(existing, "case_id", None) if existing else None
        ) or annotations.get("case_id")
        split = (
            (getattr(existing, "split", None) if existing else None)
            or patch_rows.get(str(path.resolve()), (None, splits.get(slide_id)))[1]
            or (getattr(existing, "split", None) if existing else None)
        )
        if not split and case_id:
            split = splits.get(case_id)
        event_time = getattr(existing, "event_time", None) if existing else None
        event_status = getattr(existing, "event_status", None) if existing else None
        if event_time is None:
            event_time = annotations.get("event_time")
        if event_status is None:
            event_status = annotations.get("event_status")
        event_time = float(event_time) if event_time not in {None, ""} else None
        event_status = (
            int(event_status) if event_status in {"0", "1", 0, 1} else event_status
        )
        if case_id and aggregation_level == "case":
            case = cases.setdefault(case_id, {})
            for field, value in {
                "split": split,
                "label": label,
                "event_time": event_time,
                "event_status": event_status,
            }.items():
                if value in {None, ""}:
                    continue
                if field in case and case[field] != value:
                    raise ValueError(f"Inconsistent {field} within case {case_id}")
                case[field] = value
        if label:
            label_values.add(label)
        else:
            missing_labels += 1
        if not split:
            missing_splits += 1
        if aggregation_level == "case" and not case_id:
            missing_cases += 1
        if task_type == "wsi_survival" and (
            event_time in {None, ""} or event_status in {None, ""}
        ):
            missing_survival += 1
        if event_time is not None and (not math.isfinite(event_time) or event_time < 0):
            raise ValueError("Survival follow-up time cannot be negative")
        if event_status not in {None, "", 0, 1}:
            raise ValueError("event_status must use 0=censored, 1=event")
        if existing:
            existing.source = organ
            existing.associated_files = {
                **(getattr(existing, "associated_files", None) or {}),
                "acquisition": dataset.acquisition_metadata,
            }
            for field in ["label", "case_id", "event_time", "event_status"]:
                value = annotations.get(field)
                if value not in {None, ""} and getattr(existing, field, None) in {
                    None,
                    "",
                }:
                    setattr(
                        existing,
                        field,
                        float(value)
                        if field == "event_time"
                        else int(value)
                        if field == "event_status"
                        else value,
                    )
            if not getattr(existing, "label", None) and label:
                existing.label = label
            if not getattr(existing, "split", None) and split:
                existing.split = split
            skipped += 1
            continue
        await WSIRepository.create(
            db,
            wsi_id=wsi_id,
            original_filename=path.name,
            dataset_id=dataset.dataset_id,
            case_id=case_id or (slide_id if aggregation_level == "file" else None),
            label=label,
            wsi_path=str(path),
            user_id=owner_id,
            source=organ,
            associated_files={
                "acquisition": {
                    "dataset_id": manifest.dataset_id,
                    "provider": manifest.provider,
                    "source_url": source_url,
                    "organs": organs,
                    "license": metadata.get("license"),
                    "access": manifest.access,
                }
            },
            event_time=event_time,
            event_status=event_status if event_status != "" else None,
            split=split,
            file_size=file_size,
            data_type=_data_type_for_manifest(manifest),
            feature_extracted=False,
        )
        created += 1

    annotation_ready = task_type not in {"patch_segmentation", "patch_detection"}
    if coco is not None:
        from backend.database.repositories import SegmentationAnnotationRepository

        for image in coco["images"]:
            wsi_id = image_map.get(Path(image["file_name"]).name)
            if not wsi_id:
                raise ValueError("COCO image does not match the downloaded images")
            image["wsi_id"] = wsi_id
        await SegmentationAnnotationRepository.upsert(
            db,
            annotation_id=f"acquired-{dataset.dataset_id}",
            task_type=task_type,
            user_id=owner_id,
            source_dataset_id=dataset.dataset_id,
            annotations=coco,
            status="finalized",
            source="import",
        )
        annotation_ready = True

    await DatasetStatsRepository.recompute(db, dataset.dataset_id)
    return {
        "status": "registered",
        "dataset_id": dataset.dataset_id,
        "dataset_name": dataset.name,
        "created_wsi_count": created,
        "skipped_wsi_count": skipped,
        "total_wsi_count": len(wsi_files),
        "session_id": session_id,
        "is_public": public,
        "source_organ": organ,
        "source_url": source_url,
        "task_type": task_type,
        "aggregation_level": aggregation_level,
        "metadata_complete": bool(
            organs
            and organ.lower() != "unknown"
            and source_url
            and metadata.get("license")
            and metadata.get("license").lower() != "unknown"
        ),
        "missing_metadata": [
            key
            for key, value in {
                "organs": organs if organ.lower() != "unknown" else [],
                "license": metadata.get("license")
                if metadata.get("license", "").lower() != "unknown"
                else "",
                "source_url": source_url,
            }.items()
            if not value
        ],
        "training_ready": not missing_cases
        and (
            annotation_ready
            if task_type in {"patch_segmentation", "patch_detection"}
            else not missing_survival
            if task_type == "wsi_survival"
            else not missing_labels and len(label_values) >= 2
        ),
        "split_ready": missing_splits == 0,
        "label_count": len(label_values),
        "missing_annotations": {
            "labels": missing_labels if "classification" in task_type else 0,
            "case_ids": missing_cases,
            "survival": missing_survival,
            "segmentation": not annotation_ready,
        },
    }
