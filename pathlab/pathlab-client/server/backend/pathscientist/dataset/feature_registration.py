"""Register PathScientist feature artifacts on PathLab WSI rows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.database.models import WSISlide


def _coords_dir_for_features_dir(features_dir: Path) -> Path | None:
    """Return PathLab coordinates/<params_hash> for features/<extractor>/<hash>."""
    parts = features_dir.parts
    try:
        features_index = parts.index("features")
    except ValueError:
        return None
    if len(parts) <= features_index + 2:
        return None
    params_hash = parts[features_index + 2]
    dataset_root = Path(*parts[:features_index])
    if not str(dataset_root):
        dataset_root = Path(features_dir.anchor or ".")
    return dataset_root / "coordinates" / params_hash


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


async def register_extracted_features_with_pathlab(
    *,
    db,
    features_dir: str | Path,
    wsi_dir: str | Path = "",
    extractor_name: str = "",
    data_role: str = "internal",
) -> dict[str, Any]:
    """Mark matching PathLab WSI rows as having PathScientist features.

    Matching is intentionally file-based: PathScientist feature files are named
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
        slide_id = _slide_id_from_wsi_path(wsi_path)
        feature_path = feature_files.get(slide_id)
        if feature_path is None:
            continue

        coords_path = None
        if coords_dir is not None:
            candidate = coords_dir / f"{slide_id}_coords.h5"
            if candidate.is_file():
                coords_path = candidate

        associated = dict(getattr(row, "associated_files", None) or {})
        pathscientist_features = dict(associated.get("pathscientist_features") or {})
        pathscientist_features[role] = {
            "feature_path": str(feature_path),
            "coordinates_path": str(coords_path) if coords_path is not None else "",
            "features_dir": str(feature_root),
            "extractor_name": extractor,
        }
        associated["pathscientist_features"] = pathscientist_features
        row.associated_files = associated
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
