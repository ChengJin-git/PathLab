"""Shared split-generation helpers for export and training task creation."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sklearn.exceptions import NotFittedError

from backend.annotation.coco_utils import (
    extract_coco_wsi_label_sets,
    merge_coco_datasets,
)


def _normalize_annotation_file_key(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    normalized = Path(str(file_name)).name.strip().lower()
    return normalized or None


def _build_segmentation_wsi_lookups(
    wsis: List[Any],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    exact_lookup: Dict[str, str] = {}
    stem_candidates: Dict[str, Set[str]] = {}

    for wsi in wsis:
        candidates = [getattr(wsi, "original_filename", None), getattr(wsi, "wsi_path", None)]
        for candidate in candidates:
            key = _normalize_annotation_file_key(candidate)
            if not key:
                continue
            exact_lookup.setdefault(key, getattr(wsi, "wsi_id"))
            stem_candidates.setdefault(Path(key).stem, set()).add(getattr(wsi, "wsi_id"))

    stem_lookup = {
        stem: next(iter(wsi_ids))
        for stem, wsi_ids in stem_candidates.items()
        if len(wsi_ids) == 1
    }
    return exact_lookup, stem_lookup


def _extract_segmentation_multilabels_from_payloads(
    payloads: List[dict[str, Any]],
    wsis: List[Any],
) -> Tuple[List[str], Dict[str, Set[str]]]:
    merged_coco = merge_coco_datasets(payloads)
    exact_lookup, stem_lookup = _build_segmentation_wsi_lookups(wsis)
    multilabels = extract_coco_wsi_label_sets(merged_coco, exact_lookup, stem_lookup)
    classes = sorted({label for label_set in multilabels.values() for label in label_set})
    return classes, multilabels


async def load_segmentation_multilabels(
    db: Any,
    wsis: List[Any],
) -> Tuple[List[str], Dict[str, Set[str]]]:
    dataset_ids = {getattr(wsi, "dataset_id", None) for wsi in wsis if getattr(wsi, "dataset_id", None)}
    if len(dataset_ids) != 1:
        return [], {}

    from backend.database.repositories.annotation import (  # noqa: PLC0415
        SegmentationAnnotationRepository,
    )

    dataset_id = next(iter(dataset_ids))
    records = await SegmentationAnnotationRepository.get_all_by_dataset(
        db,
        dataset_id,
        include_drafts=False,
    )
    if not records:
        return [], {}

    dataset_level_record = next(
        (record for record in records if record.annotation_id == f"label_{dataset_id}"),
        None,
    )
    payloads = (
        [dataset_level_record.annotations]
        if dataset_level_record
        else [record.annotations for record in records if isinstance(record.annotations, dict)]
    )
    if not payloads:
        return [], {}

    return await asyncio.to_thread(
        _extract_segmentation_multilabels_from_payloads,
        payloads,
        wsis,
    )


def build_survival_event_labels(wsis: List[Any], case_level: bool) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for wsi in wsis:
        event_time = getattr(wsi, "event_time", None)
        event_status = getattr(wsi, "event_status", None)
        if event_time is None or event_status is None:
            continue
        sample_id = getattr(wsi, "case_id", None) if case_level and getattr(wsi, "case_id", None) else getattr(wsi, "wsi_id")
        labels.setdefault(sample_id, str(int(event_status)))
    return labels


def is_split_stratification_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, (ValueError, NotFittedError)) and any(
        token in message
        for token in (
            "least populated class",
            "n_splits",
            "members in each class",
            "test_size",
            "train_size",
            "number of groups",
            "cannot be greater than the number of members",
        )
    )


def generate_split_assignments(
    wsis: List[Any],
    *,
    aggregation_level: str,
    task_type: str,
    split_config: Dict[str, Any],
    segmentation_multilabels: Optional[Dict[str, Sequence[str] | Set[str]]] = None,
) -> Tuple[Dict[str, str], bool]:
    """Generate split assignments using the exact same logic for export and training."""
    from backend.ai.utils.data_splitter import (  # noqa: PLC0415
        split_case_dataset,
        split_wsi_dataset,
    )

    if not wsis:
        return {}, False

    strategy = split_config.get("strategy", "random")
    if strategy == "manual":
        return split_config.get("manual_splits", {}) or {}, False

    stratified = bool(split_config.get("stratified", True))
    splitter_kwargs: Dict[str, Any] = {
        "strategy": strategy,
        "seed": int(split_config.get("seed", 42)),
    }
    if strategy == "k_fold":
        splitter_kwargs["n_splits"] = int(split_config.get("n_splits", 5))
    else:
        splitter_kwargs["ratios"] = split_config.get(
            "ratios",
            {"train": 0.7, "val": 0.1, "test": 0.2},
        )

    is_case_level = aggregation_level == "case"
    is_survival = task_type == "survival"
    is_segmentation = task_type == "segmentation"
    use_multilabels = (
        dict(segmentation_multilabels or {}) if is_segmentation and stratified else None
    )
    survival_labels = (
        build_survival_event_labels(wsis, case_level=is_case_level)
        if is_survival and stratified
        else {}
    )
    wsi_ids = [getattr(wsi, "wsi_id") for wsi in wsis]

    if is_case_level:
        case_id_map: Dict[str, str] = {}
        case_labels: Dict[str, str] = {}
        for wsi in wsis:
            wsi_id = getattr(wsi, "wsi_id")
            case_id = getattr(wsi, "case_id", None) or wsi_id
            case_id_map[wsi_id] = case_id

            label_val = None
            if stratified and not is_segmentation:
                label_val = survival_labels.get(case_id) if is_survival else getattr(wsi, "label", None)
            if label_val and case_id not in case_labels:
                case_labels[case_id] = label_val

        try:
            return (
                split_case_dataset(
                    wsi_ids=wsi_ids,
                    case_id_map=case_id_map,
                    labels=case_labels if stratified and not is_segmentation else None,
                    multilabels=use_multilabels,
                    **splitter_kwargs,
                ),
                False,
            )
        except Exception as exc:
            if (case_labels or use_multilabels) and is_split_stratification_error(exc):
                return (
                    split_case_dataset(
                        wsi_ids=wsi_ids,
                        case_id_map=case_id_map,
                        labels=None,
                        multilabels=None,
                        **splitter_kwargs,
                    ),
                    True,
                )
            raise

    wsi_labels: Dict[str, str] = {}
    if stratified and not is_segmentation:
        for wsi in wsis:
            wsi_id = getattr(wsi, "wsi_id")
            label_val = survival_labels.get(wsi_id) if is_survival else getattr(wsi, "label", None)
            if label_val:
                wsi_labels[wsi_id] = label_val

    try:
        return (
            split_wsi_dataset(
                wsi_ids=wsi_ids,
                labels=wsi_labels if stratified and not is_segmentation else None,
                multilabels=use_multilabels,
                **splitter_kwargs,
            ),
            False,
        )
    except Exception as exc:
        if (wsi_labels or use_multilabels) and is_split_stratification_error(exc):
            return (
                split_wsi_dataset(
                    wsi_ids=wsi_ids,
                    labels=None,
                    multilabels=None,
                    **splitter_kwargs,
                ),
                True,
            )
        raise