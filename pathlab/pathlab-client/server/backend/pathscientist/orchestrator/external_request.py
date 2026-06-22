"""LLM-first natural-language external validation inference.

This module does not use keyword heuristics to decide whether external
validation was requested. The LLM supplies that semantic decision; this module
only validates and normalizes the structured response into PathScientist's
``external_test_contract`` shape.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..structured_output import extract_json
from .external_contract import normalize_external_test_contract, normalize_dataset_role

logger = logging.getLogger(__name__)

_CONF_RANK = {"": 0, "low": 1, "medium": 2, "high": 3}
_FEATURE_EXTS = {".pt", ".pth"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
_MASK_EXTS = _IMAGE_EXTS | {".npy", ".pt", ".pth"}
_WSI_EXTS = {".svs", ".svslide", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn", ".bif", ".vsi", ".vms", ".vmu", ".kfb", ".sdpc", ".tmap", ".qptiff"}


@dataclass
class ExternalRequestInference:
    requested: bool = False
    enabled: bool = False
    confidence: str = ""
    status: str = "not_requested"
    reason: str = ""
    contract: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    training_data: dict[str, Any] = field(default_factory=dict)
    external_data: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    source: str = "llm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _norm_lower(value: Any) -> str:
    return _norm(value).lower().replace("-", "_")


def _confidence(value: Any) -> str:
    conf = _norm_lower(value)
    return conf if conf in _CONF_RANK else ""


def _conf_at_least(confidence: str, minimum: str = "medium") -> bool:
    return _CONF_RANK.get(confidence, 0) >= _CONF_RANK[minimum]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _norm_lower(value)
    return text in {"1", "true", "yes", "y"}


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _norm(item)
        if text:
            out.append(text)
    return out


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_task_type(
    value: Any,
    *,
    selected_skill: str = "",
    task_profile: dict | None = None,
) -> str:
    task = _norm_lower(value)
    aliases = {
        "classification": "mil_classification",
        "wsi_classification": "mil_classification",
        "slide_classification": "mil_classification",
        "mil": "mil_classification",
        "mil_classification": "mil_classification",
        "patch": "patch_classification",
        "patch_classification": "patch_classification",
        "image_classification": "patch_classification",
        "survival": "survival",
        "survival_analysis": "survival",
        "segmentation": "segmentation",
        "patch_segmentation": "segmentation",
    }
    if task in aliases:
        return aliases[task]
    skill = _norm_lower(selected_skill)
    if skill in aliases:
        return aliases[skill]
    profile_task = _norm_lower((task_profile or {}).get("task_type"))
    if profile_task in aliases:
        return aliases[profile_task]
    return ""


def _build_prompt(
    *,
    question: str,
    selected_skill: str,
    task_profile: dict | None,
    data_mounts: dict[str, str] | None,
) -> str:
    known_paths = list((data_mounts or {}).keys())
    return f"""You decide whether a PathScientist user request asks for EXTERNAL validation.
Return ONLY JSON. Do not decide by keyword matching; decide the semantic role
of each dataset/cohort/path in the user's request.

Rules:
- external_validation_requested=true only when the user wants evaluation on an
  independent dataset/cohort/site/source after training.
- A normal train/val/test split inside one dataset is not external validation.
- Preserve dataset names exactly as the user wrote them. Do not normalize NSCLC
  to TCGA-LUNG or invent dataset names.
- If an external dataset is requested but no external path is given, still set
  external_validation_requested=true and list missing requirements.
- Confidence must be high, medium, or low.

Schema:
{{
  "external_validation_requested": true,
  "confidence": "high|medium|low",
  "reason": "",
  "datasets": [
    {{"role": "internal", "paths": [], "dataset_name": ""}},
    {{"role": "external", "paths": [], "dataset_name": "", "task_type": ""}}
  ],
  "training_data": {{"paths": [], "dataset_name": ""}},
  "external_data": {{"paths": [], "dataset_name": "", "role": "external_validation"}},
  "external_task_type": "mil_classification|patch_classification|survival|segmentation",
  "missing": []
}}

User request:
{question}

Selected skill: {selected_skill}
Task profile: {task_profile or {}}
Known existing local paths from the request/config: {known_paths}
"""


def _parse_response(raw_text: str) -> dict[str, Any] | None:
    if not (raw_text or "").strip():
        return None
    try:
        data = extract_json(raw_text or "")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _first_dataset_by_role(data: dict[str, Any], role: str) -> dict[str, Any]:
    datasets = data.get("datasets")
    if not isinstance(datasets, list):
        return {}
    for item in datasets:
        if not isinstance(item, dict):
            continue
        if normalize_dataset_role(item.get("role") or item.get("data_role")) == role:
            return dict(item)
    return {}


def _path_with_aliases(path_text: str) -> Path | None:
    text = _norm(path_text)
    if not text:
        return None
    path = Path(text)
    try:
        if path.exists():
            return path
    except OSError:
        return None
    try:
        from ..runtime.path_aliases import KNOWN_PREFIX_ALIASES

        for bad, good in KNOWN_PREFIX_ALIASES.items():
            if text.startswith(bad):
                candidate = Path(good + text[len(bad):])
                if candidate.exists():
                    return candidate
    except Exception:
        pass
    return None


def _containerize_path(path: Path, data_mounts: dict[str, str] | None) -> str:
    path_str = str(path)
    for host, container in (data_mounts or {}).items():
        host_path = Path(str(host))
        try:
            rel = path.relative_to(host_path)
        except ValueError:
            continue
        container_root = str(container).rstrip("/")
        return container_root if str(rel) == "." else f"{container_root}/{rel.as_posix()}"
    return path_str


def _containerize_path_text(path_text: str, data_mounts: dict[str, str] | None) -> str:
    text = _norm(path_text)
    if not text:
        return ""
    existing = _path_with_aliases(text)
    if existing is not None:
        return _containerize_path(existing, data_mounts)
    for host, container in (data_mounts or {}).items():
        host_text = str(host).rstrip("/")
        if text == host_text:
            return str(container).rstrip("/")
        if text.startswith(host_text + "/"):
            suffix = text[len(host_text):].lstrip("/")
            return f"{str(container).rstrip('/')}/{suffix}"
    return text


def _contract_dataset_data(
    data: dict[str, Any],
    *,
    data_mounts: dict[str, str] | None,
) -> dict[str, Any]:
    if not data:
        return {}
    normalized = dict(data)
    paths = [
        mapped
        for path in _as_list(normalized.get("paths"))
        if (mapped := _containerize_path_text(path, data_mounts))
    ]
    if paths:
        normalized["paths"] = paths
    return normalized


def _contains_ext(root: Path, exts: set[str]) -> bool:
    if root.is_file():
        return root.suffix.lower() in exts
    if not root.is_dir():
        return False
    try:
        return any(p.is_file() and p.suffix.lower() in exts for p in root.rglob("*"))
    except OSError:
        return False


def _maybe_set_path(
    contract: dict[str, str],
    key: str,
    path: Path,
    data_mounts: dict[str, str] | None,
) -> None:
    if key not in contract:
        contract[key] = _containerize_path(path, data_mounts)


def _mark_external_features_ready(contract: dict[str, str]) -> None:
    contract["external_features_ready"] = "true"


def _feature_leaf_dirs(root: Path) -> list[Path]:
    """Return feature directories that contain tensors directly.

    PathLab uploads keep global cache tensors under
    ``features/<extractor>/<params_hash>/*.pt`` while older prepared datasets
    may use flat ``features/*.pt`` or ``pt_files/<extractor>/*.pt``.
    """
    if not root.is_dir():
        return []
    leaves: list[Path] = []
    if _contains_ext(root, _FEATURE_EXTS):
        try:
            if any(p.is_file() and p.suffix.lower() in _FEATURE_EXTS for p in root.iterdir()):
                leaves.append(root)
        except OSError:
            return leaves
    try:
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_dir() or ".locks" in candidate.parts:
                continue
            if any(
                p.is_file() and p.suffix.lower() in _FEATURE_EXTS
                for p in candidate.iterdir()
            ):
                leaves.append(candidate)
    except OSError:
        pass
    return leaves


def _choose_feature_leaf(root: Path, *, preferred_extractor: str = "") -> Path | None:
    leaves = _feature_leaf_dirs(root)
    preferred = _norm_lower(preferred_extractor)
    if preferred:
        preferred_leaves = [
            leaf
            for leaf in leaves
            if leaf.name.lower() == preferred
            or any(parent.name.lower() == preferred for parent in leaf.parents)
        ]
        if preferred_leaves:
            return preferred_leaves[0]
    return leaves[0] if leaves else None


def _discover_pathlab_uploads_layout(
    root: Path,
    contract: dict[str, str],
    data_mounts: dict[str, str] | None,
    *,
    preferred_extractor: str = "",
) -> None:
    """Populate contract paths for a PathLab uploads repository root."""
    markers = (
        root / "wsi_files",
        root / "features",
        root / "coordinates",
        root / "training",
        root / "metadata",
        root / "ai_results",
        root / "models",
    )
    if not root.is_dir() or not any(path.exists() for path in markers):
        return

    contract.setdefault("external_data_layout", "pathlab_uploads")
    _maybe_set_path(contract, "external_pathlab_uploads_dir", root, data_mounts)

    wsi_files = root / "wsi_files"
    if wsi_files.is_dir():
        _maybe_set_path(contract, "external_pathlab_wsi_files_dir", wsi_files, data_mounts)
        if _contains_ext(wsi_files, _WSI_EXTS):
            _maybe_set_path(contract, "external_wsi_dir", wsi_files, data_mounts)

    features_root = root / "features"
    if features_root.is_dir():
        _maybe_set_path(
            contract,
            "external_pathlab_global_features_dir",
            features_root,
            data_mounts,
        )
        if leaf := _choose_feature_leaf(features_root, preferred_extractor=preferred_extractor):
            _maybe_set_path(contract, "external_features_dir", leaf, data_mounts)
            _mark_external_features_ready(contract)

    training = root / "training"
    if training.is_dir():
        _maybe_set_path(contract, "external_pathlab_training_dir", training, data_mounts)
        if "external_features_dir" not in contract:
            for candidate in sorted(training.glob("*/features")):
                if candidate.is_dir() and (leaf := _choose_feature_leaf(candidate, preferred_extractor=preferred_extractor)):
                    _maybe_set_path(contract, "external_features_dir", leaf, data_mounts)
                    _mark_external_features_ready(contract)
                    break

    for key, dirname in (
        ("external_pathlab_coordinates_dir", "coordinates"),
        ("external_pathlab_metadata_dir", "metadata"),
        ("external_pathlab_ai_results_dir", "ai_results"),
        ("external_pathlab_models_dir", "models"),
        ("external_pathlab_masks_dir", "masks"),
        ("external_pathlab_progress_dir", "progress"),
        ("external_pathlab_logs_dir", "logs"),
    ):
        path = root / dirname
        if path.is_dir():
            _maybe_set_path(contract, key, path, data_mounts)


def _discover_contract_paths(
    external_paths: list[str],
    *,
    task_type: str,
    data_mounts: dict[str, str] | None,
    preferred_extractor: str = "",
) -> tuple[dict[str, str], list[str]]:
    contract: dict[str, str] = {}
    existing_roots: list[Path] = []
    for path_text in external_paths:
        existing = _path_with_aliases(path_text)
        if existing is not None:
            existing_roots.append(existing)

    if not existing_roots:
        return contract, ["external_data_path"]

    for root in existing_roots:
        if root.is_file():
            name = root.name.lower()
            if name in {"splits.json", "split.json"}:
                _maybe_set_path(contract, "external_splits_file", root, data_mounts)
            elif name in {"labels.json", "label.json"}:
                _maybe_set_path(contract, "external_labels_file", root, data_mounts)
            continue

        splits = root / "splits.json"
        if splits.exists():
            _maybe_set_path(contract, "external_splits_file", splits, data_mounts)

        labels = root / "labels.json"
        if labels.exists():
            _maybe_set_path(contract, "external_labels_file", labels, data_mounts)

        _discover_pathlab_uploads_layout(
            root,
            contract,
            data_mounts,
            preferred_extractor=preferred_extractor,
        )

        features = root / "features"
        images = root / "images"
        wsis = root / "WSIs"
        slides = root / "slides"
        wsi_files = root / "wsi_files"
        masks = root / "masks"
        predictions = root / "predictions"

        if features.is_dir():
            feature_leaf = (
                _choose_feature_leaf(features, preferred_extractor=preferred_extractor)
                if task_type in {"mil_classification", "survival"}
                else None
            )
            feature_leaf = feature_leaf or features
            _maybe_set_path(contract, "external_features_dir", feature_leaf, data_mounts)
            if _contains_ext(feature_leaf, _FEATURE_EXTS):
                _mark_external_features_ready(contract)
        elif root.name.lower() in {"features", "pt_files"} or _contains_ext(root, _FEATURE_EXTS):
            feature_leaf = (
                _choose_feature_leaf(root, preferred_extractor=preferred_extractor)
                if task_type in {"mil_classification", "survival"}
                else None
            )
            feature_leaf = feature_leaf or root
            _maybe_set_path(contract, "external_features_dir", feature_leaf, data_mounts)
            if _contains_ext(feature_leaf, _FEATURE_EXTS):
                _mark_external_features_ready(contract)

        if images.is_dir() and _contains_ext(images, _IMAGE_EXTS):
            _maybe_set_path(contract, "external_images_dir", images, data_mounts)
        elif root.name.lower() in {"images", "patches"} and _contains_ext(root, _IMAGE_EXTS):
            _maybe_set_path(contract, "external_images_dir", root, data_mounts)

        if wsis.is_dir() and _contains_ext(wsis, _WSI_EXTS):
            _maybe_set_path(contract, "external_wsi_dir", wsis, data_mounts)
        elif wsi_files.is_dir() and _contains_ext(wsi_files, _WSI_EXTS):
            _maybe_set_path(contract, "external_wsi_dir", wsi_files, data_mounts)
        elif slides.is_dir() and _contains_ext(slides, _WSI_EXTS):
            _maybe_set_path(contract, "external_wsi_dir", slides, data_mounts)
        elif root.name.lower() in {"wsis", "wsi", "slides", "wsi_files"} and _contains_ext(root, _WSI_EXTS):
            _maybe_set_path(contract, "external_wsi_dir", root, data_mounts)

        if masks.is_dir() and _contains_ext(masks, _MASK_EXTS):
            _maybe_set_path(contract, "external_masks_dir", masks, data_mounts)
        if predictions.is_dir() and _contains_ext(predictions, _MASK_EXTS):
            _maybe_set_path(contract, "external_predictions_dir", predictions, data_mounts)

    missing: list[str] = []
    if (
        task_type in {"mil_classification", "survival"}
        and "external_features_dir" not in contract
        and "external_wsi_dir" not in contract
    ):
        missing.append("external_features_dir")
    if task_type == "patch_classification" and not (
        contract.get("external_features_dir") or contract.get("external_images_dir")
    ):
        missing.append("external_features_dir_or_external_images_dir")
    if task_type == "segmentation":
        if "external_masks_dir" not in contract:
            missing.append("external_masks_dir")
        if "external_predictions_dir" not in contract:
            missing.append("external_predictions_dir")
    if task_type in {"mil_classification", "patch_classification", "survival"} and (
        "external_splits_file" not in contract and "external_labels_file" not in contract
    ):
        missing.append("external_splits_file")
    return contract, missing


def infer_external_request(
    *,
    question: str,
    selected_skill: str = "",
    task_profile: dict | None = None,
    data_mounts: dict[str, str] | None = None,
    llm_caller: Callable[[str], str] | None = None,
    config: Any | None = None,
) -> ExternalRequestInference:
    """Infer an external-test request from natural language using an LLM."""
    if llm_caller is None and config is not None:
        try:
            from ..runtime.metric_parser import build_llm_text_caller

            llm_caller = build_llm_text_caller(config)
        except Exception:
            llm_caller = None
    if llm_caller is None:
        return ExternalRequestInference(status="llm_unavailable", source="llm")

    prompt = _build_prompt(
        question=question,
        selected_skill=selected_skill,
        task_profile=task_profile,
        data_mounts=data_mounts,
    )
    try:
        raw_text = llm_caller(prompt)
    except Exception as exc:
        logger.warning("LLM external request inference failed: %s", exc)
        return ExternalRequestInference(status="llm_error", reason=str(exc), source="llm")

    data = _parse_response(raw_text)
    if data is None:
        return ExternalRequestInference(
            requested=False,
            enabled=False,
            status="parse_error",
            reason="unparseable_llm_response",
            raw={},
            source="llm",
        )
    requested = _as_bool(data.get("external_validation_requested"))
    confidence = _confidence(data.get("confidence"))
    training_data = _as_dict(data.get("training_data")) or _first_dataset_by_role(data, "internal")
    external_data = _as_dict(data.get("external_data")) or _first_dataset_by_role(data, "external")
    if training_data:
        training_data.setdefault("data_role", "internal")
    if external_data:
        external_data.setdefault("data_role", "external")
    reason = _norm(data.get("reason"))
    if not requested:
        return ExternalRequestInference(
            requested=False,
            enabled=False,
            confidence=confidence,
            status="not_requested",
            reason=reason,
            training_data=training_data,
            external_data=external_data,
            raw=data,
            source="llm",
        )

    if not _conf_at_least(confidence):
        return ExternalRequestInference(
            requested=True,
            enabled=False,
            confidence=confidence,
            status="low_confidence",
            reason=reason,
            training_data=training_data,
            external_data=external_data,
            raw=data,
            source="llm",
        )

    task_type = _normalize_task_type(
        data.get("external_task_type"),
        selected_skill=selected_skill,
        task_profile=task_profile,
    )
    if not task_type:
        missing = _as_list(data.get("missing"))
        if "external_task_type" not in missing:
            missing.append("external_task_type")
        return ExternalRequestInference(
            requested=True,
            enabled=False,
            confidence=confidence,
            status="unknown_task_type",
            reason=reason,
            contract={},
            missing=missing,
            training_data=training_data,
            external_data=external_data,
            raw=data,
            source="llm",
        )
    contract: dict[str, Any] = {
        "model_source": "best_run",
        "external_task_type": task_type,
    }
    external_paths = _as_list(external_data.get("paths"))
    preferred_extractor = _norm(
        getattr(config, "planned_feature_extractor", "")
        or getattr(config, "feature_extractor", "")
        or getattr(config, "pathlab_extractor", "")
    )
    discovered, missing = _discover_contract_paths(
        external_paths,
        task_type=task_type,
        data_mounts=data_mounts,
        preferred_extractor=preferred_extractor,
    )
    contract.update(discovered)
    contract = normalize_external_test_contract(
        contract,
        training_data=_contract_dataset_data(training_data, data_mounts=data_mounts),
        external_data=_contract_dataset_data(external_data, data_mounts=data_mounts),
        task_type=task_type,
    )

    response_missing = _as_list(data.get("missing"))
    for item in response_missing:
        if item not in missing:
            missing.append(item)

    return ExternalRequestInference(
        requested=True,
        enabled=True,
        confidence=confidence,
        status="enabled" if not missing else "missing_external_data",
        reason=reason,
        contract=contract,
        missing=missing,
        training_data=training_data,
        external_data=external_data,
        raw=data,
        source="llm",
    )
