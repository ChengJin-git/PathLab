"""Normalize AutoResearch external-test contracts.

The canonical shape is role-tagged ``datasets`` entries. Legacy flat
``external_*`` keys are still emitted because skills/templates consume env vars
derived from those keys.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


_DATASET_TO_FLAT = {
    "wsi_dir": "external_wsi_dir",
    "features_dir": "external_features_dir",
    "images_dir": "external_images_dir",
    "masks_dir": "external_masks_dir",
    "predictions_dir": "external_predictions_dir",
    "splits_file": "external_splits_file",
    "labels_file": "external_labels_file",
    "data_layout": "external_data_layout",
    "pathlab_uploads_dir": "external_pathlab_uploads_dir",
    "pathlab_wsi_files_dir": "external_pathlab_wsi_files_dir",
    "pathlab_global_features_dir": "external_pathlab_global_features_dir",
    "pathlab_training_dir": "external_pathlab_training_dir",
    "pathlab_coordinates_dir": "external_pathlab_coordinates_dir",
    "pathlab_metadata_dir": "external_pathlab_metadata_dir",
    "pathlab_ai_results_dir": "external_pathlab_ai_results_dir",
    "pathlab_models_dir": "external_pathlab_models_dir",
    "pathlab_masks_dir": "external_pathlab_masks_dir",
    "pathlab_progress_dir": "external_pathlab_progress_dir",
    "pathlab_logs_dir": "external_pathlab_logs_dir",
    "data_output_dir": "external_data_output_dir",
    "generated_features_dir": "external_generated_features_dir",
    "extractor_name": "external_extractor_name",
}
_FLAT_TO_DATASET = {flat: key for key, flat in _DATASET_TO_FLAT.items()}
_DATASET_FIELDS = set(_DATASET_TO_FLAT)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item))]


def normalize_dataset_role(value: Any, *, default: str = "") -> str:
    role = _text(value).lower().replace("-", "_")
    if role in {"internal", "train", "training", "source"}:
        return "internal"
    if role in {
        "external",
        "external_test",
        "external_validation",
        "validation",
        "target",
        "independent",
    }:
        return "external"
    return default


def _normalize_dataset(
    data: Mapping[str, Any] | None,
    *,
    default_role: str = "",
    task_type: str = "",
) -> dict[str, Any]:
    raw = dict(data or {})
    role = normalize_dataset_role(
        raw.get("role") or raw.get("data_role"),
        default=default_role,
    )
    out: dict[str, Any] = {}
    if role:
        out["role"] = role
    name = _text(raw.get("dataset_name") or raw.get("name"))
    if name:
        out["dataset_name"] = name
    paths = _list_text(raw.get("paths"))
    if paths:
        out["paths"] = paths
    ds_task = _text(raw.get("task_type") or raw.get("external_task_type") or task_type)
    if ds_task and role == "external":
        out["task_type"] = ds_task

    for field in _DATASET_FIELDS:
        value = _text(raw.get(field))
        if value:
            out[field] = value
    for flat_key, field in _FLAT_TO_DATASET.items():
        value = _text(raw.get(flat_key))
        if value and field not in out:
            out[field] = value
    return out


def _merge_dataset(datasets: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    if not candidate:
        return
    role = candidate.get("role")
    target = None
    if role:
        target = next((item for item in datasets if item.get("role") == role), None)
    if target is None:
        datasets.append(candidate)
        return
    for key, value in candidate.items():
        if key == "paths" and value:
            merged = list(target.get("paths") or [])
            for path in value:
                if path not in merged:
                    merged.append(path)
            target["paths"] = merged
        elif value and key not in target:
            target[key] = value


def _flat_external_dataset(contract: Mapping[str, Any], *, task_type: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {"role": "external"}
    external_task_type = _text(contract.get("external_task_type") or task_type)
    if external_task_type:
        data["task_type"] = external_task_type
    for flat_key, field in _FLAT_TO_DATASET.items():
        value = _text(contract.get(flat_key))
        if value:
            data[field] = value
    return data if len(data) > 1 else {}


def _sync_flat_from_external_dataset(contract: dict[str, Any]) -> None:
    datasets = contract.get("datasets")
    if not isinstance(datasets, list):
        return
    external = next(
        (item for item in datasets if isinstance(item, dict) and item.get("role") == "external"),
        None,
    )
    if not isinstance(external, dict):
        return

    task_type = _text(contract.get("external_task_type") or external.get("task_type"))
    if task_type:
        contract["external_task_type"] = task_type
        external.setdefault("task_type", task_type)
    for field, flat_key in _DATASET_TO_FLAT.items():
        value = _text(external.get(field) or contract.get(flat_key))
        if value:
            contract[flat_key] = value
            external.setdefault(field, value)


def normalize_external_test_contract(
    contract: Mapping[str, Any] | None,
    *,
    training_data: Mapping[str, Any] | None = None,
    external_data: Mapping[str, Any] | None = None,
    task_type: str = "",
) -> dict[str, Any]:
    """Return a contract with canonical datasets and legacy flat aliases."""
    raw = deepcopy(dict(contract or {}))
    result: dict[str, Any] = {k: v for k, v in raw.items() if k != "datasets"}

    datasets: list[dict[str, Any]] = []
    raw_datasets = raw.get("datasets")
    if isinstance(raw_datasets, list):
        for item in raw_datasets:
            if isinstance(item, Mapping):
                _merge_dataset(
                    datasets,
                    _normalize_dataset(item, default_role="", task_type=task_type),
                )

    if training_data:
        _merge_dataset(
            datasets,
            _normalize_dataset(training_data, default_role="internal", task_type=task_type),
        )

    external_candidate = _normalize_dataset(
        external_data,
        default_role="external" if external_data else "",
        task_type=task_type or _text(result.get("external_task_type")),
    )
    flat_candidate = _flat_external_dataset(
        result,
        task_type=task_type or _text(result.get("external_task_type")),
    )
    if external_candidate:
        _merge_dataset(datasets, external_candidate)
    if flat_candidate:
        _merge_dataset(datasets, flat_candidate)

    if datasets:
        result["datasets"] = datasets
    _sync_flat_from_external_dataset(result)
    return result


def update_external_dataset(
    contract: Mapping[str, Any] | None,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply updates to the canonical external dataset and flat aliases."""
    normalized = normalize_external_test_contract(contract)
    datasets = normalized.setdefault("datasets", [])
    external = next(
        (item for item in datasets if isinstance(item, dict) and item.get("role") == "external"),
        None,
    )
    if external is None:
        external = {"role": "external"}
        datasets.append(external)

    for key, value in updates.items():
        text = _text(value)
        if not text:
            continue
        field = _FLAT_TO_DATASET.get(key, key)
        if field in _DATASET_FIELDS or field in {"task_type", "dataset_name"}:
            external[field] = text
        if field in _DATASET_TO_FLAT:
            normalized[_DATASET_TO_FLAT[field]] = text
        elif key.startswith("external_"):
            normalized[key] = text

    _sync_flat_from_external_dataset(normalized)
    return normalized
