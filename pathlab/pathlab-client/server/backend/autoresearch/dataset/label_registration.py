"""Backfill PathLab labels inferred by AutoResearch onto WSI rows."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.database.models import WSISlide


def _read_label_map(path: str | Path) -> dict[str, str]:
    labels_path = Path(path).expanduser()
    if not labels_path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        with labels_path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel_tab if labels_path.suffix.lower() == ".tsv" else csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            for row in reader:
                slide_id = str(
                    row.get("slide_id")
                    or row.get("wsi_id")
                    or row.get("filename")
                    or row.get("file_name")
                    or ""
                ).strip()
                label = str(row.get("label") or row.get("class") or "").strip()
                if slide_id and label:
                    out[Path(slide_id).stem] = label
    except OSError:
        return {}
    return out


def _read_split_map(path: str | Path) -> dict[str, str]:
    splits_path = Path(path).expanduser()
    if not splits_path.is_file():
        return {}
    try:
        payload = json.loads(splits_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for split in ("train", "val", "test"):
        values = payload.get(split) or []
        if not isinstance(values, list):
            continue
        for value in values:
            slide_id = Path(str(value or "")).stem
            if slide_id:
                out[slide_id] = split
    return out


def _manifest_map(manifest: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in manifest.get("pathlab_slide_map") or []:
        if not isinstance(item, dict):
            continue
        slide_id = str(item.get("slide_id") or "").strip()
        wsi_id = str(item.get("wsi_id") or "").strip()
        if slide_id and wsi_id:
            out[Path(slide_id).stem] = wsi_id
    return out


async def register_inferred_labels_with_pathlab(
    *,
    db,
    dataset_view_dir: str | Path = "",
    manifest_file: str | Path = "",
    labels_file: str | Path = "",
    splits_file: str | Path = "",
) -> dict[str, Any]:
    """Update labels/splits for the PathLab WSI rows named in a view manifest."""
    view_root = Path(dataset_view_dir).expanduser() if dataset_view_dir else None
    manifest_path = Path(manifest_file).expanduser() if manifest_file else None
    if manifest_path is None and view_root is not None:
        manifest_path = view_root / "dataset_manifest.json"
    if manifest_path is None or not manifest_path.is_file():
        return {"status": "skipped", "reason": "manifest_missing"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "skipped", "reason": f"manifest_unreadable:{exc}"}
    if not isinstance(manifest, dict):
        return {"status": "skipped", "reason": "manifest_invalid"}

    if not labels_file and view_root is not None:
        labels_file = view_root / str(manifest.get("labels_file") or "labels.csv")
    if not splits_file and view_root is not None:
        splits_file = view_root / str(manifest.get("splits_file") or "splits.json")
    label_map = _read_label_map(labels_file)
    if not label_map:
        return {"status": "skipped", "reason": "labels_missing"}
    split_map = _read_split_map(splits_file) if splits_file else {}
    slide_to_wsi = _manifest_map(manifest)
    if not slide_to_wsi:
        return {"status": "skipped", "reason": "manifest_slide_map_missing"}

    wsi_ids = [wsi_id for slide_id, wsi_id in slide_to_wsi.items() if slide_id in label_map]
    if not wsi_ids:
        return {"status": "skipped", "reason": "no_matching_wsi_ids"}
    result = await db.execute(select(WSISlide).where(WSISlide.wsi_id.in_(wsi_ids)))
    rows = {row.wsi_id: row for row in result.scalars().all()}
    updated = 0
    dataset_ids: set[str] = set()
    for slide_id, label in label_map.items():
        wsi_id = slide_to_wsi.get(slide_id)
        row = rows.get(wsi_id or "")
        if row is None:
            continue
        row.label = label
        split = split_map.get(slide_id)
        if split:
            row.split = split
        dataset_id = str(getattr(row, "dataset_id", "") or "")
        if dataset_id:
            dataset_ids.add(dataset_id)
        updated += 1

    if updated:
        try:
            from backend.database.repositories.dataset_stats import DatasetStatsRepository

            for dataset_id in sorted(dataset_ids):
                await DatasetStatsRepository.recompute(db, dataset_id)
        except Exception:
            pass
        await db.commit()
    return {
        "status": "registered" if updated else "skipped",
        "updated_wsi_count": updated,
        "label_count": len(label_map),
        "dataset_ids": sorted(dataset_ids),
    }
