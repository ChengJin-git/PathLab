"""Data readiness preflight for slide-level feature consumers.

Plan-2026-04-30 data-readiness-execution Task 1+: decide whether a
slide-level training task can run as-is (feature tensors + splits already
present), needs feature extraction first (raw WSI + labels), or needs
acquisition / explicit input (missing_data).

The resolver inspects host paths only; runtime/container paths flow
into the execution brief separately. ``DataReadinessResult`` carries
both ``*_host`` and runtime fields so this distinction is explicit.

Tasks 2/3/4/8 extend this module with path resolution, assessment,
split generation hooks, and post-extraction discovery — see the plan.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


FEATURE_EXTS = {".pt", ".pth"}
PATCH_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
WSI_EXTS = {
    ".svs", ".svslide", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn",
    ".bif", ".vsi", ".vms", ".vmu", ".kfb", ".sdpc", ".tmap", ".qptiff",
}
FEATURE_CONSUMER_TASKS = {"mil_classification", "survival_analysis"}
PATCH_CONSUMER_TASKS = {"patch_classification"}


@dataclass(frozen=True)
class DataReadinessResult:
    """Outcome of the slide-level feature-consumer preflight.

    ``status`` is one of:
    - ``"features_ready"``  — feature tensors + valid splits exist; train directly.
    - ``"raw_wsi_ready"``   — raw WSI + labels (+ generable splits) exist; run
                              feature_extraction first, then downstream training.
    - ``"missing_data"``    — neither path satisfied; not terminal until
                              acquisition has been attempted or disabled.
    - ``"not_applicable"``  — task is not a slide-level feature consumer.

    Runtime fields (``features_dir`` / ``splits_file`` / ``wsi_dir`` /
    ``labels_file``) are paths visible inside the execution environment
    (typically container paths like ``/data/features``). ``*_host`` fields
    hold the corresponding absolute host paths used by readiness probing
    and tests. When the path didn't come from a mount, runtime == host.
    """

    status: str
    source: str = ""
    features_dir: str = ""
    splits_file: str = ""
    wsi_dir: str = ""
    labels_file: str = ""
    data_dir: str = ""
    images_dir: str = ""
    features_dir_host: str = ""
    splits_file_host: str = ""
    wsi_dir_host: str = ""
    labels_file_host: str = ""
    data_dir_host: str = ""
    images_dir_host: str = ""
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DataReadinessResult":
        data = data or {}
        return cls(
            status=str(data.get("status", "missing_data")),
            source=str(data.get("source", "")),
            features_dir=str(data.get("features_dir", "")),
            splits_file=str(data.get("splits_file", "")),
            wsi_dir=str(data.get("wsi_dir", "")),
            labels_file=str(data.get("labels_file", "")),
            data_dir=str(data.get("data_dir", "")),
            images_dir=str(data.get("images_dir", "")),
            features_dir_host=str(data.get("features_dir_host", "")),
            splits_file_host=str(data.get("splits_file_host", "")),
            wsi_dir_host=str(data.get("wsi_dir_host", "")),
            labels_file_host=str(data.get("labels_file_host", "")),
            data_dir_host=str(data.get("data_dir_host", "")),
            images_dir_host=str(data.get("images_dir_host", "")),
            missing=list(data.get("missing") or []),
            notes=list(data.get("notes") or []),
        )


def find_generated_features_dir(
    output_root: str | Path,
    *,
    expected_dir: str | Path = "",
) -> Path | None:
    """Plan-2026-04-30 data-readiness Task 8: find the directory that
    feature_extraction wrote ``.pt`` files into.

    Search order:
    1. ``expected_dir`` (the deterministic path the runner pre-baked)
    2. ``expected_dir/*`` for PathLab ``features/<extractor>/<params_hash>``
    3. ``<root>/.dataset/generated_features/pt_files/*``
    4. ``<root>/output/pt_files/*``
    5. ``<root>/output/runs/*/pt_files/*`` (only as a fallback)
    """
    if (
        expected_dir
        and _contains_direct_files_with_ext(expected_dir, FEATURE_EXTS)
        and _feature_cache_is_complete_path(expected_dir)
    ):
        return Path(expected_dir)
    root = Path(output_root)
    candidates: list[Path] = []
    expected = Path(expected_dir) if expected_dir else None
    if expected and expected.is_dir():
        candidates.extend(sorted(p for p in expected.iterdir() if p.is_dir()))
    rooted = root / ".dataset" / "generated_features" / "pt_files"
    if rooted.is_dir():
        candidates.extend(sorted(rooted.glob("*")))
    out_pt = root / "output" / "pt_files"
    if out_pt.is_dir():
        candidates.extend(sorted(out_pt.glob("*")))
    runs_pt = root / "output" / "runs"
    if runs_pt.is_dir():
        for run_dir in sorted(runs_pt.glob("*")):
            sub = run_dir / "pt_files"
            if sub.is_dir():
                candidates.extend(sorted(sub.glob("*")))
    for c in candidates:
        if (
            contains_files_with_ext(c, FEATURE_EXTS)
            and _feature_cache_is_complete_path(c)
        ):
            return c
    return None


def contains_files_with_ext(root: str | Path, exts: set[str]) -> bool:
    """Return True if ``root`` is a directory and contains at least one
    file (recursively) whose suffix is in ``exts`` (case-insensitive)."""
    path = Path(root)
    if not path.is_dir():
        return False
    lowered = {e.lower() for e in exts}
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in lowered:
            return True
    return False


def _contains_direct_files_with_ext(root: str | Path, exts: set[str]) -> bool:
    """Return True when feature files live directly under ``root``.

    MIL trainers load ``features_dir/<slide_id>.pt`` and do not recurse into
    extractor subdirectories, so readiness must return the leaf feature folder.
    """
    path = Path(root)
    if not path.is_dir():
        return False
    lowered = {e.lower() for e in exts}
    try:
        for p in path.iterdir():
            if p.is_file() and p.suffix.lower() in lowered:
                return True
    except OSError:
        return False
    return False


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_extraction_meta_paths(feature_dir: str | Path) -> list[Path]:
    """Return likely metadata locations for a feature tensor directory."""
    path = Path(feature_dir)
    candidates = [
        path / "extraction_meta.json",
        path.parent / "extraction_meta.json",
        path.parent.parent / "extraction_meta.json",
    ]
    out: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


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


def _meta_failures_are_only_no_tissue(meta: dict[str, Any]) -> bool:
    results = meta.get("results")
    if not isinstance(results, dict) or not results:
        return False
    failed = [
        record
        for record in results.values()
        if str((record or {}).get("status") if isinstance(record, dict) else record)
        .strip()
        .lower()
        not in {"success", "cached"}
    ]
    return bool(failed) and all(_record_is_no_tissue(record) for record in failed)


def _meta_low_success_is_explained_by_no_tissue(meta: dict[str, Any]) -> bool:
    results = meta.get("results")
    if not isinstance(results, dict) or not results:
        return False
    actionable = 0
    successful = 0
    for record in results.values():
        if _record_is_no_tissue(record):
            continue
        actionable += 1
        status = (
            str((record or {}).get("status") if isinstance(record, dict) else record)
            .strip()
            .lower()
        )
        if status in {"success", "cached"}:
            successful += 1
    if actionable <= 0:
        return False
    min_success_rate = _coerce_float(meta.get("min_success_rate"))
    if min_success_rate is None:
        min_success_rate = 0.95
    if min_success_rate > 1.0:
        min_success_rate = min_success_rate / 100.0
    return successful / actionable >= min_success_rate


def _feature_cache_is_complete_path(feature_dir: str | Path) -> bool:
    """Reject partial extractor caches when metadata is available.

    Legacy feature folders without ``extraction_meta.json`` remain valid so
    old prepared datasets are not forced through feature extraction again.
    """
    meta_path = next(
        (p for p in _candidate_extraction_meta_paths(feature_dir) if p.is_file()),
        None,
    )
    if meta_path is None:
        return True

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(meta, dict):
        return False

    status = str(meta.get("status") or "").strip().lower()
    no_tissue_explains_failures = (
        _meta_failures_are_only_no_tissue(meta)
        or _meta_low_success_is_explained_by_no_tissue(meta)
    )
    if status and status != "completed" and not no_tissue_explains_failures:
        return False

    min_success_rate = _coerce_float(meta.get("min_success_rate"))
    if min_success_rate is None:
        min_success_rate = 0.95
    if min_success_rate > 1.0:
        min_success_rate = min_success_rate / 100.0

    success_rate = _coerce_float(meta.get("success_rate"))
    if success_rate is None:
        successful = _coerce_float(meta.get("successful"))
        total_wsi = _coerce_float(meta.get("total_wsi"))
        if total_wsi and total_wsi > 0 and successful is not None:
            success_rate = successful / total_wsi

    if (
        success_rate is not None
        and success_rate < min_success_rate
        and not no_tissue_explains_failures
    ):
        return False
    return True


def _preferred_feature_subdir_names(preferred_feature_extractor: str = "") -> list[str]:
    import os

    names = [
        preferred_feature_extractor,
        os.environ.get("PATHSCIENTIST_FEATURE_EXTRACTOR", ""),
        os.environ.get("PATHLAB_EXTRACTOR", ""),
        "virchow2",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = str(name or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _leaf_feature_dir(
    candidate: ResolvedPath,
    *,
    preferred_feature_extractor: str = "",
) -> ResolvedPath | None:
    """Return the directory that should be passed to training.

    Canonical layout stores model-specific tensors in
    ``pt_files/<extractor>/``. If readiness probes ``pt_files/`` itself,
    recurse one level and return the preferred extractor leaf. Legacy flat
    ``features/*.pt`` remains supported.
    """
    if _contains_direct_files_with_ext(candidate.host_path, FEATURE_EXTS):
        strict_preferred = str(preferred_feature_extractor or "").strip().lower()
        if (
            strict_preferred
            and candidate.host_path.parent.name.lower() in {"pt_files", "features"}
            and candidate.host_path.name.lower() != strict_preferred
        ):
            return None
        return candidate

    try:
        children = [
            p for p in candidate.host_path.iterdir()
            if p.is_dir() and _contains_direct_files_with_ext(p, FEATURE_EXTS)
        ]
    except OSError:
        return None
    if not children:
        try:
            nested = [
                p
                for p in candidate.host_path.rglob("*")
                if (
                    p.is_dir()
                    and ".locks" not in p.parts
                    and _contains_direct_files_with_ext(p, FEATURE_EXTS)
                )
            ]
        except OSError:
            return None
        if not nested:
            return None
        strict_preferred = str(preferred_feature_extractor or "").strip().lower()
        if strict_preferred:
            nested = [
                p for p in nested
                if p.name.lower() == strict_preferred
                or any(parent.name.lower() == strict_preferred for parent in p.parents)
            ]
            if not nested:
                return None
        chosen = sorted(nested, key=lambda p: (len(p.parts), str(p).lower()))[0]
        rel = chosen.relative_to(candidate.host_path)
        runtime = candidate.runtime_path
        for part in rel.parts:
            runtime = _runtime_join(runtime, part)
        return ResolvedPath(
            host_path=chosen,
            runtime_path=runtime,
            source=candidate.source,
        )

    by_name = {p.name.lower(): p for p in children}
    strict_preferred = str(preferred_feature_extractor or "").strip().lower()
    if strict_preferred:
        chosen = by_name.get(strict_preferred)
        if chosen is None:
            return None
        return ResolvedPath(
            host_path=chosen,
            runtime_path=_runtime_join(candidate.runtime_path, chosen.name),
            source=candidate.source,
        )

    chosen = None
    for name in _preferred_feature_subdir_names():
        if name in by_name:
            chosen = by_name[name]
            break
    if chosen is None:
        chosen = sorted(children, key=lambda p: p.name.lower())[0]

    return ResolvedPath(
        host_path=chosen,
        runtime_path=_runtime_join(candidate.runtime_path, chosen.name),
        source=candidate.source,
    )


# ---------------------------------------------------------------- T2: paths


@dataclass(frozen=True)
class ResolvedPath:
    """A path probed by the readiness resolver.

    ``host_path`` is what we use to ``Path.exists()`` / count files.
    ``runtime_path`` is what we render into execution briefs (typically
    a container-visible path like ``/data/features``).
    ``source`` is one of ``"mount" | "host" | "unknown"``.
    """

    host_path: Path
    runtime_path: str
    source: str = ""


def resolve_probe_path(
    value: str | Path,
    *,
    data_mounts: dict[str, str] | None = None,
) -> ResolvedPath:
    """Map a path string to a (host, runtime) pair via ``data_mounts``.

    Two directions are honored:

    1. **Container → host**: a path starting with a known container root
       (``/data/features`` under ``data_mounts={host_root: "/data"}``) maps
       to the host file under ``host_root``.
    2. **Host → runtime** (review P1-3): a host path that falls under a
       mounted host root maps to the container runtime path. Without this,
       normalizer-emitted host contracts get rendered into briefs as host
       paths instead of ``/data/...``.

    Container mappings WIN over filesystem existence (``/data/features``
    on the host can't steal a container path that's explicitly mounted).
    Among candidate mounts the longer container prefix wins
    (``"/data/features"`` > ``"/data"``); among candidate host roots the
    longer host prefix wins for the same reason.
    """
    raw = str(value or "").strip()
    if not raw:
        return ResolvedPath(Path(""), "", "unknown")

    mounts = data_mounts or {}

    # 1. Container → host (longest container prefix first).
    for host_root, container_root in sorted(
        mounts.items(),
        key=lambda item: len(str(item[1] or "")),
        reverse=True,
    ):
        container = str(container_root or "").rstrip("/")
        if not container:
            continue
        if raw == container or raw.startswith(container + "/"):
            suffix = raw[len(container):].lstrip("/")
            host = Path(host_root).expanduser()
            if suffix:
                host = host / suffix
            return ResolvedPath(
                host_path=host,
                runtime_path=raw,
                source="mount",
            )

    # 2. Host → runtime (longest host prefix first). Only fires when the
    # input looks like an absolute host path under a mount.
    raw_path = Path(raw).expanduser()
    raw_str = str(raw_path)
    for host_root, container_root in sorted(
        mounts.items(),
        key=lambda item: len(str(item[0] or "")),
        reverse=True,
    ):
        host_str = str(Path(host_root).expanduser()).rstrip("/")
        container = str(container_root or "").rstrip("/")
        if not host_str or not container:
            continue
        if raw_str == host_str or raw_str.startswith(host_str + "/"):
            suffix = raw_str[len(host_str):].lstrip("/")
            runtime = container if not suffix else f"{container}/{suffix}"
            return ResolvedPath(
                host_path=raw_path,
                runtime_path=runtime,
                source="mount",
            )

    # 3. Plain host path (no mount overlap).
    if raw_path.exists():
        return ResolvedPath(raw_path, raw, "host")
    return ResolvedPath(raw_path, raw, "unknown")


@dataclass(frozen=True)
class ReadinessCandidates:
    """Bundle of plausible host-side paths the assessor can probe."""

    features_dirs: list[ResolvedPath] = field(default_factory=list)
    images_dirs: list[ResolvedPath] = field(default_factory=list)
    splits_files: list[ResolvedPath] = field(default_factory=list)
    wsi_dirs: list[ResolvedPath] = field(default_factory=list)
    labels_files: list[ResolvedPath] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


# Conventional subpaths probed under each mounted host root when not
# explicitly named in the prepared contract.
_CONVENTIONAL_FEATURE_DIRS = ("features", "pt_files")
_CONVENTIONAL_IMAGE_DIRS = ("images", "patch_images")
_CONVENTIONAL_WSI_DIRS = (
    "WSIs", "wsis",  # canonical, then legacy lowercase variant
    "wsi_files",  # PathLab uploads raw slide store
    "wsi", "WSI", "wsi_images",
    "slides", "slide",  # legacy normalizer output
)
_CONVENTIONAL_LABEL_FILES = ("labels.csv", "label.csv", "labels.tsv", "labels.json")
_CONVENTIONAL_SPLITS_FILES = ("splits.json", "split.json")


def _runtime_join(container_root: str, name: str) -> str:
    container = container_root.rstrip("/")
    return f"{container}/{name}" if container else name


def _looks_like_label_table(path: Path) -> bool:
    """Return True for CSV/TSV files with slide-id plus label-like columns."""
    if path.suffix.lower() not in {".csv", ".tsv"}:
        return False
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            fieldnames = reader.fieldnames or []
    except OSError:
        return False

    columns = {str(c or "").strip().lower() for c in fieldnames}
    if not columns:
        return False

    try:
        from .wsi_splits import (
            EVENT_COLUMNS,
            LABEL_COLUMNS,
            SLIDE_ID_COLUMNS,
            TIME_COLUMNS,
        )
    except Exception:
        return False

    slide_cols = {c.lower() for c in SLIDE_ID_COLUMNS}
    label_cols = {c.lower() for c in LABEL_COLUMNS}
    time_cols = {c.lower() for c in TIME_COLUMNS}
    event_cols = {c.lower() for c in EVENT_COLUMNS}
    has_slide = bool(columns & slide_cols)
    has_classification_label = bool(columns & label_cols)
    has_survival_label = bool(columns & time_cols and columns & event_cols)
    return has_slide and (has_classification_label or has_survival_label)


def _append_unique(out: list[ResolvedPath], item: ResolvedPath) -> None:
    if any(p.host_path == item.host_path for p in out):
        return
    out.append(item)


def _runtime_parent(path: str) -> str:
    from pathlib import PurePosixPath

    raw = str(path or "").rstrip("/")
    if not raw:
        return ""
    parent = str(PurePosixPath(raw).parent)
    return "" if parent == "." else parent


def _data_dir_for_child(child: ResolvedPath) -> ResolvedPath:
    return ResolvedPath(
        host_path=child.host_path.parent,
        runtime_path=_runtime_parent(child.runtime_path),
        source=child.source,
    )


def _class_subdir_stats(root: str | Path, exts: set[str]) -> tuple[int, int]:
    path = Path(root)
    if not path.is_dir():
        return 0, 0
    lowered = {e.lower() for e in exts}
    n_classes = 0
    n_files = 0
    try:
        children = [p for p in path.iterdir() if p.is_dir()]
    except OSError:
        return 0, 0
    for child in children:
        count = sum(
            1
            for f in child.rglob("*")
            if f.is_file() and f.suffix.lower() in lowered
        )
        if count:
            n_classes += 1
            n_files += count
    return n_classes, n_files


def _patch_splits_file_matches(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    train = data.get("train")
    val = data.get("val")
    test = data.get("test")
    return (
        isinstance(train, list)
        and len(train) > 0
        and (
            (isinstance(val, list) and len(val) > 0)
            or (isinstance(test, list) and len(test) > 0)
        )
    )


def _conventional_under(host_root: str, container_root: str) -> ReadinessCandidates:
    """Probe conventional subpaths under one mount."""
    cands = ReadinessCandidates()
    host = Path(host_root).expanduser()
    container = container_root.rstrip("/")
    for sub in _CONVENTIONAL_FEATURE_DIRS:
        host_sub = host / sub
        if host_sub.is_dir():
            _append_unique(cands.features_dirs, ResolvedPath(
                host_path=host_sub,
                runtime_path=_runtime_join(container, sub),
                source="mount",
            ))
    training_root = host / "training"
    if training_root.is_dir():
        for feature_dir in sorted(training_root.glob("*/features")):
            if feature_dir.is_dir():
                rel = feature_dir.relative_to(host)
                runtime = container
                for part in rel.parts:
                    runtime = _runtime_join(runtime, part)
                _append_unique(cands.features_dirs, ResolvedPath(
                    host_path=feature_dir,
                    runtime_path=runtime,
                    source="mount",
                ))
    for sub in _CONVENTIONAL_IMAGE_DIRS:
        host_sub = host / sub
        if host_sub.is_dir():
            _append_unique(cands.images_dirs, ResolvedPath(
                host_path=host_sub,
                runtime_path=_runtime_join(container, sub),
                source="mount",
            ))
    for sub in _CONVENTIONAL_WSI_DIRS:
        host_sub = host / sub
        if host_sub.is_dir():
            _append_unique(cands.wsi_dirs, ResolvedPath(
                host_path=host_sub,
                runtime_path=_runtime_join(container, sub),
                source="mount",
            ))
    for sub in _CONVENTIONAL_LABEL_FILES:
        host_sub = host / sub
        if host_sub.is_file():
            _append_unique(cands.labels_files, ResolvedPath(
                host_path=host_sub,
                runtime_path=_runtime_join(container, sub),
                source="mount",
            ))
    if host.is_dir():
        for host_sub in sorted(host.iterdir()):
            if host_sub.is_file() and _looks_like_label_table(host_sub):
                _append_unique(cands.labels_files, ResolvedPath(
                    host_path=host_sub,
                    runtime_path=_runtime_join(container, host_sub.name),
                    source="mount",
                ))
    for sub in _CONVENTIONAL_SPLITS_FILES:
        host_sub = host / sub
        if host_sub.is_file():
            _append_unique(cands.splits_files, ResolvedPath(
                host_path=host_sub,
                runtime_path=_runtime_join(container, sub),
                source="mount",
            ))
    return cands


def _merge_into(target: ReadinessCandidates, src: ReadinessCandidates) -> None:
    for p in src.features_dirs:
        _append_unique(target.features_dirs, p)
    for p in src.images_dirs:
        _append_unique(target.images_dirs, p)
    for p in src.splits_files:
        _append_unique(target.splits_files, p)
    for p in src.wsi_dirs:
        _append_unique(target.wsi_dirs, p)
    for p in src.labels_files:
        _append_unique(target.labels_files, p)


def _collect_question_paths(question: str) -> list[Path]:
    """Pull absolute path tokens out of free-form text."""
    import re

    tokens = re.findall(r"(?:^|\s)(/[\w./_-]+)", question or "")
    return [Path(t).expanduser() for t in tokens]


_CLASSIFICATION_SPLIT_KEYS = {"train", "val", "test", "labels"}
_SURVIVAL_SPLIT_KEYS = {"train", "val", "test", "survival_times", "event_status"}


def splits_file_matches_task(path: str | Path, task_type: str) -> bool:
    """Return True iff ``path`` is a usable splits JSON.

    Plan-2026-04-30 data-readiness review P1-5: presence of required keys
    is necessary but not sufficient — every split (``train``/``val``/``test``)
    must be a non-empty list, and every classification slide ID must have
    a label. Without this readiness can claim ``raw_wsi_ready`` for a
    splits file that yields zero-length val/test → meaningless metrics.
    """
    import json

    p = Path(path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text())
    except Exception:
        return False
    if not isinstance(data, dict):
        return False

    required = (
        _SURVIVAL_SPLIT_KEYS
        if task_type == "survival_analysis"
        else _CLASSIFICATION_SPLIT_KEYS
    )
    if not required.issubset(set(data.keys())):
        return False

    # All three core splits must be non-empty lists.
    for key in ("train", "val", "test"):
        value = data.get(key)
        if not isinstance(value, list) or len(value) == 0:
            return False

    # Classification: every listed ID must have a label entry.
    if task_type != "survival_analysis":
        labels = data.get("labels")
        if not isinstance(labels, dict):
            return False
        all_ids = set(data["train"]) | set(data["val"]) | set(data["test"])
        if not all_ids.issubset(set(labels.keys())):
            return False

    return True


def _split_slide_ids(path: str | Path) -> set[str]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    slide_ids: set[str] = set()
    for key in ("train", "val", "test"):
        values = data.get(key)
        if isinstance(values, list):
            slide_ids.update(str(item) for item in values if str(item))
    return slide_ids


def _load_no_tissue_slide_ids(feature_dir: str | Path) -> set[str]:
    """Return slide IDs that feature extraction explicitly marked no_tissue."""
    out: set[str] = set()
    for meta_path in _candidate_extraction_meta_paths(feature_dir):
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
        for slide_id, record in results.items():
            if _record_is_no_tissue(record):
                out.add(str(slide_id))
    return out


def _feature_cache_coverage(feature_dir: str | Path, splits_file: str | Path) -> tuple[bool, dict[str, Any]]:
    """Return whether feature tensors cover enough split IDs to train.

    MIL training filters missing tensors before epochs. A small number of
    missing features should not force extraction when every split still has
    usable slides and overall coverage is high.
    """
    p = Path(splits_file)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False, {}
    if not isinstance(data, dict):
        return False, {}
    split_ids = {
        key: [str(item) for item in data.get(key, []) if str(item)]
        for key in ("train", "val", "test")
    }
    expected = {slide_id for ids in split_ids.values() for slide_id in ids}
    if not expected:
        return False, {}
    feature_path = Path(feature_dir)
    try:
        present = {
            p.stem
            for p in feature_path.iterdir()
            if p.is_file() and p.suffix.lower() in FEATURE_EXTS
        }
    except OSError:
        return False, {}
    present_norm = {item.lower() for item in present}

    def has_feature(slide_id: str) -> bool:
        variants = {slide_id.lower()}
        stem = Path(slide_id).stem.lower()
        if stem:
            variants.add(stem)
        return bool(variants & present_norm)

    present_by_split = {}
    missing_ids_by_split = {}
    for key, ids in split_ids.items():
        missing_ids = [slide_id for slide_id in ids if not has_feature(slide_id)]
        missing_ids_by_split[key] = missing_ids
        present_by_split[key] = len(ids) - len(missing_ids)
    missing_by_split = {
        key: len(missing_ids)
        for key, missing_ids in missing_ids_by_split.items()
    }
    missing_ids = [
        slide_id
        for key in ("train", "val", "test")
        for slide_id in missing_ids_by_split.get(key, [])
    ]
    present_total = sum(present_by_split.values())
    expected_total = sum(len(ids) for ids in split_ids.values())
    coverage = present_total / expected_total if expected_total else 0.0
    min_coverage = _coerce_float(os.environ.get("PATHSCIENTIST_FEATURE_READY_MIN_COVERAGE"))
    if min_coverage is None:
        min_coverage = 0.95
    if min_coverage > 1.0:
        min_coverage = min_coverage / 100.0
    ok = (
        coverage >= min_coverage
        and all(present_by_split[key] > 0 for key in ("train", "val", "test"))
    )
    return ok, {
        "coverage": round(coverage, 4),
        "present_total": present_total,
        "expected_total": expected_total,
        "missing_total": expected_total - present_total,
        "missing_ids": missing_ids,
        "missing_ids_by_split": missing_ids_by_split,
        "present_by_split": present_by_split,
        "missing_by_split": missing_by_split,
        "min_coverage": min_coverage,
    }


def _coverage_is_ready_after_ignoring_no_tissue(
    coverage: dict[str, Any],
    no_tissue_ids: set[str],
) -> bool:
    missing_ids = {
        str(slide_id)
        for slide_id in coverage.get("missing_ids") or []
        if str(slide_id)
    }
    if not missing_ids:
        return False

    ignored_no_tissue_ids = missing_ids & no_tissue_ids
    unresolved_missing_ids = missing_ids - no_tissue_ids
    coverage["ignored_no_tissue_ids"] = sorted(ignored_no_tissue_ids)
    coverage["unresolved_missing_ids"] = sorted(unresolved_missing_ids)
    if unresolved_missing_ids:
        return False

    present_by_split = coverage.get("present_by_split") or {}
    return all(
        int(present_by_split.get(key) or 0) > 0
        for key in ("train", "val", "test")
    )


def _feature_cache_covers_splits(feature_dir: str | Path, splits_file: str | Path) -> bool:
    ok, _coverage = _feature_cache_coverage(feature_dir, splits_file)
    return ok


def _question_requests_missing_feature_extraction(question: str) -> bool:
    text = (question or "").lower()
    if not text:
        return False
    return (
        ("missing feature" in text and any(token in text for token in ("extract", "generate", "compute")))
        or "extract any missing features" in text
        or "extract missing features" in text
        or "补提" in question
        or ("缺失" in question and "特征" in question and ("提取" in question or "补" in question))
    )


def collect_readiness_candidates(
    *,
    prepared_contract: dict[str, str] | None = None,
    data_mounts: dict[str, str] | None = None,
    question: str = "",
) -> ReadinessCandidates:
    """Walk every input source and assemble a bundle of probe candidates.

    Sources, in order:
    1. Direct keys from ``prepared_contract`` (resolved through ``data_mounts``).
    2. Conventional subpaths under each mounted host root.
    3. Absolute path tokens from ``question`` if they exist on disk.
    """
    cands = ReadinessCandidates()
    contract = prepared_contract or {}
    mounts = data_mounts or {}

    # 1. Direct contract keys.
    for key, target in (
        ("features_dir", cands.features_dirs),
        ("images_dir", cands.images_dirs),
        ("splits_file", cands.splits_files),
        ("wsi_dir", cands.wsi_dirs),
        ("labels_file", cands.labels_files),
    ):
        raw = contract.get(key)
        if not raw:
            continue
        resolved = resolve_probe_path(raw, data_mounts=mounts)
        if str(resolved.host_path):
            _append_unique(target, resolved)

    # 2. Conventional subpaths under each mount.
    for host_root, container_root in mounts.items():
        if not host_root or not container_root:
            continue
        _merge_into(cands, _conventional_under(host_root, container_root))

    # 3. Absolute path tokens from the user's question.
    for tok in _collect_question_paths(question):
        if not tok.exists():
            continue
        if tok.is_dir():
            _merge_into(cands, _conventional_under(str(tok), str(tok)))
            if contains_files_with_ext(tok, FEATURE_EXTS):
                _append_unique(cands.features_dirs, ResolvedPath(tok, str(tok), "host"))
            if contains_files_with_ext(tok, PATCH_IMAGE_EXTS):
                _append_unique(cands.images_dirs, ResolvedPath(tok, str(tok), "host"))
            if contains_files_with_ext(tok, WSI_EXTS):
                _append_unique(cands.wsi_dirs, ResolvedPath(tok, str(tok), "host"))
        elif tok.is_file():
            name = tok.name.lower()
            if name in {f.lower() for f in _CONVENTIONAL_LABEL_FILES}:
                _append_unique(cands.labels_files, ResolvedPath(tok, str(tok), "host"))
            elif _looks_like_label_table(tok):
                _append_unique(cands.labels_files, ResolvedPath(tok, str(tok), "host"))
            elif name in {f.lower() for f in _CONVENTIONAL_SPLITS_FILES}:
                _append_unique(cands.splits_files, ResolvedPath(tok, str(tok), "host"))

    return cands


# ---------------------------------------------------------------- T3: assess


def _first_ready_feature_pair(
    candidates: ReadinessCandidates,
    *,
    task_type: str,
    preferred_feature_extractor: str = "",
) -> tuple[ResolvedPath, ResolvedPath, str, dict[str, Any]] | None:
    for fdir in candidates.features_dirs:
        leaf = _leaf_feature_dir(
            fdir,
            preferred_feature_extractor=preferred_feature_extractor,
        )
        if leaf is None:
            continue
        if not _feature_cache_is_complete_path(leaf.host_path):
            continue
        for splits in candidates.splits_files:
            if not splits_file_matches_task(splits.host_path, task_type):
                continue
            covers_splits, coverage = _feature_cache_coverage(leaf.host_path, splits.host_path)
            if covers_splits and not coverage.get("missing_total", 0):
                return (leaf, splits, leaf.source or splits.source or "preflight", coverage)
            no_tissue_ids = _load_no_tissue_slide_ids(leaf.host_path)
            if _coverage_is_ready_after_ignoring_no_tissue(coverage, no_tissue_ids):
                return (leaf, splits, leaf.source or splits.source or "preflight", coverage)
    return None


def _first_patch_splits(candidates: ReadinessCandidates) -> ResolvedPath | None:
    return next(
        (p for p in candidates.splits_files if _patch_splits_file_matches(p.host_path)),
        None,
    )


def _assess_patch_classification_readiness(
    candidates: ReadinessCandidates,
) -> DataReadinessResult:
    splits = _first_patch_splits(candidates)

    for fdir in candidates.features_dirs:
        n_classes, n_files = _class_subdir_stats(fdir.host_path, FEATURE_EXTS)
        if n_classes >= 2 and n_files > 0:
            data_dir = _data_dir_for_child(fdir)
            return DataReadinessResult(
                status="patch_features_ready",
                source=fdir.source or "preflight",
                data_dir=data_dir.runtime_path,
                data_dir_host=str(data_dir.host_path),
                features_dir=fdir.runtime_path,
                features_dir_host=str(fdir.host_path),
                splits_file=splits.runtime_path if splits else "",
                splits_file_host=str(splits.host_path) if splits else "",
                notes=[
                    "patch feature tensors detected; run patch classifier directly",
                ],
            )

    for idir in candidates.images_dirs:
        n_classes, n_files = _class_subdir_stats(idir.host_path, PATCH_IMAGE_EXTS)
        if n_classes >= 2 and n_files > 0:
            data_dir = _data_dir_for_child(idir)
            return DataReadinessResult(
                status="patch_images_ready",
                source=idir.source or "preflight",
                data_dir=data_dir.runtime_path,
                data_dir_host=str(data_dir.host_path),
                images_dir=idir.runtime_path,
                images_dir_host=str(idir.host_path),
                splits_file=splits.runtime_path if splits else "",
                splits_file_host=str(splits.host_path) if splits else "",
                notes=[
                    "patch images detected; classifier template will use a "
                    "frozen patch encoder before the classifier head",
                ],
            )

    has_feature_files = any(
        contains_files_with_ext(p.host_path, FEATURE_EXTS)
        for p in candidates.features_dirs
    )
    has_image_files = any(
        contains_files_with_ext(p.host_path, PATCH_IMAGE_EXTS)
        for p in candidates.images_dirs
    )
    missing = ["features_dir", "images_dir"]
    if has_feature_files or has_image_files:
        missing.append("patch_class_subdirectories")
    return DataReadinessResult(
        status="missing_data",
        source="preflight",
        missing=missing,
        notes=[
            "need PathLab DB-selected patch images with labels/splits, or "
            "filesystem fallback DATA_DIR/images/<class>/* / "
            "DATA_DIR/features/<class>/*.pt",
        ],
    )



def _runtime_child(root: ResolvedPath, name: str) -> ResolvedPath:
    return ResolvedPath(
        host_path=root.host_path / name,
        runtime_path=_runtime_join(root.runtime_path, name),
        source=root.source,
    )


def _manifest_requested_label_inference(host_root: Path) -> dict[str, Any] | None:
    manifest_path = host_root / "dataset_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not bool(data.get("requires_label_inference")):
        return None
    return data


def _label_inference_wsi_candidate(
    candidates: ReadinessCandidates,
) -> tuple[ResolvedPath, dict[str, Any], ResolvedPath, ResolvedPath, str] | None:
    for wsi in candidates.wsi_dirs:
        if not contains_files_with_ext(wsi.host_path, WSI_EXTS):
            continue
        manifest = _manifest_requested_label_inference(wsi.host_path.parent)
        if manifest is None:
            continue
        labels_name = str(manifest.get("labels_file") or "labels.csv").strip() or "labels.csv"
        splits_name = str(manifest.get("splits_file") or "splits.json").strip() or "splits.json"
        labels = _runtime_child(_data_dir_for_child(wsi), labels_name)
        splits = _runtime_child(_data_dir_for_child(wsi), splits_name)
        return (wsi, manifest, labels, splits, wsi.source or "pathlab_dataset_view")
    return None


def _first_existing_feature_leaf(
    candidates: ReadinessCandidates,
    *,
    preferred_feature_extractor: str = "",
) -> ResolvedPath | None:
    for fdir in candidates.features_dirs:
        leaf = _leaf_feature_dir(
            fdir,
            preferred_feature_extractor=preferred_feature_extractor,
        )
        if leaf is not None and _feature_cache_is_complete_path(leaf.host_path):
            return leaf
    return None


def _first_ready_raw_wsi_pair(
    candidates: ReadinessCandidates,
    *,
    task_type: str,
) -> tuple[ResolvedPath, ResolvedPath, ResolvedPath, str] | None:
    """For classification we require labels AND a valid splits file at this
    stage (Task 4 will add deterministic split generation)."""
    for wsi in candidates.wsi_dirs:
        if not contains_files_with_ext(wsi.host_path, WSI_EXTS):
            continue
        labels = next((p for p in candidates.labels_files if p.host_path.is_file()), None)
        if labels is None:
            continue
        splits = next(
            (
                p for p in candidates.splits_files
                if splits_file_matches_task(p.host_path, task_type)
            ),
            None,
        )
        if splits is None:
            continue
        return (wsi, labels, splits, wsi.source or "preflight")
    return None


def _missing_requirements(
    candidates: ReadinessCandidates,
    *,
    task_type: str,
) -> list[str]:
    """Best-effort 'what's missing' list for actionable error messages.

    Rules:
    - features present but splits invalid → ``["splits_file"]``
    - WSI present but labels missing → ``["labels_file"]`` (+ splits if also missing)
    - WSI + labels but splits invalid → ``["splits_file"]``
    - nothing useful mounted → all four keys.
    """
    has_features = any(
        (leaf := _leaf_feature_dir(p)) is not None
        and _feature_cache_is_complete_path(leaf.host_path)
        for p in candidates.features_dirs
    )
    has_wsi = any(
        contains_files_with_ext(p.host_path, WSI_EXTS)
        for p in candidates.wsi_dirs
    )
    has_labels = any(p.host_path.is_file() for p in candidates.labels_files)
    has_splits = any(
        splits_file_matches_task(p.host_path, task_type)
        for p in candidates.splits_files
    )

    missing: list[str] = []
    if has_features:
        if not has_splits:
            missing.append("splits_file")
        return missing

    # No usable features. Look at the raw-WSI path.
    if has_wsi:
        if not has_labels:
            missing.append("labels_file")
        if not has_splits:
            missing.append("splits_file")
        return missing

    # Nothing useful at all.
    missing.append("features_dir")
    missing.append("wsi_dir")
    if not has_labels:
        missing.append("labels_file")
    if not has_splits:
        missing.append("splits_file")
    return missing


def _try_generate_splits(
    candidates: ReadinessCandidates,
    *,
    generated_contract_root: str | Path | None,
    task_type: str = "mil_classification",
) -> ResolvedPath | None:
    """Plan-2026-04-30 data-readiness Task 4 + review P2-6: generate a
    splits.json from labels when raw WSI + labels exist but no splits do.

    Dispatches on ``task_type``:
    - ``survival_analysis`` → ``build_survival_splits_from_labels`` so the
      output carries ``survival_times`` + ``event_status`` keys (which
      ``splits_file_matches_task`` validates separately).
    - everything else → classification splits with integer ``labels``.
    """
    label_candidate = next(
        (p for p in candidates.labels_files if p.host_path.is_file()), None,
    )
    if label_candidate is None:
        return None

    if generated_contract_root is not None:
        out_dir = Path(generated_contract_root).expanduser()
        out_path = out_dir / "splits.json"
    else:
        # Fallback: alongside the labels file. Tests under chmod-readonly
        # parents will hit OSError below and we'll return None cleanly.
        out_path = label_candidate.host_path.parent / "splits.json"

    try:
        if task_type == "survival_analysis":
            from .wsi_splits import build_survival_splits_from_labels

            build_survival_splits_from_labels(label_candidate.host_path, out_path)
        else:
            from .wsi_splits import build_classification_splits_from_labels

            build_classification_splits_from_labels(label_candidate.host_path, out_path)
    except (ValueError, OSError):
        return None

    return ResolvedPath(
        host_path=out_path,
        runtime_path=str(out_path),
        source="generated",
    )


def assess_data_readiness(
    profile,
    *,
    prepared_contract: dict[str, str] | None = None,
    data_mounts: dict[str, str] | None = None,
    question: str = "",
    generated_contract_root: str | Path | None = None,
    preferred_feature_extractor: str = "",
) -> DataReadinessResult:
    """Assess whether a slide-level feature consumer can run as-is.

    Returns one of: ``features_ready`` / ``raw_wsi_ready`` / ``missing_data``
    / ``not_applicable``. See ``DataReadinessResult`` docstring for what
    each status means and how the runtime/host path fields differ.

    Plan-2026-04-30 data-readiness review constraint #2: classification
    raw_wsi_ready requires a splits file. Task 4 will add deterministic
    split generation for raw WSI + labels when no split is present.
    """
    task_type = (
        getattr(profile, "task_type", "")
        or getattr(profile, "preferred_skill", "")
        or ""
    ).strip()
    candidates = collect_readiness_candidates(
        prepared_contract=prepared_contract or {},
        data_mounts=data_mounts or {},
        question=question or "",
    )

    if task_type in PATCH_CONSUMER_TASKS:
        return _assess_patch_classification_readiness(candidates)

    if task_type not in FEATURE_CONSUMER_TASKS:
        return DataReadinessResult(status="not_applicable", source="task_profile")

    feature_pair = _first_ready_feature_pair(
        candidates,
        task_type=task_type,
        preferred_feature_extractor=preferred_feature_extractor,
    )
    if feature_pair:
        features_dir, splits_file, source, coverage = feature_pair
        notes = ["existing feature tensors detected; skip feature_extraction"]
        if coverage and coverage.get("missing_total", 0):
            ignored_no_tissue_ids = coverage.get("ignored_no_tissue_ids") or []
            unresolved_missing_ids = coverage.get("unresolved_missing_ids") or []
            low_coverage_needs_extraction = (
                coverage.get("coverage", 1.0) < coverage.get("min_coverage", 0.95)
                and not ignored_no_tissue_ids
            )
            if unresolved_missing_ids or low_coverage_needs_extraction:
                raw_pair = _first_ready_raw_wsi_pair(candidates, task_type=task_type)
                if raw_pair:
                    wsi_dir, labels_file, raw_splits_file, raw_source = raw_pair
                    return DataReadinessResult(
                        status="raw_wsi_ready",
                        source=raw_source or source,
                        wsi_dir=wsi_dir.runtime_path,
                        labels_file=labels_file.runtime_path,
                        splits_file=raw_splits_file.runtime_path,
                        features_dir=features_dir.runtime_path,
                        wsi_dir_host=str(wsi_dir.host_path),
                        labels_file_host=str(labels_file.host_path),
                        splits_file_host=str(raw_splits_file.host_path),
                        features_dir_host=str(features_dir.host_path),
                        missing=["features_dir"],
                        notes=[
                            "existing feature tensors are incomplete; user requested missing feature extraction before training",
                            "feature coverage "
                            f"{coverage['present_total']}/{coverage['expected_total']}",
                        ],
                    )
            if ignored_no_tissue_ids:
                notes.append(
                    "feature coverage "
                    f"{coverage['present_total']}/{coverage['expected_total']}; "
                    f"ignored {len(ignored_no_tissue_ids)} no_tissue slide(s)"
                )
            else:
                notes.append(
                    "feature coverage "
                    f"{coverage['present_total']}/{coverage['expected_total']} "
                    "with every split represented; training will filter missing tensors"
                )
        return DataReadinessResult(
            status="features_ready",
            source=source,
            features_dir=features_dir.runtime_path,
            splits_file=splits_file.runtime_path,
            features_dir_host=str(features_dir.host_path),
            splits_file_host=str(splits_file.host_path),
            notes=notes,
        )

    raw_pair = _first_ready_raw_wsi_pair(candidates, task_type=task_type)
    if raw_pair:
        wsi_dir, labels_file, splits_file, source = raw_pair
        return DataReadinessResult(
            status="raw_wsi_ready",
            source=source,
            wsi_dir=wsi_dir.runtime_path,
            labels_file=labels_file.runtime_path,
            splits_file=splits_file.runtime_path,
            wsi_dir_host=str(wsi_dir.host_path),
            labels_file_host=str(labels_file.host_path),
            splits_file_host=str(splits_file.host_path),
            missing=["features_dir"],
            notes=[
                "raw WSI detected; feature_extraction required before downstream training",
            ],
        )

    # Plan-2026-04-30 data-readiness Task 4: try to GENERATE splits.json
    # when raw WSI + labels exist but no splits do. Re-check raw_wsi_ready
    # with the generated splits attached.
    has_raw_wsi = any(
        contains_files_with_ext(p.host_path, WSI_EXTS) for p in candidates.wsi_dirs
    )
    has_labels_file = any(p.host_path.is_file() for p in candidates.labels_files)
    has_valid_splits = any(
        splits_file_matches_task(p.host_path, task_type)
        for p in candidates.splits_files
    )
    if has_raw_wsi and not has_labels_file:
        label_inference = _label_inference_wsi_candidate(candidates)
        if label_inference is not None:
            wsi_dir, _manifest, labels_file, splits_file, source = label_inference
            existing_features = _first_existing_feature_leaf(
                candidates,
                preferred_feature_extractor=preferred_feature_extractor,
            )
            missing = [
                name
                for name, present in (
                    ("labels_file", labels_file.host_path.is_file()),
                    ("splits_file", splits_file.host_path.is_file() and splits_file_matches_task(splits_file.host_path, task_type)),
                )
                if not present
            ]
            notes = [
                "registered PathLab WSI dataset is accessible but lacks labels; "
                "agent must infer labels from dataset metadata/layout before training",
            ]
            if existing_features is not None:
                notes.append(
                    "existing feature tensors detected; after label inference, train directly",
                )
            else:
                missing.append("features_dir")
            return DataReadinessResult(
                status="raw_wsi_needs_labels",
                source=source,
                wsi_dir=wsi_dir.runtime_path,
                labels_file=labels_file.runtime_path,
                splits_file=splits_file.runtime_path,
                features_dir=existing_features.runtime_path if existing_features else "",
                wsi_dir_host=str(wsi_dir.host_path),
                labels_file_host=str(labels_file.host_path),
                splits_file_host=str(splits_file.host_path),
                features_dir_host=str(existing_features.host_path) if existing_features else "",
                missing=list(dict.fromkeys(missing)),
                notes=notes,
            )

    if has_raw_wsi and has_labels_file and not has_valid_splits:
        generated = _try_generate_splits(
            candidates,
            generated_contract_root=generated_contract_root,
            task_type=task_type,
        )
        if generated is not None:
            _append_unique(candidates.splits_files, generated)
            raw_pair = _first_ready_raw_wsi_pair(candidates, task_type=task_type)
            if raw_pair:
                wsi_dir, labels_file, splits_file, source = raw_pair
                return DataReadinessResult(
                    status="raw_wsi_ready",
                    source=source,
                    wsi_dir=wsi_dir.runtime_path,
                    labels_file=labels_file.runtime_path,
                    splits_file=splits_file.runtime_path,
                    wsi_dir_host=str(wsi_dir.host_path),
                    labels_file_host=str(labels_file.host_path),
                    splits_file_host=str(splits_file.host_path),
                    missing=["features_dir"],
                    notes=[
                        "raw WSI detected; splits generated from labels; "
                        "feature_extraction required before downstream training",
                    ],
                )

    return DataReadinessResult(
        status="missing_data",
        source="preflight",
        missing=_missing_requirements(candidates, task_type=task_type),
        notes=[
            "need either feature tensors plus splits.json, or raw WSI plus labels and splits",
        ],
    )
