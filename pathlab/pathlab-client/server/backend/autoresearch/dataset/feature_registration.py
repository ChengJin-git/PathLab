"""Register AutoResearch feature artifacts on PathLab WSI rows."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.database.models import WSISlide


def _coords_dir_for_features_dir(features_dir: Path) -> Path | None:
    """Return PathLab coordinates dir for flat or legacy hashed feature dirs."""
    parts = features_dir.parts
    try:
        features_index = parts.index("features")
    except ValueError:
        return None
    if len(parts) <= features_index + 1:
        return None
    dataset_root = Path(*parts[:features_index])
    if not str(dataset_root):
        dataset_root = Path(features_dir.anchor or ".")
    if len(parts) > features_index + 2:
        params_hash = parts[features_index + 2]
        return dataset_root / "coordinates" / params_hash
    return dataset_root / "coordinates"


def _dataset_root_for_pathlab_features_dir(features_dir: Path) -> Path | None:
    parts = features_dir.parts
    try:
        features_index = parts.index("features")
    except ValueError:
        return None
    dataset_root = Path(*parts[:features_index])
    if not str(dataset_root):
        dataset_root = Path(features_dir.anchor or ".")
    return dataset_root


def _host_wsi_dir_for_features_dir(features_dir: Path) -> Path | None:
    dataset_root = _dataset_root_for_pathlab_features_dir(features_dir)
    if dataset_root is None:
        return None
    for dirname in ("WSIs", "wsis", "wsi_files"):
        candidate = dataset_root / dirname
        if candidate.is_dir():
            return candidate
    return None


def _dataset_manifest_for_features_dir(features_dir: Path) -> Path | None:
    dataset_root = _dataset_root_for_pathlab_features_dir(features_dir)
    if dataset_root is None:
        return None
    for name in (
        "dataset_manifest.json",
        "autoresearch_pathlab_view_manifest.json",
    ):
        manifest = dataset_root / name
        if manifest.is_file():
            return manifest
    return None


def _load_pathlab_slide_map(features_dir: Path) -> dict[str, dict[str, str]]:
    manifest_path = _dataset_manifest_for_features_dir(features_dir)
    if manifest_path is None:
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("layout") != "pathlab_dataset_view":
        return {}
    out: dict[str, dict[str, str]] = {}
    for item in data.get("pathlab_slide_map") or []:
        if not isinstance(item, dict):
            continue
        slide_id = str(item.get("slide_id") or item.get("wsi_id") or "").strip()
        source_path = str(item.get("wsi_path") or "").strip()
        if not slide_id or not source_path:
            continue
        source_key = str(Path(source_path).expanduser())
        original_stem = Path(source_path).stem
        info = {
            "slide_id": slide_id,
            "wsi_path": source_path,
            "original_stem": original_stem,
        }
        out[slide_id] = info
        out[source_key] = info
        if original_stem:
            out[original_stem] = info
    return out


def _candidate_extraction_meta_paths(features_dir: Path) -> list[Path]:
    return [
        features_dir / "extraction_meta.json",
        features_dir.parent / "extraction_meta.json",
        features_dir.parent.parent / "extraction_meta.json",
    ]


def _record_is_no_tissue(record: Any) -> bool:
    if isinstance(record, dict):
        values = [
            record.get("status"),
            record.get("reason"),
            record.get("error"),
            record.get("message"),
        ]
    else:
        values = [record]
    text = " ".join(str(value or "") for value in values).strip().lower()
    normalized = text.replace("-", "_").replace(" ", "_")
    return (
        "no_tissue" in normalized
        or "no_detectable_tissue" in normalized
        or "without_detectable_tissue" in normalized
        or "blank_or_no_detectable_tissue" in normalized
    )


def _load_extraction_results(features_dir: Path) -> dict[str, dict[str, Any]]:
    for meta_path in _candidate_extraction_meta_paths(features_dir):
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        results = meta.get("results")
        if not isinstance(results, dict):
            continue
        out: dict[str, dict[str, Any]] = {}
        for key, record in results.items():
            if isinstance(record, dict):
                out[str(key)] = dict(record)
            else:
                out[str(key)] = {"status": str(record)}
        return out
    return {}


def _extraction_record_for_wsi(
    *,
    wsi_path: Path,
    slide_map: dict[str, dict[str, str]],
    extraction_results: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    original_stem = _slide_id_from_wsi_path(wsi_path)
    mapped = slide_map.get(str(wsi_path)) or slide_map.get(original_stem)
    candidate_ids: list[str] = [original_stem, wsi_path.name, str(wsi_path)]
    if mapped is not None:
        for key in ("slide_id", "original_stem", "wsi_path"):
            value = str(mapped.get(key) or "").strip()
            if value and value not in candidate_ids:
                candidate_ids.append(value)
            stem = Path(value).stem if value else ""
            if stem and stem not in candidate_ids:
                candidate_ids.append(stem)

    for slide_id in candidate_ids:
        record = extraction_results.get(slide_id)
        if record is not None:
            return slide_id, record
    return None, None


def _slide_id_from_feature(path: Path) -> str:
    return path.stem


def _slide_id_from_wsi_path(path: str | Path) -> str:
    return Path(str(path)).stem


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, ValueError):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _feature_candidates_for_wsi(
    *,
    wsi_path: Path,
    feature_files: dict[str, Path],
    slide_map: dict[str, dict[str, str]],
) -> tuple[str, Path] | tuple[None, None]:
    original_stem = _slide_id_from_wsi_path(wsi_path)
    mapped = slide_map.get(str(wsi_path)) or slide_map.get(original_stem)
    candidate_ids: list[str] = [original_stem]
    if mapped is not None:
        for key in ("slide_id", "original_stem"):
            value = str(mapped.get(key) or "").strip()
            if value and value not in candidate_ids:
                candidate_ids.append(value)

    for slide_id in candidate_ids:
        feature_path = feature_files.get(slide_id)
        if feature_path is not None:
            return slide_id, feature_path
    return None, None


async def register_extracted_features_with_pathlab(
    *,
    db,
    features_dir: str | Path,
    wsi_dir: str | Path = "",
    extractor_name: str = "",
    data_role: str = "internal",
) -> dict[str, Any]:
    """Mark matching PathLab WSI rows as having AutoResearch features.

    Matching is intentionally file-based: AutoResearch feature files are named
    by slide stem, and PathLab WSI rows store the source WSI path.
    """
    feature_root = Path(features_dir).expanduser()
    if not feature_root.is_dir():
        return {"status": "skipped", "reason": "features_dir_missing"}

    feature_files = {
        _slide_id_from_feature(path): path
        for path in sorted(feature_root.glob("*.pt"))
        if path.is_file()
    }
    if not feature_files:
        return {"status": "skipped", "reason": "no_feature_files"}

    wsi_root = Path(wsi_dir).expanduser() if wsi_dir else None
    if wsi_root is not None and str(wsi_root).startswith("/data"):
        wsi_root = _host_wsi_dir_for_features_dir(feature_root)
    coords_dir = _coords_dir_for_features_dir(feature_root)
    slide_map = _load_pathlab_slide_map(feature_root)
    extraction_results = _load_extraction_results(feature_root)
    if slide_map:
        # A PathLab dataset view stages WSIs under ``wsi_files/<uuid>.svs``,
        # while DB rows keep the original WSI path. Match through the manifest
        # instead of filtering original rows out by the staging directory.
        wsi_root = None
    result = await db.execute(select(WSISlide))
    rows = result.scalars().all()
    updated = 0
    role = str(data_role or "internal").strip() or "internal"
    extractor = str(extractor_name or "").strip() or feature_root.parent.name

    for row in rows:
        raw_wsi_path = str(getattr(row, "wsi_path", "") or "")
        if not raw_wsi_path:
            continue
        wsi_path = Path(raw_wsi_path).expanduser()
        if wsi_root is not None and not _path_is_under(wsi_path, wsi_root):
            continue
        slide_id, feature_path = _feature_candidates_for_wsi(
            wsi_path=wsi_path,
            feature_files=feature_files,
            slide_map=slide_map,
        )
        extraction_slide_id, extraction_record = _extraction_record_for_wsi(
            wsi_path=wsi_path,
            slide_map=slide_map,
            extraction_results=extraction_results,
        )
        if feature_path is None and not _record_is_no_tissue(extraction_record):
            continue

        coords_path = None
        if coords_dir is not None and slide_id is not None:
            candidate = coords_dir / f"{slide_id}_coords.h5"
            if candidate.is_file():
                coords_path = candidate

        associated = dict(getattr(row, "associated_files", None) or {})
        autoresearch_features = dict(associated.get("autoresearch_features") or {})
        feature_info: dict[str, Any] = {
            "features_dir": str(feature_root),
            "extractor_name": extractor,
        }
        if feature_path is not None:
            feature_info.update(
                {
                    "status": "ready",
                    "feature_path": str(feature_path),
                    "coordinates_path": str(coords_path) if coords_path is not None else "",
                }
            )
        else:
            record = extraction_record if isinstance(extraction_record, dict) else {}
            feature_info.update(
                {
                    "status": "no_tissue",
                    "feature_path": "",
                    "coordinates_path": "",
                    "reason": str(record.get("reason") or "No detectable tissue found"),
                }
            )
            if extraction_slide_id:
                feature_info["slide_id"] = extraction_slide_id
        autoresearch_features[role] = feature_info
        associated["autoresearch_features"] = autoresearch_features
        row.associated_files = associated
        if feature_path is not None:
            row.feature_extracted = True
        updated += 1

    if updated:
        await db.commit()
    return {
        "status": "registered" if updated else "skipped",
        "updated_wsi_count": updated,
        "feature_file_count": len(feature_files),
        "features_dir": str(feature_root),
    }
