"""RunExperiment tool — execute training scripts via SDK workspace."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import Field

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from openhands.sdk.llm import TextContent
from openhands.sdk.tool.schema import Action, Observation
from openhands.sdk.tool.tool import ToolAnnotations, ToolDefinition, ToolExecutor

from ..orchestrator.metrics_utils import is_invalid_synthetic_run
from ..orchestrator.external_contract import normalize_external_test_contract
from ..runtime.data_protocol import (
    data_protocol_change_message,
    extract_data_protocol,
    locked_data_protocol_from_tracker,
)
from ..runtime.sandbox import _dedupe_data_mounts_by_container_target

if TYPE_CHECKING:
    from openhands.sdk.conversation import LocalConversation

    from ..runtime.workspace import Workspace


_FEATURE_EXTRACTION_SCRIPT_MARKERS = (
    "PathLab Feature Extraction Script",
    "def extract(",
    "EXTRACTOR_NAME",
    "WSITiler",
    "features.pt",
)
_FEATURE_EXTS = {".pt", ".pth"}
_PATHLAB_UPLOADS_CHILD_DIRS = {
    "ai_results",
    "coordinates",
    "features",
    "logs",
    "masks",
    "metadata",
    "models",
    "pathscientist",
    "progress",
    "training",
    "wsi_files",
}
_EXTRACTOR_NAME_RE = re.compile(
    r"^\s*EXTRACTOR_NAME\s*=\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
_MIN_RUN_TIMEOUT = 3600
_RUN_TIMEOUT_SECONDS_PER_SAMPLE = 3
_SPLIT_KEYS = ("train", "val", "test")


def _looks_like_feature_extraction_script(script: str) -> bool:
    """Conservatively recognize PathLab feature extraction scripts."""
    return sum(marker in script for marker in _FEATURE_EXTRACTION_SCRIPT_MARKERS) >= 3


def _normalize_script_type(script_path: str, script_type: str = "auto") -> str:
    requested = (script_type or "auto").strip().lower()
    if requested in {"python", "bash"}:
        return requested
    suffix = Path(script_path or "").suffix.lower()
    if suffix in {".sh", ".bash"}:
        return "bash"
    return "python"


def _is_feature_extraction_run(run_kind: str, script_text: str) -> bool:
    if (run_kind or "auto").strip().lower() == "feature_extraction":
        return True
    return _looks_like_feature_extraction_script(script_text or "")


def _is_feature_extraction_run_for_test(run_kind: str, script_text: str) -> bool:
    return _is_feature_extraction_run(run_kind, script_text)


def _contains_feature_tensors(root: Path) -> bool:
    if not root.is_dir():
        return False
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _FEATURE_EXTS:
            return True
    return False


def _script_extractor_name(script_text: str) -> str:
    match = _EXTRACTOR_NAME_RE.search(script_text or "")
    return (match.group(1).strip() if match else "")


def _host_path_for_mounted_container_path(path_text: str, data_mounts: dict | None) -> Path | None:
    """Map a container path back to its host path using ``data_mounts``.

    PathScientist stores mounts as ``{host_path: container_path}``. Feature
    extraction runs inside the sandbox write to the container path, while the
    contract checker runs in the host process. Checking the container path
    directly therefore misses valid artifacts unless we reverse the mapping.
    """
    raw = str(path_text or "").strip()
    if not raw:
        return None

    raw_norm = raw.rstrip("/") or "/"
    for host_path, container_path in sorted(
        (data_mounts or {}).items(),
        key=lambda item: len(str(item[1] or "")),
        reverse=True,
    ):
        host = str(host_path or "").strip()
        container = str(container_path or "").strip()
        if not host or not container:
            continue
        container_norm = container.rstrip("/") or "/"
        if raw_norm == container_norm:
            return Path(host)
        prefix = container_norm.rstrip("/") + "/"
        if raw_norm.startswith(prefix):
            return Path(host) / raw_norm[len(prefix):]
    return None


def _deduped_data_mounts_for_workspace(data_mounts: dict | None, workspace_root: Path) -> dict[str, str]:
    return dict(
        _dedupe_data_mounts_by_container_target(
            data_mounts or {},
            workspace_dir=Path(workspace_root),
        )
    )


def _candidate_data_output_roots(*, config, data_output_dir: str) -> list[Path]:
    roots: list[Path] = []

    def add_root(path_text: str) -> None:
        text = str(path_text or "").strip()
        if not text:
            return
        path = Path(text)
        if path not in roots:
            roots.append(path)
        mapped = _host_path_for_mounted_container_path(
            text,
            getattr(config, "data_mounts", {}) or {},
        )
        if mapped is not None and mapped not in roots:
            roots.append(mapped)

    add_root(data_output_dir)
    add_root((getattr(config, "planned_data_output_dir", "") or "").strip())
    return roots


def _expected_feature_output_dirs(
    *,
    data_output_dir: str,
    script_text: str,
    config=None,
) -> list[Path]:
    """Return persistent feature dirs that satisfy the output contract.

    Prefer the configured extractor name because it is the orchestrator's
    selected extractor. For PathLab uploads repositories, feature tensors land
    under ``features/<extractor>``; standalone fallback datasets
    still use ``pt_files/<extractor>``.
    """
    roots = _candidate_data_output_roots(config=config, data_output_dir=data_output_dir)
    env_names: list[str] = []
    for name in (
        os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", ""),
        os.environ.get("PATHLAB_EXTRACTOR", ""),
    ):
        name = (name or "").strip()
        if name and name not in env_names:
            env_names.append(name)
    if env_names:
        dirs: list[Path] = []
        for root in roots:
            for name in env_names:
                dirs.append(root / "features" / name)
                dirs.append(root / "pt_files" / name)
        return dirs

    script_name = _script_extractor_name(script_text)
    if script_name:
        return [
            path
            for root in roots
            for path in (root / "features" / script_name, root / "pt_files" / script_name)
        ]
    return [path for root in roots for path in (root / "features", root / "pt_files")]



def _feature_output_contract_violation(
    *,
    config,
    data_output_dir: str,
    script_text: str,
    run_kind: str = "auto",
) -> str:
    """Hard-gate feature extraction outputs to the planned durable path.

    When the orchestrator plans a feature_extraction step it sets
    ``config.planned_data_output_dir`` to the dataset/workspace-stable output
    root. A script that exits 0 but writes tensors only under a per-run
    ``OUTPUT_DIR`` is invalid because the next session cannot reuse those
    features. Return an actionable error string on violation, else ``""``.
    """
    planned = (getattr(config, "planned_data_output_dir", "") or "").strip()
    if not planned:
        return ""
    if not _is_feature_extraction_run(run_kind, script_text or ""):
        return ""

    expected_dirs = _expected_feature_output_dirs(
        data_output_dir=data_output_dir,
        script_text=script_text,
        config=config,
    )
    for expected in expected_dirs:
        if _contains_feature_tensors(expected):
            return ""

    expected_text = ", ".join(str(p) for p in expected_dirs)
    return (
        "FEATURE OUTPUT CONTRACT VIOLATION: feature_extraction exited "
        "successfully, but no .pt/.pth feature tensors were found in the "
        f"planned persistent feature directory: {expected_text}. "
        "Feature extraction scripts must save tensors under "
        "DATA_OUTPUT_DIR/features/<extractor>/<slide_id>.pt "
        "for PathLab uploads or DATA_OUTPUT_DIR/pt_files/<extractor>/<slide_id>.pt "
        "for standalone fallback datasets, not only under "
        "OUTPUT_DIR/output/runs/<run_id>. This run is marked failed so the "
        "agent cannot commit non-reusable features."
    )


def _feature_output_contract_violation_for_test(
    *,
    config,
    data_output_dir: str,
    script_text: str,
    run_kind: str = "auto",
) -> str:
    """Test seam for the feature-output hard gate."""
    return _feature_output_contract_violation(
        config=config,
        data_output_dir=data_output_dir,
        script_text=script_text,
        run_kind=run_kind,
    )


def _model_selection_contract_violation(
    *,
    config,
    metrics: dict,
    is_feature_extraction: bool = False,
) -> str:
    """Return an error when training switched the planned MIL model."""
    if is_feature_extraction:
        return ""
    planned = (getattr(config, "planned_mil_model", "") or "").strip()
    if not planned or not metrics:
        return ""
    try:
        from ..domain.mil_selector import normalize_mil_model_name
    except Exception:
        normalize_mil_model_name = lambda value: str(value or "").strip().lower()

    expected = normalize_mil_model_name(planned)
    actual_raw = metrics.get("mil_model", "")
    if not actual_raw and isinstance(metrics.get("model_selection"), dict):
        actual_raw = metrics["model_selection"].get("mil_model", "")
    actual = normalize_mil_model_name(actual_raw)
    if not actual_raw:
        return (
            "MODEL SELECTION CONTRACT VIOLATION: metrics.json is missing "
            f"mil_model. The execution plan expected {expected}; the training "
            "script must honor PATHSCIENTIST_MIL_MODEL and record the actual "
            "MIL architecture in metrics.json."
        )
    if actual != expected:
        return (
            "MODEL SELECTION CONTRACT VIOLATION: training changed the MIL "
            f"architecture; expected {expected}, got {actual}. Keep the "
            "paper-grounded model selection fixed across iterations unless "
            "the user explicitly requests architecture exploration."
        )
    return ""


def _model_selection_contract_violation_for_test(
    *,
    config,
    metrics: dict,
    is_feature_extraction: bool = False,
) -> str:
    return _model_selection_contract_violation(
        config=config,
        metrics=metrics,
        is_feature_extraction=is_feature_extraction,
    )


def _resolve_data_output_dir(
    *,
    config,
    run_dir: Path,
    is_feature_extraction: bool,
) -> str:
    """Pick DATA_OUTPUT_DIR for the script.

    P0-2 fix (2026-05-10): when running a feature_extraction script,
    prefer the orchestrator's planned path (``config.planned_data_output_dir``).
    Pre-fix, this only fell back to the per-run ``output/runs/<run_id>``
    dir, which got purged when the session ended — losing 9 hours of
    extracted features (session_64561aa7962b).

    Order:
      1. ``config.planned_data_output_dir`` (only for feature scripts)
      2. ``data_mounts`` whose container path is ``/output``,
         ``/results``, or ``/data/output`` (legacy convention)
      3. ``run_dir`` (per-run, ephemeral) — final fallback
    """
    if is_feature_extraction:
        planned = (getattr(config, "planned_data_output_dir", "") or "").strip()
        if planned:
            return planned

    data_mounts = getattr(config, "data_mounts", {}) or {}
    for host_path, container_path in data_mounts.items():
        if container_path in ("/output", "/results", "/data/output"):
            return host_path

    return str(run_dir)


def _planned_feature_extraction_env(config) -> dict[str, str]:
    """Return orchestrator-planned feature extraction env vars."""
    env: dict[str, str] = {}
    wsi_dir = (getattr(config, "planned_feature_wsi_dir", "") or "").strip()
    if wsi_dir:
        env["WSI_DIR"] = wsi_dir

    extractor = (getattr(config, "planned_feature_extractor", "") or "").strip()
    if not extractor:
        extractor = (os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", "") or "").strip()
    if extractor:
        env["PATHSCIENTIST_FEATURE_EXTRACTOR"] = extractor
        env["PATHLAB_EXTRACTOR"] = extractor
    return env


def _pathlab_feature_task_id(*, session_id: str, run_id: str) -> str:
    if not session_id or not run_id:
        return ""
    raw = f"pathscientist_features_{session_id}_{run_id}"
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return text[:255].rstrip("._-")


def _planned_model_selection_env(config) -> dict[str, str]:
    """Return orchestrator-planned training model-selection env vars."""
    env: dict[str, str] = {}
    mil_model = (getattr(config, "planned_mil_model", "") or "").strip()
    if not mil_model:
        mil_model = (os.environ.get("PATHSCIENTIST_MIL_MODEL", "") or "").strip()
    if mil_model:
        env["PATHSCIENTIST_MIL_MODEL"] = mil_model
    return env


def _planned_training_data_env(config) -> dict[str, str]:
    """Return orchestrator-planned downstream training data env vars."""
    env: dict[str, str] = {}
    features_dir = (getattr(config, "planned_features_dir", "") or "").strip()
    splits_file = (getattr(config, "planned_splits_file", "") or "").strip()
    extractor = (getattr(config, "planned_feature_extractor", "") or "").strip()
    if features_dir:
        env["FEATURES_DIR"] = features_dir
    if splits_file:
        env["SPLITS_FILE"] = splits_file
    if extractor:
        env["PATHSCIENTIST_FEATURE_EXTRACTOR"] = extractor
        env["PATHLAB_EXTRACTOR"] = extractor
    return env


def _huggingface_token_env(config) -> dict[str, str]:
    token = str(getattr(config, "huggingface_token", "") or "").strip()
    if not token:
        token = os.environ.get("PATHSCIENTIST_HUGGINGFACE_TOKEN", "").strip()
    if not token:
        token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        token = os.environ.get("HUGGING_FACE_HUB_TOKEN", "").strip()
    if not token:
        return {}
    return {
        "HF_TOKEN": token,
        "HUGGING_FACE_HUB_TOKEN": token,
        "PATHSCIENTIST_HUGGINGFACE_TOKEN": token,
    }


def _entry_model_path(entry: dict | None) -> str:
    if not isinstance(entry, dict):
        return ""
    for value in (
        entry.get("model_path"),
        (entry.get("pathlab") or {}).get("model_path")
        if isinstance(entry.get("pathlab"), dict)
        else "",
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _entry_metric_value(entry: dict, primary_metric: str = "auc") -> float:
    for value in (
        entry.get("metric_value"),
        (entry.get("metrics") or {}).get(primary_metric)
        if isinstance(entry.get("metrics"), dict)
        else None,
    ):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return 0.0


def _resolve_best_run_model_path(
    *,
    last_experiment: dict | None = None,
    run_history: list[dict] | None = None,
    primary_metric: str = "auc",
) -> str:
    """Find an existing checkpoint for model_source=best_run external tests.

    Prefer committed metric-best runs. If a small debug run produced a valid
    model but no positive primary metric, fall back to the latest successful
    training checkpoint so requested external validation can still run.
    """
    pending = _entry_model_path(last_experiment)
    if pending and Path(pending).expanduser().exists():
        return pending

    committed_candidates: list[tuple[float, str]] = []
    fallback_candidates: list[tuple[int, float, str]] = []
    for index, entry in enumerate(run_history or []):
        if not isinstance(entry, dict):
            continue
        model_path = _entry_model_path(entry)
        if not model_path or not Path(model_path).expanduser().exists():
            continue
        value = _entry_metric_value(entry, primary_metric)
        if entry.get("committed", False):
            committed_candidates.append((value, model_path))
            continue
        if str(entry.get("run_kind") or "").strip().lower() in {"", "training", "mil_classification"}:
            fallback_candidates.append((index, value, model_path))
    if committed_candidates:
        return max(committed_candidates, key=lambda item: item[0])[1]
    if fallback_candidates:
        return max(fallback_candidates, key=lambda item: (item[0], item[1]))[2]
    return ""



def _durable_model_artifact_root(*, workspace_root: Path, config) -> Path:
    configured = str(getattr(config, "model_artifact_dir", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return workspace_root.parent / "model_artifacts"



def _register_durable_artifact_mount(config, artifact_root: Path) -> None:
    mounts = getattr(config, "data_mounts", None)
    if not isinstance(mounts, dict):
        mounts = {}
        try:
            setattr(config, "data_mounts", mounts)
        except Exception:
            return
    root_text = str(artifact_root)
    mounts.setdefault(root_text, root_text)



def _materialize_durable_model_artifact(
    *,
    config,
    workspace_root: Path,
    session_id: str,
    run_id: str,
    model_path: str | None,
) -> str:
    source_text = str(model_path or "").strip()
    if not source_text or not session_id or not run_id:
        return source_text
    source = Path(source_text).expanduser()
    if not source.is_file():
        return source_text

    artifact_root = _durable_model_artifact_root(
        workspace_root=Path(workspace_root),
        config=config,
    )
    destination = artifact_root / str(session_id) / str(run_id) / source.name
    if source.resolve(strict=False) == destination.resolve(strict=False):
        _register_durable_artifact_mount(config, artifact_root)
        return str(destination)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        _register_durable_artifact_mount(config, artifact_root)
        return str(destination)
    except OSError:
        return source_text



def _materialize_durable_model_artifact_for_test(**kwargs) -> str:
    return _materialize_durable_model_artifact(**kwargs)


def _clean_path(value) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve(strict=False)


def _relative_to(path: Path, root: Path):
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def _configured_pathlab_uploads_dir(config) -> Path | None:
    for attr in ("pathlab_uploads_dir", "uploads_dir"):
        candidate = _clean_path(getattr(config, attr, ""))
        if candidate:
            return candidate

    candidate = _clean_path(os.environ.get("PATHLAB_UPLOADS_DIR", ""))
    if candidate:
        return candidate

    try:
        from backend.common.config import Config

        return Config.get_uploads_dir().expanduser().resolve(strict=False)
    except Exception:
        return None


def _infer_pathlab_uploads_dir(paths: list[Path]) -> Path | None:
    for path in paths:
        parts = path.parts
        for index, part in enumerate(parts):
            if part in _PATHLAB_UPLOADS_CHILD_DIRS and index > 0:
                return Path(*parts[:index]).expanduser().resolve(strict=False)
    return None


def _pathlab_child_path(
    *,
    uploads_dir: Path,
    path: Path | None,
    child_name: str,
) -> Path | None:
    if path is None:
        return None
    rel = _relative_to(path, uploads_dir)
    if rel is None or not rel.parts or rel.parts[0] != child_name:
        return None
    return path


def _pathlab_training_link(
    *,
    uploads_dir: Path,
    paths: list[Path],
) -> tuple[str, Path] | tuple[None, None]:
    for path in paths:
        rel = _relative_to(path, uploads_dir)
        if rel is None or len(rel.parts) < 2 or rel.parts[0] != "training":
            continue
        task_id = str(rel.parts[1]).strip()
        if task_id:
            return task_id, uploads_dir / "training" / task_id
    return None, None


def _pathlab_features_dir(
    *,
    uploads_dir: Path,
    data_output_dir: Path | None,
    artifact_paths: list[Path],
) -> Path | None:
    data_output_features = _pathlab_child_path(
        uploads_dir=uploads_dir,
        path=data_output_dir,
        child_name="features",
    )
    if data_output_features:
        return data_output_features

    for artifact in artifact_paths:
        rel = _relative_to(artifact, uploads_dir)
        if rel is None or len(rel.parts) < 2 or rel.parts[0] != "features":
            continue
        if artifact.suffix.lower() in _FEATURE_EXTS:
            return artifact.parent
        return artifact
    return None


def _pathlab_task_features_link(
    *,
    uploads_dir: Path,
    paths: list[Path],
) -> tuple[str, Path] | tuple[None, None]:
    for path in paths:
        rel = _relative_to(path, uploads_dir)
        if rel is None or len(rel.parts) < 3 or rel.parts[0] != "training":
            continue
        task_id = str(rel.parts[1]).strip()
        if task_id and rel.parts[2] == "features":
            return task_id, uploads_dir / "training" / task_id / "features"
    return None, None


def _pathlab_linkage_for_run(
    *,
    config,
    run_kind: str,
    data_output_dir: str,
    model_path: str | None,
    run_dir: Path,
    data_output_artifacts: list[str],
) -> dict[str, str]:
    """Normalize PathScientist run outputs into PathLab artifact links."""
    data_output_path = _clean_path(data_output_dir)
    model = _clean_path(model_path)
    run = _clean_path(run_dir)
    artifacts = [path for item in data_output_artifacts if (path := _clean_path(item))]
    known_paths = [path for path in [data_output_path, model, run, *artifacts] if path]

    uploads_dir = _configured_pathlab_uploads_dir(config)
    if uploads_dir is None:
        uploads_dir = _infer_pathlab_uploads_dir(known_paths)
    if uploads_dir is None:
        return {}
    if not any(_relative_to(path, uploads_dir) is not None for path in known_paths):
        return {}

    linkage: dict[str, str] = {"uploads_dir": str(uploads_dir)}

    features_dir = _pathlab_features_dir(
        uploads_dir=uploads_dir,
        data_output_dir=data_output_path,
        artifact_paths=artifacts,
    )
    if features_dir:
        linkage["features_dir"] = str(features_dir)

    task_id, training_dir = _pathlab_training_link(
        uploads_dir=uploads_dir,
        paths=[path for path in [model, data_output_path, *artifacts] if path],
    )
    if task_id and training_dir:
        linkage["training_task_id"] = task_id
        linkage["training_dir"] = str(training_dir)

    feature_task_id, task_features_dir = _pathlab_task_features_link(
        uploads_dir=uploads_dir,
        paths=[path for path in [data_output_path, *artifacts] if path],
    )
    if feature_task_id and task_features_dir:
        linkage["feature_training_task_id"] = feature_task_id
        linkage["task_features_dir"] = str(task_features_dir)

    if model:
        linkage["model_path"] = str(model)

    if (uploads_dir / "models").exists():
        linkage["models_dir"] = str(uploads_dir / "models")
    if (uploads_dir / "logs").exists():
        linkage["logs_dir"] = str(uploads_dir / "logs")
    if (uploads_dir / "progress").exists():
        linkage["progress_dir"] = str(uploads_dir / "progress")

    return linkage


def _pathlab_linkage_for_run_for_test(
    *,
    config,
    run_kind: str,
    data_output_dir: str,
    model_path: str | None,
    run_dir: Path,
    data_output_artifacts: list[str],
) -> dict[str, str]:
    return _pathlab_linkage_for_run(
        config=config,
        run_kind=run_kind,
        data_output_dir=data_output_dir,
        model_path=model_path,
        run_dir=run_dir,
        data_output_artifacts=data_output_artifacts,
    )


def _external_test_env(
    config,
    *,
    quick_check: bool = False,
    last_experiment: dict | None = None,
    run_history: list[dict] | None = None,
) -> dict[str, str]:
    """Return orchestrator-provided inputs for external_test scripts."""
    contract = normalize_external_test_contract(
        getattr(config, "external_test_contract", {}) or {}
    )
    env: dict[str, str] = {"PATHSCIENTIST_RUN_KIND": "external_test"}
    if contract.get("datasets"):
        env["PATHSCIENTIST_EXTERNAL_DATASETS"] = json.dumps(contract["datasets"])
    mapping = {
        "external_task_type": "PATHSCIENTIST_EXTERNAL_TASK_TYPE",
        "task_type": "PATHSCIENTIST_EXTERNAL_TASK_TYPE",
        "model_path": "PATHSCIENTIST_MODEL_PATH",
        "model_metadata_path": "PATHSCIENTIST_MODEL_METADATA_PATH",
        "external_wsi_dir": "EXTERNAL_WSI_DIR",
        "external_features_dir": "EXTERNAL_FEATURES_DIR",
        "external_images_dir": "EXTERNAL_IMAGES_DIR",
        "external_masks_dir": "EXTERNAL_MASKS_DIR",
        "external_predictions_dir": "EXTERNAL_PREDICTIONS_DIR",
        "external_splits_file": "EXTERNAL_SPLITS_FILE",
        "external_labels_file": "EXTERNAL_LABELS_FILE",
        "external_pathlab_uploads_dir": "EXTERNAL_PATHLAB_UPLOADS_DIR",
        "external_pathlab_wsi_files_dir": "EXTERNAL_PATHLAB_WSI_FILES_DIR",
        "external_pathlab_global_features_dir": "EXTERNAL_PATHLAB_GLOBAL_FEATURES_DIR",
        "external_pathlab_training_dir": "EXTERNAL_PATHLAB_TRAINING_DIR",
        "external_pathlab_coordinates_dir": "EXTERNAL_PATHLAB_COORDINATES_DIR",
        "external_pathlab_metadata_dir": "EXTERNAL_PATHLAB_METADATA_DIR",
        "external_pathlab_ai_results_dir": "EXTERNAL_PATHLAB_AI_RESULTS_DIR",
        "external_pathlab_models_dir": "EXTERNAL_PATHLAB_MODELS_DIR",
        "external_pathlab_masks_dir": "EXTERNAL_PATHLAB_MASKS_DIR",
        "external_pathlab_progress_dir": "EXTERNAL_PATHLAB_PROGRESS_DIR",
        "external_pathlab_logs_dir": "EXTERNAL_PATHLAB_LOGS_DIR",
    }
    for contract_key, env_key in mapping.items():
        value = str(contract.get(contract_key) or "").strip()
        if (
            env_key == "PATHSCIENTIST_EXTERNAL_TASK_TYPE"
            and value.lower() in {"external_test", "external_validation", "evaluation"}
        ):
            continue
        if env_key in env and env[env_key]:
            continue
        if value:
            env[env_key] = value
    if (
        not env.get("PATHSCIENTIST_MODEL_PATH")
        and str(contract.get("model_source") or "").strip().lower() == "best_run"
    ):
        model_path = _resolve_best_run_model_path(
            last_experiment=last_experiment,
            primary_metric=str(getattr(config, "primary_metric", "auc") or "auc"),
            run_history=run_history
            if run_history is not None
            else getattr(config, "run_history", None),
        )
        if model_path:
            env["PATHSCIENTIST_MODEL_PATH"] = model_path
    if quick_check:
        env["PATHLAB_MAX_EXTERNAL_SAMPLES"] = str(
            contract.get("quick_check_max_samples") or 64
        )
    return env


def _external_test_model_resolution_error(
    config,
    *,
    env_vars: dict[str, str],
    last_experiment: dict | None = None,
) -> str:
    """Return a fail-fast error when external_test lacks a real checkpoint."""
    contract = normalize_external_test_contract(
        getattr(config, "external_test_contract", {}) or {}
    )
    model_source = str(contract.get("model_source") or "").strip().lower()

    model_path = str(env_vars.get("PATHSCIENTIST_MODEL_PATH") or "").strip()
    if not model_path and model_source != "best_run":
        return ""
    if not model_path:
        run_id = str((last_experiment or {}).get("run_id") or "").strip()
        suffix = f" (last run: {run_id})" if run_id else ""
        return (
            "External validation requested model_source='best_run', but the "
            f"best run did not provide a model_path{suffix}. Refusing to run "
            "external_test without a saved checkpoint."
        )

    path = Path(model_path)
    if not path.exists():
        source_text = f"model_source='{model_source or 'explicit'}'"
        return (
            f"External validation requested {source_text}, but the "
            f"resolved model_path does not exist on disk: {model_path}. "
            "Refusing to run external_test without a saved checkpoint."
        )
    if not path.is_file():
        source_text = f"model_source='{model_source or 'explicit'}'"
        return (
            f"External validation requested {source_text}, but the "
            f"resolved model_path is not a file: {model_path}. Refusing to "
            "run external_test without a saved checkpoint."
        )
    return ""


def _build_env_vars_for_test(
    *,
    config,
    run_dir: Path,
    script_text: str,
    quick_check: bool = False,
    run_kind: str = "auto",
    last_experiment: dict | None = None,
) -> dict[str, str]:
    """Test-only seam exposing the env-var assembly logic.

    ``RunExperimentExecutor.__call__`` builds env vars in-line; this
    helper mirrors only the OUTPUT_DIR / DATA_OUTPUT_DIR logic so tests
    can assert path-resolution behavior without instantiating the full
    executor + workspace stack.
    """
    env_vars: dict[str, str] = _huggingface_token_env(config)
    if quick_check:
        env_vars["PATHLAB_QUICK_CHECK"] = "1"
        env_vars["PATHLAB_RUN_MODE"] = "quick_check"
        env_vars["PATHLAB_MAX_EPOCHS"] = "2"
    env_vars["OUTPUT_DIR"] = str(run_dir)
    env_vars["DATA_OUTPUT_DIR"] = _resolve_data_output_dir(
        config=config,
        run_dir=run_dir,
        is_feature_extraction=_is_feature_extraction_run(run_kind, script_text or ""),
    )
    if _is_feature_extraction_run(run_kind, script_text or ""):
        env_vars.update(_planned_feature_extraction_env(config))
    if (run_kind or "").strip().lower() == "external_test":
        env_vars.update(
            _external_test_env(
                config,
                quick_check=quick_check,
                last_experiment=last_experiment,
                run_history=getattr(config, "run_history", None),
            )
        )
    if (run_kind or "").strip().lower() in {"auto", "training"}:
        env_vars.update(_planned_training_data_env(config))
    env_vars.update(_planned_model_selection_env(config))
    return env_vars


def _timeout_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_sample_count_from_payload(payload) -> int:
    if not isinstance(payload, dict):
        return 0

    split_total = 0
    found_split = False
    for key in _SPLIT_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            split_total += len(value)
            found_split = True
        elif isinstance(value, dict):
            split_total += len(value)
            found_split = True
    if found_split:
        return split_total

    nested = payload.get("splits")
    if isinstance(nested, dict):
        nested_total = _split_sample_count_from_payload(nested)
        if nested_total:
            return nested_total

    labels = payload.get("labels")
    if isinstance(labels, dict):
        return len(labels)
    return 0


def _split_sample_count_from_file(path: Path) -> int:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    return _split_sample_count_from_payload(payload)


def _candidate_splits_files(workspace_root: Path, data_mounts: dict) -> list[Path]:
    candidates: list[Path] = []
    for host_path, container_path in (data_mounts or {}).items():
        host = Path(str(host_path))
        container = str(container_path).rstrip("/")
        if container.endswith("/splits.json") or container == "splits.json":
            candidates.append(host)
        elif container in {"/data", "/dataset"}:
            candidates.append(host / "splits.json")

    dataset_root = workspace_root / ".dataset"
    candidates.extend([
        dataset_root / "mil_classification" / "splits.json",
        dataset_root / "splits.json",
    ])
    if dataset_root.is_dir():
        candidates.extend(dataset_root.rglob("splits.json"))

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _infer_split_sample_count(*, workspace_root: Path, data_mounts: dict) -> int:
    counts = [
        _split_sample_count_from_file(candidate)
        for candidate in _candidate_splits_files(workspace_root, data_mounts)
        if candidate.is_file()
    ]
    return max(counts, default=0)


def _resolve_sample_scaled_timeout(
    *,
    configured_timeout: int,
    action_timeout: int,
    workspace_root: Path,
    data_mounts: dict,
) -> int:
    sample_count = _infer_split_sample_count(
        workspace_root=workspace_root,
        data_mounts=data_mounts,
    )
    return max(
        _MIN_RUN_TIMEOUT,
        _timeout_int(configured_timeout, _MIN_RUN_TIMEOUT),
        _timeout_int(action_timeout, 0),
        sample_count * _RUN_TIMEOUT_SECONDS_PER_SAMPLE,
    )


def _resolve_quick_check_timeout(
    *,
    config,
    action_timeout: int,
    workspace_root: Path,
    data_mounts: dict,
    is_feature_extraction: bool,
) -> int:
    timeout = _resolve_sample_scaled_timeout(
        configured_timeout=getattr(
            config, "quick_check_timeout", _MIN_RUN_TIMEOUT
        ),
        action_timeout=action_timeout,
        workspace_root=workspace_root,
        data_mounts=data_mounts,
    )
    if is_feature_extraction:
        feature_timeout = _timeout_int(
            getattr(
                config,
                "feature_extraction_quick_timeout",
                _MIN_RUN_TIMEOUT,
            ),
            _MIN_RUN_TIMEOUT,
        )
        timeout = max(timeout, feature_timeout)
    return timeout


def _resolve_full_run_timeout(
    *,
    config,
    action_timeout: int,
    workspace_root: Path,
    data_mounts: dict,
) -> int:
    return _resolve_sample_scaled_timeout(
        configured_timeout=getattr(
            config, "execution_timeout", _MIN_RUN_TIMEOUT
        ),
        action_timeout=action_timeout,
        workspace_root=workspace_root,
        data_mounts=data_mounts,
    )


def _sanitize_metrics(value):
    """Convert non-standard JSON numeric values to strict JSON-safe values."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {str(k): _sanitize_metrics(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_metrics(v) for v in value]
    return value


def _synthetic_data_violation_text() -> str:
    return (
        "SYNTHETIC DATA RUN: metrics.json marks this experiment as using "
        "synthetic/mock/demo/dummy data. Synthetic fallback is allowed only "
        "for local debugging and must not be reported as a scientific metric. "
        "Fail hard instead: locate or download real data, fix DATA_DIR/"
        "FEATURES_DIR/LABELS paths, or stop with a data-readiness error."
    )


def _write_run_metadata(
    run_dir: Path,
    *,
    run_id: str,
    quick_check: bool,
    run_kind: str,
    script_path: str,
    started_at: str,
) -> None:
    metadata = {
        "run_id": run_id,
        "quick_check": bool(quick_check),
        "run_kind": run_kind,
        "script_path": script_path,
        "started_at": started_at,
    }
    try:
        (run_dir / "run_metadata.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    except OSError:
        pass


class RunExperimentAction(Action):
    script_path: str = Field(
        default="train.py",
        description="Script path relative to workspace root.",
    )
    script_type: Literal["auto", "python", "bash"] = Field(
        default="auto",
        description="How to execute script_path. auto uses the file suffix.",
    )
    run_kind: Literal["auto", "feature_extraction", "training", "external_test"] = Field(
        default="auto",
        description="Semantic run kind for timeout/output-contract handling.",
    )
    script_inputs: list[str] = Field(
        default_factory=list,
        description=(
            "Additional workspace-relative files that are executed or imported "
            "by the launcher and must be included in validation/run hashes."
        ),
    )
    quick_check: bool = Field(
        default=False,
        description="If true, run a 2-epoch validation (fast fail check).",
    )
    timeout: int = Field(
        default=3600,
        description="Execution timeout in seconds.",
    )


class RunExperimentObservation(Observation):
    exit_code: int = Field(description="Process exit code (0 = success).")
    metrics: dict = Field(default_factory=dict, description="Parsed metrics from metrics.json.")
    duration: float = Field(default=0.0, description="Wall-clock seconds.")
    model_path: str | None = Field(default=None, description="Path to saved model, if any.")


class RunExperimentExecutor(ToolExecutor):
    def __init__(self, workspace: Workspace, config, session_id: str = ""):
        self._workspace = workspace
        self._config = config
        self._session_id = session_id

    def _get_iteration_state(self):
        if not self._session_id:
            return None
        try:
            from ..runtime.session_registry import get_session
            return get_session(self._session_id).iteration_state
        except (KeyError, AttributeError):
            return None

    def _resolve_path(self, path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = self._workspace.root / path
        return path.resolve(strict=False)

    def _snapshot_directory(self, directory: str) -> dict[str, tuple[int, int]]:
        abs_dir = self._resolve_path(directory)
        if not abs_dir.is_dir():
            return {}

        snapshot = {}
        for file_path in abs_dir.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            snapshot[str(file_path.resolve(strict=False))] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    def _changed_files_since_snapshot(
        self,
        directory: str,
        before: dict[str, tuple[int, int]],
    ) -> list[str]:
        after = self._snapshot_directory(directory)
        changed = []
        for path, meta in after.items():
            if before.get(path) != meta:
                changed.append(path)
        return sorted(changed)

    def __call__(
        self,
        action: RunExperimentAction,
        conversation: "LocalConversation | None" = None,
    ) -> RunExperimentObservation:
        # Mint a fresh run_id at tool entry and write it to iteration_state
        # BEFORE running the experiment. This makes RunExperimentTool the
        # authoritative producer of ``last_run_id`` — we never rely on
        # ``ensure_run_id()`` idempotent semantics from the caller side, so
        # each call to run_experiment gets a distinct lineage id even if an
        # earlier iteration left a sticky value behind. Assignment happens
        # unconditionally up front so a mid-experiment raise still leaves
        # ``last_run_id`` pointing at this run's id.
        #
        # Canonical shape ``run_[0-9a-f]{8}`` (Fix 5) keeps bare 8-hex
        # conversation UUID / commit shards out of the run_id namespace.
        run_id = f"run_{uuid4().hex[:8]}"

        action_script_path = self._workspace.root / action.script_path
        try:
            script_text = (
                action_script_path.read_text() if action_script_path.exists() else ""
            )
        except OSError:
            script_text = ""
        is_feature_extraction = _is_feature_extraction_run(action.run_kind, script_text)
        semantic_run_kind = (
            "feature_extraction"
            if is_feature_extraction
            else (
                "training"
                if (action.run_kind or "auto").strip().lower() == "auto"
                else (action.run_kind or "training").strip().lower()
            )
        )

        # Enforce iteration policy
        ignores_training_budget = semantic_run_kind in {
            "external_test",
            "feature_extraction",
        }
        iteration_state = self._get_iteration_state()
        if iteration_state:
            iteration_state.last_run_id = run_id
            file_hash = iteration_state.compute_file_hash(
                self._workspace.root,
                script_path=action.script_path,
                script_inputs=action.script_inputs,
            )

            try:
                from ..runtime.iteration_state import PolicyViolation
                if action.quick_check:
                    iteration_state.check_can_quick_check(
                        file_hash,
                        script_path=action.script_path,
                        ignore_budget=ignores_training_budget,
                    )
                else:
                    iteration_state.check_can_full_run(
                        file_hash,
                        script_path=action.script_path,
                        ignore_budget=ignores_training_budget,
                    )
            except PolicyViolation as e:
                return RunExperimentObservation(
                    exit_code=-1, metrics={}, duration=0.0,
                    content=[TextContent(text=f"\u274c {e}")],
                    is_error=True,
                )

        env_vars = _huggingface_token_env(self._config)
        if self._session_id:
            env_vars["PATHSCIENTIST_SESSION_ID"] = self._session_id
            env_vars["PATHSCIENTIST_RUN_ID"] = run_id
        if action.quick_check:
            # Plan T6: stronger quick-check env contract. Templates that
            # honor PATHLAB_QUICK_CHECK should also cap epochs and
            # subsample. Older templates may only check
            # PATHLAB_QUICK_CHECK; stricter caps give them an explicit
            # numeric limit to fall back on.
            env_vars["PATHLAB_QUICK_CHECK"] = "1"
            env_vars["PATHLAB_RUN_MODE"] = "quick_check"
            env_vars["PATHLAB_MAX_EPOCHS"] = "2"
            env_vars["PATHLAB_MAX_TRAIN_SAMPLES"] = "128"
            env_vars["PATHLAB_MAX_VAL_SAMPLES"] = "64"
            env_vars["PATHLAB_MAX_TEST_SAMPLES"] = "64"

        script_type = _normalize_script_type(action.script_path, action.script_type)
        data_mounts = _deduped_data_mounts_for_workspace(
            getattr(self._config, "data_mounts", {}) or {},
            self._workspace.root,
        )
        if isinstance(getattr(self._config, "data_mounts", None), dict):
            self._config.data_mounts = data_mounts
        timeout = (
            _resolve_quick_check_timeout(
                config=self._config,
                action_timeout=action.timeout,
                workspace_root=self._workspace.root,
                data_mounts=data_mounts,
                is_feature_extraction=is_feature_extraction,
            )
            if action.quick_check
            else _resolve_full_run_timeout(
                config=self._config,
                action_timeout=action.timeout,
                workspace_root=self._workspace.root,
                data_mounts=data_mounts,
            )
        )
        if is_feature_extraction:
            default_feature_timeout = 3600 if action.quick_check else 86400
            config_attr = (
                "feature_extraction_quick_timeout"
                if action.quick_check
                else "feature_extraction_timeout"
            )
            feature_timeout = _timeout_int(
                getattr(self._config, config_attr, default_feature_timeout),
                default_feature_timeout,
            )
            timeout = max(_timeout_int(timeout, default_feature_timeout), feature_timeout)

        # Per-run output directory for metrics isolation. ``run_id`` was
        # already minted at tool entry and written to ``iteration_state``.
        output_dir = self._config.resolve_output(self._workspace.root)
        run_dir = output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        env_vars["OUTPUT_DIR"] = str(run_dir)
        started_at = datetime.now(timezone.utc).isoformat()
        _write_run_metadata(
            run_dir,
            run_id=run_id,
            quick_check=action.quick_check,
            run_kind=semantic_run_kind,
            script_path=action.script_path,
            started_at=started_at,
        )

        # DATA_OUTPUT_DIR: stable user-visible output path for actual data
        # (features, model weights, etc). Scripts should write data artifacts
        # here instead of OUTPUT_DIR when they need a predictable location.
        # P0-2 fix (2026-05-10): when running a feature_extraction script,
        # prefer the orchestrator's planned path so features land at a
        # workspace-stable location instead of the per-run dir that gets
        # purged at session end.
        env_vars["DATA_OUTPUT_DIR"] = _resolve_data_output_dir(
            config=self._config,
            run_dir=run_dir,
            is_feature_extraction=is_feature_extraction,
        )
        if is_feature_extraction:
            env_vars.update(_planned_feature_extraction_env(self._config))
            feature_task_id = _pathlab_feature_task_id(
                session_id=self._session_id,
                run_id=run_id,
            )
            if feature_task_id:
                env_vars["PATHSCIENTIST_PATHLAB_TRAINING_TASK_ID"] = feature_task_id
        external_test_last_experiment: dict | None = None
        if semantic_run_kind == "external_test":
            last_experiment = {}
            if self._session_id:
                try:
                    from ..runtime.session_registry import get_session

                    deps = get_session(self._session_id)
                    last_experiment = deps.last_experiment or {}
                    tracker = getattr(deps, "tracker", None)
                    if tracker is not None:
                        self._config.run_history = list(
                            getattr(tracker, "history", []) or []
                        )
                except Exception:
                    last_experiment = {}
            env_vars.update(
                _external_test_env(
                    self._config,
                    quick_check=action.quick_check,
                    last_experiment=last_experiment,
                    run_history=getattr(self._config, "run_history", None),
                )
            )
            resolved_model_path = str(
                env_vars.get("PATHSCIENTIST_MODEL_PATH") or ""
            ).strip()
            if resolved_model_path:
                contract = normalize_external_test_contract(
                    getattr(self._config, "external_test_contract", {}) or {}
                )
                if not contract.get("model_path"):
                    contract["model_path"] = resolved_model_path
                    self._config.external_test_contract = contract
            external_test_last_experiment = last_experiment
        if semantic_run_kind == "training":
            env_vars.update(_planned_training_data_env(self._config))
        env_vars.update(_planned_model_selection_env(self._config))

        if semantic_run_kind == "external_test":
            model_resolution_error = _external_test_model_resolution_error(
                self._config,
                env_vars=env_vars,
                last_experiment=external_test_last_experiment,
            )
            if model_resolution_error:
                return RunExperimentObservation(
                    exit_code=-1,
                    metrics={},
                    duration=0.0,
                    model_path=None,
                    content=[TextContent(text=model_resolution_error)],
                    is_error=True,
                )

        run_dir_abs = self._resolve_path(str(run_dir))
        data_output_dir_abs = self._resolve_path(env_vars["DATA_OUTPUT_DIR"])
        data_output_snapshot = {}
        if data_output_dir_abs != run_dir_abs:
            data_output_snapshot = self._snapshot_directory(env_vars["DATA_OUTPUT_DIR"])

        start = time.time()
        result = self._workspace.run_script(
            script_path=action.script_path,
            env_vars=env_vars,
            timeout=float(timeout),
            data_mounts=data_mounts,
            script_type=script_type,
            session_id=self._session_id,
            run_id=run_id,
            tool_name="run_experiment",
        )
        duration = time.time() - start
        data_output_artifacts = []
        if data_output_dir_abs != run_dir_abs:
            data_output_artifacts = self._changed_files_since_snapshot(
                env_vars["DATA_OUTPUT_DIR"],
                data_output_snapshot,
            )

        # Only read metrics from THIS run's output dir, and only on success
        metrics = {}
        model_path = None
        quick_check_contract_failed = False
        feature_output_contract_failed = False
        feature_output_violation_text = ""
        synthetic_data_contract_failed = False
        synthetic_data_violation_text = ""
        data_protocol_contract_failed = False
        data_protocol_violation_text = ""
        model_selection_contract_failed = False
        model_selection_violation_text = ""
        if result.exit_code == 0:
            feature_output_violation_text = _feature_output_contract_violation(
                config=self._config,
                data_output_dir=env_vars.get("DATA_OUTPUT_DIR", ""),
                script_text=script_text,
                run_kind=action.run_kind,
            )
            feature_output_contract_failed = bool(feature_output_violation_text)

            metrics_path = run_dir / "metrics.json"
            if metrics_path.exists():
                try:
                    loaded_metrics = json.loads(metrics_path.read_text())
                    if isinstance(loaded_metrics, dict):
                        metrics = _sanitize_metrics(loaded_metrics)
                except Exception:
                    pass
            if metrics and is_invalid_synthetic_run(metrics):
                synthetic_data_contract_failed = True
                synthetic_data_violation_text = _synthetic_data_violation_text()
            if metrics:
                model_selection_violation_text = _model_selection_contract_violation(
                    config=self._config,
                    metrics=metrics,
                    is_feature_extraction=is_feature_extraction,
                )
                model_selection_contract_failed = bool(model_selection_violation_text)
            best_model = run_dir / "best_model.pth"
            if best_model.exists():
                model_path = str(best_model)
                if semantic_run_kind == "training":
                    model_path = _materialize_durable_model_artifact(
                        config=self._config,
                        workspace_root=self._workspace.root,
                        session_id=self._session_id,
                        run_id=run_id,
                        model_path=model_path,
                    )

            # Plan T6: enforce the quick-check contract. If the agent
            # ran with quick_check=True but the script wrote
            # ``"quick_check": false`` into metrics.json, the script
            # IGNORED PATHLAB_QUICK_CHECK and ran a full training pass.
            # Refuse to mark this as a passed quick-check (which would
            # unlock a full run for the same code) and surface the
            # violation as a hard error so the agent fixes its template.
            quick_check_contract_failed = (
                action.quick_check
                and bool(metrics)
                and metrics.get("quick_check") is False
            )

            # Data-protocol lock: after the first committed full run, later
            # full runs in the same ratchet ladder must keep n_train/n_val/
            # n_test and split identity fixed. Mark violations as failed here
            # so invalid runs do not pollute output/latest or pending best.
            if metrics and not action.quick_check and self._session_id:
                try:
                    from ..runtime.session_registry import get_session

                    deps = get_session(self._session_id)
                    locked_protocol, locked_run_id, locked_iteration = (
                        locked_data_protocol_from_tracker(deps.tracker)
                    )
                except (KeyError, AttributeError):
                    locked_protocol, locked_run_id, locked_iteration = {}, "", None
                if locked_protocol:
                    current_protocol = extract_data_protocol(metrics)
                    if current_protocol != locked_protocol:
                        data_protocol_contract_failed = True
                        data_protocol_violation_text = (
                            "\n\n"
                            + data_protocol_change_message(
                                locked=locked_protocol,
                                current=current_protocol,
                                run_id=locked_run_id,
                                iteration=locked_iteration,
                                tool_name="run_experiment",
                            )
                        )

            # Copy metrics to output/latest/ so the agent can easily inspect
            # the most recent non-provisional run from the next turn. We do
            # NOT copy quick_check metrics or protocol-violating metrics into
            # "latest" because neither is an authoritative comparable result.
            if (
                metrics
                and not action.quick_check
                and not data_protocol_contract_failed
                and not feature_output_contract_failed
                and not synthetic_data_contract_failed
                and not model_selection_contract_failed
            ):
                latest = output_dir / "latest"
                latest.mkdir(parents=True, exist_ok=True)
                (latest / "metrics.json").write_text(
                    json.dumps(metrics, indent=2, allow_nan=False)
                )

            # Update iteration policy — mark quick check as passed only
            # when the script actually honored the env contract.
            if (
                action.quick_check
                and iteration_state
                and file_hash
                and not quick_check_contract_failed
                and not feature_output_contract_failed
                and not synthetic_data_contract_failed
                and not model_selection_contract_failed
            ):
                iteration_state.mark_quick_check_passed(file_hash)

        # Classify the error type so the ratchet gates (Finding 2/3 of the
        # 2026-04-22 session review) can refuse commits on failed runs even
        # when ``exit_code == 0`` but stderr carries a non-empty error
        # signature. Mirrors ``EvidenceCollector.finalize``'s classification
        # so downstream consumers see the same string the evidence record
        # will eventually carry.
        error_type_str = ""
        if result.exit_code != 0:
            try:
                from ..error_classifier import classify_error
                error_type_str = classify_error(result.stderr or "").value
            except Exception:
                error_type_str = "Unknown"

        # Plan T6 contract violation: agent passed quick_check=True but
        # the script wrote ``"quick_check": false`` in metrics.json. Flip
        # the result to a failure so the ratchet gate refuses to commit
        # this as if it were a clean quick-check, AND so the agent gets
        # an actionable error pointing at PATHLAB_QUICK_CHECK.
        quick_check_violation_text = ""
        if synthetic_data_contract_failed:
            error_type_str = "SyntheticDataRun"
            result_exit_code = -1
        elif (
            action.quick_check
            and bool(metrics)
            and metrics.get("quick_check") is False
        ):
            error_type_str = "QuickCheckContractViolation"
            quick_check_violation_text = (
                "\n\nQUICK CHECK CONTRACT VIOLATION: "
                "the agent invoked run_experiment with quick_check=True, but "
                "the script ignored PATHLAB_QUICK_CHECK and ran a full pass "
                "(metrics.json contains \"quick_check\": false). The script "
                "MUST honor PATHLAB_QUICK_CHECK by capping epochs to "
                "PATHLAB_MAX_EPOCHS (currently 2), subsampling train/val to "
                "PATHLAB_MAX_TRAIN_SAMPLES / PATHLAB_MAX_VAL_SAMPLES, and "
                "writing \"quick_check\": true into metrics.json. Until the "
                "script honors the contract, quick_check WILL NOT unlock "
                "full runs of the same code."
            )
            # Force a -1 exit code on the result so ratchet gates / agent
            # see this as a failure not a success.
            result_exit_code = -1
        elif feature_output_contract_failed:
            error_type_str = "FeatureOutputContractViolation"
            result_exit_code = -1
        elif model_selection_contract_failed:
            error_type_str = "ModelSelectionContractViolation"
            result_exit_code = -1
        elif data_protocol_contract_failed:
            error_type_str = "DataProtocolViolation"
            result_exit_code = -1
        else:
            result_exit_code = result.exit_code

        # Store last experiment output in SessionDeps for evidence collection.
        # ``last_run_id`` was already written at tool entry, so we don't
        # re-assign it here — a single canonical write keeps the invariant
        # "last_run_id tracks the most recent run_experiment call" clear.
        #
        # ``quick_check`` and ``error_type`` are surfaced here so the ratchet
        # tool gates can refuse commits on sanity-check / failed runs without
        # re-classifying stderr themselves (Findings 1–3 of the 2026-04-22
        # session review).
        if self._session_id:
            try:
                from ..runtime.session_registry import get_session
                deps = get_session(self._session_id)
                try:
                    rel_run_dir = str(run_dir.relative_to(self._workspace.root))
                except ValueError:
                    rel_run_dir = str(run_dir)
                pathlab_linkage = _pathlab_linkage_for_run(
                    config=self._config,
                    run_kind=semantic_run_kind,
                    data_output_dir=env_vars.get("DATA_OUTPUT_DIR", ""),
                    model_path=model_path,
                    run_dir=run_dir,
                    data_output_artifacts=data_output_artifacts,
                )
                last_experiment = {
                    "run_id": run_id,
                    "run_dir": rel_run_dir,
                    "exit_code": result_exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "metrics": metrics,
                    "duration": duration,
                    "started_at": started_at,
                    "model_path": model_path,
                    "data_output_dir": env_vars.get("DATA_OUTPUT_DIR", ""),
                    "data_output_artifacts": data_output_artifacts,
                    "quick_check": bool(action.quick_check),
                    "error_type": error_type_str,
                    "run_kind": semantic_run_kind,
                }
                if pathlab_linkage:
                    last_experiment["pathlab"] = pathlab_linkage
                    if pathlab_linkage.get("training_task_id"):
                        last_experiment["pathlab_training_task_id"] = pathlab_linkage[
                            "training_task_id"
                        ]
                deps.last_experiment = last_experiment
            except (KeyError, AttributeError):
                pass

        # Build output text for LLM
        logs = result.stdout + result.stderr
        if len(logs) > 10000:
            logs = logs[:5000] + "\n...[truncated]...\n" + logs[-5000:]

        text = f"Exit code: {result_exit_code}\nDuration: {duration:.1f}s\n"
        if metrics:
            text += f"Metrics: {json.dumps(metrics, indent=2)}\n"
        if result.exit_code != 0:
            text += f"\nError output:\n{logs}"
            # Add structured error analysis with fix hints
            from ..error_classifier import format_error_analysis
            text += format_error_analysis(logs)
        elif logs:
            text += f"\nOutput (last 2000 chars):\n{logs[-2000:]}"
        # Append the quick-check contract violation banner (if any) AFTER
        # the normal output so it's the last thing the agent sees.
        if quick_check_violation_text:
            text += quick_check_violation_text
        if feature_output_violation_text:
            text += "\n\n" + feature_output_violation_text
        if synthetic_data_violation_text:
            text += "\n\n" + synthetic_data_violation_text
        if model_selection_violation_text:
            text += "\n\n" + model_selection_violation_text
        if data_protocol_violation_text:
            text += data_protocol_violation_text

        return RunExperimentObservation(
            exit_code=result_exit_code,
            metrics=metrics,
            duration=duration,
            model_path=model_path,
            content=[TextContent(text=text)],
            is_error=result_exit_code != 0,
        )


class RunExperimentTool(ToolDefinition[RunExperimentAction, RunExperimentObservation]):
    name = "run_experiment"

    @classmethod
    def create(
        cls,
        conv_state=None,
        session_id: str = "",
        workspace=None,
        config=None,
        **params,
    ) -> Sequence[Self]:
        # Resolve from session registry if session_id provided
        if session_id and (workspace is None or config is None):
            from ..runtime.session_registry import get_session
            deps = get_session(session_id)
            workspace = workspace or deps.workspace
            config = config or deps.config
        return [
            cls(
                description=(
                    "Execute a training/experiment script in the workspace. "
                    "Set quick_check=true for a fast 2-epoch validation run before "
                    "the full experiment. Returns exit code, metrics, and logs."
                ),
                action_type=RunExperimentAction,
                observation_type=RunExperimentObservation,
                executor=RunExperimentExecutor(workspace, config, session_id=session_id),
                annotations=ToolAnnotations(
                    title="Run Experiment",
                    destructiveHint=False,
                    openWorldHint=False,
                ),
            )
        ]
