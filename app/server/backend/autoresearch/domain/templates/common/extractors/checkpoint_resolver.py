from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterable

from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.utils import GatedRepoError, HfHubHTTPError


@dataclass(frozen=True)
class ModelFileSpec:
    display_name: str
    local_subdir: str
    repo_id: str
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class ModelDirSpec:
    display_name: str
    local_subdir: str
    repo_id: str
    required_files: tuple[str, ...]
    any_weight_files: tuple[str, ...]
    optional_required_files: tuple[str, ...] = ()


def _bundled_checkpoint_root() -> Path:
    return Path(__file__).resolve().parent / "checkpoints"


def _pathlab_checkpoint_root() -> Path:
    return Path(__file__).resolve().parents[5] / "ai" / "extractors" / "checkpoints"


def checkpoint_root() -> Path:
    return Path(os.environ.get("PATHLAB_CKPT_DIR") or _pathlab_checkpoint_root())


def _candidate_checkpoint_roots() -> list[Path]:
    roots = [checkpoint_root()]
    bundled = _bundled_checkpoint_root()
    if bundled not in roots:
        roots.append(bundled)
    return roots


def _hf_cache_root() -> Path:
    hub_cache = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub_cache:
        return Path(hub_cache)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _repo_cache_dir(repo_id: str) -> Path:
    return _hf_cache_root() / ("models--" + repo_id.replace("/", "--"))


def _snapshot_dirs(repo_id: str) -> list[Path]:
    snapshots = _repo_cache_dir(repo_id) / "snapshots"
    if not snapshots.is_dir():
        return []
    return sorted(
        (p for p in snapshots.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _has_all_files(root: Path, files: Iterable[str]) -> bool:
    return all((root / name).is_file() for name in files)


def _has_any_file(root: Path, files: Iterable[str]) -> bool:
    return any((root / name).is_file() for name in files)


def _offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE") == "1" or os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def _searched_locations(local_dirs: Path | Iterable[Path], repo_id: str) -> list[str]:
    if isinstance(local_dirs, Path):
        dirs = [local_dirs]
    else:
        dirs = list(local_dirs)
    return [*(str(path) for path in dirs), *map(str, _snapshot_dirs(repo_id))]


def _download_failure_message(display_name: str, exc: Exception) -> str:
    if isinstance(exc, GatedRepoError):
        return (
            f"{display_name} checkpoint is gated on Hugging Face. "
            "Request access to the repo and pass a valid HF token, or place "
            "the checkpoint under PATHLAB_CKPT_DIR."
        )
    if isinstance(exc, HfHubHTTPError):
        return f"{display_name} checkpoint download failed: {exc}"
    return f"{display_name} checkpoint download failed: {type(exc).__name__}: {exc}"


def resolve_model_file(
    spec: ModelFileSpec,
    *,
    token: str = "",
    allow_download: bool = True,
) -> Path:
    local_dirs = [root / spec.local_subdir for root in _candidate_checkpoint_roots()]
    for local_dir in local_dirs:
        for filename in spec.filenames:
            candidate = local_dir / filename
            if candidate.is_file():
                return candidate

    for snapshot in _snapshot_dirs(spec.repo_id):
        for filename in spec.filenames:
            candidate = snapshot / filename
            if candidate.is_file():
                return candidate

    if allow_download and not _offline():
        local_dir = local_dirs[0]
        local_dir.mkdir(parents=True, exist_ok=True)
        try:
            return Path(
                hf_hub_download(
                    repo_id=spec.repo_id,
                    filename=spec.filenames[0],
                    local_dir=local_dir,
                    token=token or None,
                )
            )
        except Exception as exc:
            searched = _searched_locations(local_dirs, spec.repo_id)
            raise FileNotFoundError(
                f"{spec.display_name} checkpoint not found locally and could not be downloaded. "
                f"Expected one of {spec.filenames}; searched: {searched}. "
                + _download_failure_message(spec.display_name, exc)
            ) from exc

    searched = _searched_locations(local_dirs, spec.repo_id)
    raise FileNotFoundError(
        f"{spec.display_name} checkpoint not found. "
        f"Expected one of {spec.filenames}; searched: {searched}"
    )


def resolve_model_dir(
    spec: ModelDirSpec,
    *,
    token: str = "",
    allow_download: bool = True,
) -> Path:
    local_dirs = [root / spec.local_subdir for root in _candidate_checkpoint_roots()]
    required = spec.required_files + spec.optional_required_files
    for local_dir in local_dirs:
        if (
            local_dir.is_dir()
            and _has_all_files(local_dir, required)
            and _has_any_file(local_dir, spec.any_weight_files)
        ):
            return local_dir

    for snapshot in _snapshot_dirs(spec.repo_id):
        if (
            _has_all_files(snapshot, required)
            and _has_any_file(snapshot, spec.any_weight_files)
        ):
            return snapshot

    if allow_download and not _offline():
        local_dir = local_dirs[0]
        local_dir.mkdir(parents=True, exist_ok=True)
        try:
            return Path(
                snapshot_download(
                    repo_id=spec.repo_id,
                    local_dir=local_dir,
                    token=token or None,
                )
            )
        except Exception as exc:
            searched = _searched_locations(local_dirs, spec.repo_id)
            raise FileNotFoundError(
                f"{spec.display_name} model directory not found locally and could not be downloaded. "
                f"Required files={required}, weights={spec.any_weight_files}; "
                f"searched: {searched}. "
                + _download_failure_message(spec.display_name, exc)
            ) from exc

    searched = _searched_locations(local_dirs, spec.repo_id)
    raise FileNotFoundError(
        f"{spec.display_name} model directory not found. "
        f"Required files={required}, weights={spec.any_weight_files}; "
        f"searched: {searched}"
    )
