"""Normalize a WSI/MIL dataset into prepared/WSIs/*.

Raw layout expected (any of):

    raw_root/WSIs/*.{svs,tiff,tif,ndpi,mrxs}
    raw_root/slides/*.{svs,tiff,tif,ndpi,mrxs}
    raw_root/train_images/*.{svs,tiff,tif,ndpi,mrxs} + raw_root/train.csv
    raw_root/*.{svs,tiff,tif,ndpi,mrxs}

Prepared layout produced:

    prepared_root/WSIs/*.{svs,...}      (symlinks where possible)
    prepared_root/labels.csv            canonical slide_id,label table
    prepared_root/splits.json           when enough labeled slides exist

Always returns ``requires_feature_extraction = True`` because the v1
skill chain expects a feature-extraction step before MIL training.
"""
from __future__ import annotations

import csv
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from .base import NormalizerError

logger = logging.getLogger(__name__)

_WSI_EXTS = (".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn", ".vms", ".vmu")
_CONVENTIONAL_SLIDE_DIRS = (
    "WSIs", "wsis", "slides", "slide", "wsi", "WSI", "wsi_images",
    "train_images", "images",
)
_CONVENTIONAL_LABEL_FILES = (
    "labels.csv", "label.csv", "labels.tsv", "label.tsv",
    "train.csv", "train_labels.csv",
)
_LABEL_FILE_GLOBS = ("*label*.csv", "*label*.tsv", "*labels*.csv", "*labels*.tsv")
_SLIDE_ID_COLUMNS = (
    "slide_id", "wsi_id", "image_id", "case_id",
    "slide", "filename", "file",
)
_LABEL_COLUMNS = (
    "label", "class", "grade", "isup_grade", "gleason_score",
    # SciDB chronic gastritis WSI labels ship as Task1..Task4:
    # inflammation, activity, atrophy, intestinal metaplasia. Without a
    # target-specific column from the planner, Task1 is the deterministic
    # default so the dataset can still be prepared.
    "Task1", "Task2", "Task3", "Task4",
)


def _slide_sources(raw_root: Path) -> list[Path]:
    """Return likely directories containing WSI files, in priority order."""
    roots: list[Path] = []
    seen: set[Path] = set()
    for name in _CONVENTIONAL_SLIDE_DIRS:
        candidate = raw_root / name
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(candidate)
    if not roots:
        roots.append(raw_root)
    return roots


def _find_label_sources(raw_root: Path) -> list[Path]:
    """Find slide-label tables, including PANDA and SciDB layouts."""
    sources: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        if not path.is_file():
            return
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        sources.append(path)

    for name in _CONVENTIONAL_LABEL_FILES:
        direct = raw_root / name
        _add(direct)
    for name in _CONVENTIONAL_LABEL_FILES:
        matches = sorted(p for p in raw_root.rglob(name) if p.is_file())
        for match in matches:
            _add(match)
    for pattern in _LABEL_FILE_GLOBS:
        matches = sorted(p for p in raw_root.rglob(pattern) if p.is_file())
        for match in matches:
            _add(match)
    return sources


def _read_table(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
        return list(csv.DictReader(fh, dialect=dialect))


def _first_value(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    by_lower = {str(k or "").strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        value = by_lower.get(alias.lower())
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def _first_value_with_column(
    row: dict[str, str],
    aliases: tuple[str, ...],
) -> tuple[str, str]:
    by_lower = {
        str(k or "").strip().lower(): (str(k or "").strip(), v)
        for k, v in row.items()
    }
    for alias in aliases:
        hit = by_lower.get(alias.lower())
        if hit is None:
            continue
        column, value = hit
        if value is not None and str(value).strip() != "":
            return str(value).strip(), column or alias
    return "", ""


def _canonical_slide_id(raw_value: str, slide_ids: set[str]) -> str:
    """Map label-table IDs to slide stems used by feature extraction."""
    value = (raw_value or "").strip()
    if not value:
        return ""
    candidates = [value, Path(value).stem]
    # Some tables store image ids without extension while files carry .tiff.
    for candidate in candidates:
        if candidate in slide_ids:
            return candidate
    lower_to_slide = {sid.lower(): sid for sid in slide_ids}
    for candidate in candidates:
        hit = lower_to_slide.get(candidate.lower())
        if hit:
            return hit
    return ""


def _standardize_labels(
    labels_srcs: list[Path],
    labels_dest: Path,
    *,
    ordered_slide_ids: list[str],
) -> tuple[int, str]:
    """Write labels_dest as slide_id,label and return count + source column."""
    slide_ids = set(ordered_slide_ids)
    label_map: dict[str, str] = {}
    label_column = ""
    for labels_src in labels_srcs:
        try:
            rows = _read_table(labels_src)
        except OSError:
            continue
        for row in rows:
            slide = _canonical_slide_id(
                _first_value(row, _SLIDE_ID_COLUMNS),
                slide_ids,
            )
            label, column = _first_value_with_column(row, _LABEL_COLUMNS)
            if slide and label and slide not in label_map:
                label_map[slide] = label
                if column and not label_column:
                    label_column = column

    labels_dest.parent.mkdir(parents=True, exist_ok=True)
    with labels_dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["slide_id", "label"])
        for slide_id in ordered_slide_ids:
            if slide_id in label_map:
                writer.writerow([slide_id, label_map[slide_id]])
    return len(label_map), label_column


def _derive_labels_from_prefixed_slide_ids(
    labels_dest: Path,
    *,
    ordered_slide_ids: list[str],
) -> tuple[int, str]:
    """Derive labels from slide IDs like ``LUAD__TCGA-...``.

    Explicit merged cohorts such as TCGA-NSCLC often encode the class label
    in symlink/feature filenames even when no separate labels.csv is present.
    This keeps the user-specified folder as the dataset instead of forcing a
    registry expansion to its component cohorts.
    """
    label_map: dict[str, str] = {}
    for slide_id in ordered_slide_ids:
        prefix, sep, _rest = slide_id.partition("__")
        label = prefix.strip()
        if not sep or not label:
            continue
        label_map[slide_id] = label

    if not label_map:
        return 0, ""

    labels_dest.parent.mkdir(parents=True, exist_ok=True)
    with labels_dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["slide_id", "label"])
        for slide_id in ordered_slide_ids:
            label = label_map.get(slide_id)
            if label:
                writer.writerow([slide_id, label])
    return len(label_map), "slide_id_prefix"


class MILClassificationNormalizer:
    name = "mil_classification"
    supported_task_types = {"mil_classification"}

    def supports(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    def prepare(self, raw_root: Path, prepared_root: Path) -> dict[str, Any]:
        raw_root = Path(raw_root)
        prepared_root = Path(prepared_root)
        wsi_dir = prepared_root / "WSIs"
        wsi_dir.mkdir(parents=True, exist_ok=True)

        slide_ids: list[str] = []
        seen_sources: set[Path] = set()
        for src_dir in _slide_sources(raw_root):
            for src in sorted(src_dir.rglob("*")):
                if not src.is_file():
                    continue
                if src.suffix.lower() not in _WSI_EXTS:
                    continue
                resolved = src.resolve()
                if resolved in seen_sources:
                    continue
                seen_sources.add(resolved)
                dest = wsi_dir / src.name
                if not dest.exists():
                    try:
                        os.symlink(resolved, dest)
                    except OSError:
                        shutil.copy2(src, dest)
                slide_ids.append(src.stem)

        if not slide_ids:
            raise NormalizerError("no_slides")

        labels_dest = prepared_root / "labels.csv"
        label_sources = _find_label_sources(raw_root)
        n_labeled, label_column = _standardize_labels(
            label_sources,
            labels_dest,
            ordered_slide_ids=slide_ids,
        )
        if n_labeled == 0:
            n_labeled, label_column = _derive_labels_from_prefixed_slide_ids(
                labels_dest,
                ordered_slide_ids=slide_ids,
            )
        if label_sources and n_labeled == 0:
            logger.info(
                "MIL normalizer: label tables %s had no rows matching %d slides",
                label_sources,
                len(slide_ids),
            )

        contract: dict[str, Any] = {
            "task_type": "mil_classification",
            "wsi_dir": str(wsi_dir),
            "labels_file": str(labels_dest),
            "requires_feature_extraction": True,
            "data_mounts": {str(prepared_root): "/data"},
            "n_slides": len(slide_ids),
            "n_labeled": n_labeled,
        }
        if label_column:
            contract["label_column"] = label_column

        # Plan-2026-04-30 data-readiness Task 4: when the labels file has
        # actual rows, deterministically generate splits.json so a
        # downstream MIL run has the splits contract it needs without
        # waiting on Task 4's readiness-side fallback. We don't fail if
        # generation can't proceed (e.g. unlabeled / too-few-slides) —
        # readiness will surface ``missing: splits_file`` in that case.
        try:
            from ..wsi_splits import build_classification_splits_from_labels

            splits_dest = prepared_root / "splits.json"
            build_classification_splits_from_labels(labels_dest, splits_dest)
            contract["splits_file"] = str(splits_dest)
        except (ValueError, OSError) as e:
            logger.info(
                "MIL normalizer: skipped splits.json generation (%s)", e,
            )

        return contract
