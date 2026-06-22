"""End-to-end dataset acquisition service.

Composes scout + provider + downloader + normalizer + manifest into one
``acquire()`` call so the orchestrator stage doesn't have to.

Pure orchestrator logic - every IO failure is captured in the resulting
manifest's ``status`` / ``reason`` rather than raised, so the upstream
acquisition stage can persist the manifest and continue.
"""
from __future__ import annotations

import hashlib
import csv
import fnmatch
import inspect
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .acquisition_plan import (
    acquisition_plan_path_for_workspace,
    candidate_to_plan_entry,
    save_acquisition_plan,
)
from .downloader import extract_archive, safe_dataset_id
from .download_progress import (
    DownloadProgressReporter,
    download_progress_path_for_workspace,
)
from .evidence import write_acquisition_record
from .manifests import manifest_path_for_workspace, save_manifest
from .normalizers.base import DatasetNormalizer, NormalizerError
from .policy import AcquisitionPolicy
from .providers.base import DatasetProvider, DownloadResult
from .registry import DatasetRegistry
from .scout import DatasetCandidate, DatasetScout, DatasetSemanticMatcher
from .types import DatasetManifest, TaskProfile

logger = logging.getLogger(__name__)

_ARCHIVE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz")
_FEATURE_CONSUMER_TASKS = {"mil_classification", "survival_analysis"}
_LOCAL_DISCOVERY_FILENAME = "local_discovery.json"
_LOCAL_SCAN_MAX_DIRS = 96
_LOCAL_SCAN_MAX_DEPTH = 3
_LOCAL_SCAN_SKIP_DIRS = {
    ".dataset",
    ".pathscientist",
    ".git",
    "__pycache__",
    "logs",
    "output",
    "outputs",
    "runs",
    "prepared",
}
_LOCAL_WSI_EXTS = {
    ".svs", ".svslide", ".tif", ".tiff", ".ndpi", ".mrxs",
    ".scn", ".vsi", ".vms", ".vmu", ".bif", ".kfb", ".sdpc",
    ".tmap", ".qptiff",
}
_LOCAL_RAW_HINT_DIRS = {
    "WSIs", "wsis", "slides", "slide", "wsi", "WSI", "wsi_images",
    "train_images", "images",
}
_LOCAL_IDENTITY_GENERIC_TOKENS = {
    "assessment",
    "classification",
    "comprehensive",
    "data",
    "dataset",
    "datasets",
    "direct",
    "download",
    "grade",
    "grading",
    "features",
    "huggingface",
    "image",
    "images",
    "kaggle",
    "label",
    "labels",
    "manual",
    "mil",
    "pathology",
    "prepared",
    "public",
    "raw",
    "scidb",
    "slide",
    "slides",
    "task",
    "train",
    "training",
    "whole",
    "wsi",
    "wsis",
    "zenodo",
}
_LOCAL_PROVIDER_TOKENS = {
    "hf": "huggingface",
    "huggingface": "huggingface",
    "kaggle": "kaggle",
    "scidb": "scidb",
    "zenodo": "zenodo",
    "tcia": "tcia",
    "direct": "direct_http",
    "directhttp": "direct_http",
}
_LOCAL_SOURCE_ONLY_TOKENS = {
    "nanfang",
    "pwh",
    "xijing",
    "zhefuyi",
    "zhengda",
    "shantou",
    "zhongshan",
    "zhongshansanyuan",
    "zhongshanzhongliu",
}
_LOCAL_LABEL_FILE_NAMES = {
    "labels.csv", "label.csv", "labels.tsv", "label.tsv",
    "train.csv", "train_labels.csv",
}
_LOCAL_LABEL_FILE_PATTERNS = ("*label*.csv", "*label*.tsv", "*labels*.csv", "*labels*.tsv")
_PROSTATE_LABEL_COLUMNS = {"isup_grade", "gleason_score"}
_GASTRITIS_LABEL_COLUMNS = {"task1", "task2", "task3", "task4"}
_GDC_AGGREGATE_ALIASES = {"TCGA-LUNG", "TCGA-NSCLC"}
_TCGA_NSCLC_PROJECT_LABELS = {
    "TCGA-LUAD": "LUAD",
    "TCGA-LUSC": "LUSC",
}


def _looks_like_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in _ARCHIVE_EXTS)


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _contains_file_with_ext_limited(
    root: Path,
    exts: set[str],
    *,
    max_seen: int = 4096,
) -> bool:
    """Bounded probe used before calling a normalizer on local data roots."""
    if not root.is_dir():
        return False
    lowered = {e.lower() for e in exts}
    seen = 0
    try:
        iterator = root.rglob("*")
        for p in iterator:
            seen += 1
            if seen > max_seen:
                return False
            if p.is_file() and p.suffix.lower() in lowered:
                return True
    except OSError:
        return False
    return False


def _looks_like_local_raw_dataset(path: Path) -> bool:
    """Return True only for bounded, plausible raw dataset roots."""
    path = Path(path)
    if not path.is_dir():
        return False
    # Direct slide files at the candidate root.
    try:
        for p in path.iterdir():
            if p.is_file() and p.suffix.lower() in _LOCAL_WSI_EXTS:
                return True
    except OSError:
        return False
    # Conventional WSI subdirectories, e.g. PANDA train_images/.
    for name in _LOCAL_RAW_HINT_DIRS:
        sub = path / name
        if _contains_file_with_ext_limited(sub, _LOCAL_WSI_EXTS):
            return True
    return False


def _local_prepared_key(raw_root: Path) -> str:
    try:
        resolved = raw_root.resolve()
    except OSError:
        resolved = raw_root
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return safe_dataset_id(f"local_{raw_root.name}_{digest}")


def _tokenize_local_text(
    raw_parts: Iterable[Any],
    *,
    drop_generic: bool = False,
) -> set[str]:
    """Tokenize dataset/path identity text for local-cache matching.

    We keep both split tokens (``chronic``, ``gastritis``) and compact slugs
    (``cgmil`` from ``CG-MIL``), because dataset directories often use short
    dashed names while registry records contain richer prose.
    """
    tokens: set[str] = set()
    for part in raw_parts:
        text = str(part or "").strip().lower()
        if not text:
            continue
        compact = re.sub(r"[^a-z0-9]+", "", text)
        if len(compact) >= 3:
            tokens.add(compact)
        for token in re.split(r"[^a-z0-9]+", text):
            if len(token) >= 3:
                tokens.add(token)
    if drop_generic:
        tokens = {t for t in tokens if t not in _LOCAL_IDENTITY_GENERIC_TOKENS}
    return tokens


def _provider_hint_from_path_parts(parts: Iterable[Any]) -> str:
    for part in parts:
        for token in _tokenize_local_text([part]):
            provider = _LOCAL_PROVIDER_TOKENS.get(token)
            if provider:
                return provider
    return ""


def _read_label_columns(path: Path) -> list[str]:
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
            return [
                str(c or "").strip()
                for c in (csv.DictReader(fh, dialect=dialect).fieldnames or [])
                if str(c or "").strip()
            ]
    except OSError:
        return []


def _find_label_columns_limited(
    root: Path,
    *,
    max_files: int = 32,
    max_dirs: int = 64,
    max_depth: int = 2,
) -> list[str]:
    """Return label-table columns under ``root`` using a bounded search."""
    root = Path(root)
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        if len(candidates) >= max_files or not path.is_file():
            return
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(path)

    for name in _LOCAL_LABEL_FILE_NAMES:
        _add(root / name)
    queue: list[tuple[Path, int]] = [(root, 0)]
    visited = 0
    while queue and len(candidates) < max_files and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if child.is_file():
                lower = child.name.lower()
                if lower in _LOCAL_LABEL_FILE_NAMES or any(
                    fnmatch.fnmatch(lower, pattern.lower())
                    for pattern in _LOCAL_LABEL_FILE_PATTERNS
                ):
                    _add(child)
            elif depth < max_depth and not child.name.startswith("."):
                queue.append((child, depth + 1))

    columns: list[str] = []
    for candidate in candidates:
        for column in _read_label_columns(candidate):
            if column not in columns:
                columns.append(column)
    return columns


# ---------------------------------------------------------------------------
# DC-1/2 (2026-05-10) — dataset-centric cache layout
#
# Until 2026-05-10 the cache used a provider-centric tree:
#
#     <cache>/raw/<provider>/<safe_dataset_id>/...
#     <cache>/prepared/<normalizer>/<safe_dataset_id>/...
#
# This required cross-referencing three tokens to find a single dataset
# and made it impossible to put features alongside the WSIs they were
# extracted from. Session_64561aa7962b spent 9h extracting features
# into a per-run directory that got purged on session end.
#
# New layout — every dataset is one folder under the cache root:
#
#     <cache>/<dir_name>/
#     ├── WSIs/                          (WSI assets: .svs/.tiff/...)
#     ├── images/                        (patch assets: tiles)
#     ├── labels.csv                     (normalized at root)
#     ├── splits.json                    (normalized at root)
#     ├── prepared/<normalizer>/         (normalizer outputs)
#     ├── pt_files/<extractor>/          (features, kept across sessions)
#     ├── patches/                       (patch coordinate .h5 files)
#     └── manifest.json
#
# ``dir_name`` comes from ``DatasetRecord.dir_name()`` — the canonical
# short name (PANDA / CRC-MSI / NCT-CRC-HE-100K). The helpers below
# centralize the path math so we don't drift between callers.
# ---------------------------------------------------------------------------


_WSI_ASSET_TOKENS = frozenset({"wsi", "wsis", "whole_slide", "slide"})


def _dataset_root_for_record(cache_root: Path, record) -> Path:
    """Return ``<cache_root>/<dir_name>/`` for the dataset."""
    return Path(cache_root) / record.dir_name()


def _raw_root_for_record(cache_root: Path, record) -> Path:
    """Return the raw-asset directory for ``record``.

    WSI datasets get ``<dataset_root>/wsi_files/``; patch / tile / image
    datasets get ``<dataset_root>/images/``. Anything else falls back
    to ``<dataset_root>/raw/`` so we still have a deterministic path.
    """
    root = _dataset_root_for_record(cache_root, record)
    asset_types = {a.lower() for a in (record.asset_types or [])}
    if asset_types & _WSI_ASSET_TOKENS:
        return root / "wsi_files"
    if any("patch" in a or "image" in a or "tile" in a for a in asset_types):
        return root / "images"
    return root / "raw"


def _prepared_root_for_workspace(
    workspace_root: Path, *, normalizer_name: str,
) -> Path:
    """Return ``<workspace>/.dataset/<normalizer>/`` for task artifacts.

    DT-1 (2026-05-12): the user's mental model is "data vs task":

    - Data layer lives under ``<cache>/<dataset>/`` and is persistent /
      cross-session — WSIs, patches, pt_files/<extractor>.
    - Task layer lives under ``<workspace>/.dataset/<normalizer>/`` and
      is per-session — labels.csv, splits.json, WSIs symlinks.

    Pre-DT-1 the prepared root sat at ``<cache>/<dataset>/prepared/<norm>/``
    which conflated the two and made the user's PANDA folder accumulate
    task-shaped artifacts (labels, splits, slide symlinks) on top of the
    data they care about (WSIs + features).
    """
    return Path(workspace_root) / ".dataset" / normalizer_name


# Backwards-compat alias for callers that haven't migrated yet. Returns
# the legacy ``<cache>/<dataset>/prepared/<norm>/`` path. Will be removed
# once all callers pass workspace_root.
def _prepared_root_for_record(
    cache_root: Path, record, *, normalizer_name: str,
) -> Path:
    """Legacy: ``<cache>/<dataset>/prepared/<normalizer>/``. Prefer
    ``_prepared_root_for_workspace`` for new code (DT-1)."""
    return (
        _dataset_root_for_record(cache_root, record)
        / "prepared"
        / normalizer_name
    )


def _features_root_for_record(
    cache_root: Path, record, *, extractor_name: str = "",
) -> Path:
    """Return ``<dataset_root>/pt_files[/<extractor>]/`` for features."""
    root = _dataset_root_for_record(cache_root, record) / "pt_files"
    return root / extractor_name if extractor_name else root


def _gdc_remote_id(record) -> str:
    return str(getattr(record.download, "remote_id", "") or "").strip().upper()


def _is_gdc_aggregate_alias(record) -> bool:
    """Return True for TCGA aliases that are not real GDC project ids."""
    if getattr(record, "provider", "") != "gdc":
        return False
    remote_id = _gdc_remote_id(record)
    return remote_id in _GDC_AGGREGATE_ALIASES


def _is_concrete_gdc_project(record) -> bool:
    """Return True for concrete TCGA project ids like TCGA-LUAD/TCGA-LUSC."""
    if getattr(record, "provider", "") != "gdc":
        return False
    remote_id = _gdc_remote_id(record)
    if remote_id in _GDC_AGGREGATE_ALIASES:
        return False
    return bool(re.fullmatch(r"TCGA-[A-Z0-9]{2,5}", remote_id))


def _tcga_nsclc_label(record) -> str:
    return _TCGA_NSCLC_PROJECT_LABELS.get(_gdc_remote_id(record), "")


def _is_nsclc_profile(profile: TaskProfile) -> bool:
    text = " ".join([
        profile.organ or "",
        profile.prediction_target or "",
        " ".join(profile.dataset_keywords or []),
        " ".join(profile.required_label_keywords or []),
    ]).lower()
    if (profile.prediction_target or "").lower() in {"nsclc_subtype", "tcga_nsclc_subtype"}:
        return True
    tokens = set(re.split(r"[^a-z0-9]+", text))
    return "nsclc" in text or {"luad", "lusc"}.issubset(tokens)


@dataclass
class AcquisitionResult:
    status: str
    manifest: DatasetManifest
    manifest_path: Path
    candidate: DatasetCandidate | None = None
    evidence_path: Path | None = None
    reason: str = ""


class DatasetAcquisitionService:
    """Composes scout + provider + downloader + normalizer + manifest."""

    def __init__(
        self,
        registry: DatasetRegistry,
        providers: dict[str, DatasetProvider],
        normalizers: Iterable[DatasetNormalizer],
        cache_root: Path,
        policy: AcquisitionPolicy | None = None,
        local_identity_llm_parser: Callable[[str], str] | None = None,
        download_only: bool = False,
        pathlab_dataset_resolver: Callable[[Any, TaskProfile, Path], dict[str, Any] | None] | None = None,
    ):
        self._registry = registry
        self._providers = dict(providers)
        self._normalizers = list(normalizers)
        self._cache_root = Path(cache_root)
        self._policy = policy or AcquisitionPolicy()
        self._local_identity_llm_parser = local_identity_llm_parser
        self._download_only = bool(download_only)
        self._pathlab_dataset_resolver = pathlab_dataset_resolver

    def _select_normalizer(self, task_type: str) -> DatasetNormalizer | None:
        for n in self._normalizers:
            if n.supports(task_type):
                return n
        return None

    def _empty_manifest(self, status: str, reason: str, workspace_root: Path) -> DatasetManifest:
        return DatasetManifest(
            dataset_id="", provider="", selected_for_task="",
            raw_root="", prepared_root="",
            data_mounts={}, prepared_contract={},
            access="", status=status,
        )

    def _probe_records(self, records):
        """Plan-2026-04-30 dataset-discovery T6 / review constraint #2:
        run ``provider.probe(record)`` BEFORE scoring/policy so probe tags
        (e.g. ``probe:hf_remote_unverified``) are visible to relevance and
        evidence — without making any live network calls.

        Plan-2026-04-30 dataset-provider-repair Task 0 / blocker #4:
        honor the probe's return value. Providers that return a fresh
        ``DatasetRecord`` (instead of mutating in-place) had their tag
        annotations dropped under the previous in-place-only assumption.
        """
        out = []
        for r in records:
            provider = self._providers.get(r.provider)
            probe = getattr(provider, "probe", None) if provider is not None else None
            if probe is None:
                out.append(r)
                continue
            try:
                probed = probe(r)
                out.append(probed if probed is not None else r)
            except Exception as e:
                logger.warning("probe failed for %s: %s", r.dataset_id, e)
                out.append(r)
        return out

    def _candidate_to_plan_entry(self, candidate) -> dict:
        """Plan-2026-04-30 dataset-provider-repair Task 6: enrich plan
        entries with ``provider_available`` (lookup against the registered
        providers map at write time) plus full ``download`` dict, size,
        license, and source_paper_ids — so reviewers can see exactly why a
        candidate would have been picked or rejected, even if the runtime
        environment has no matching provider.
        """
        entry = candidate_to_plan_entry(candidate)
        record = candidate.record
        entry["provider_available"] = record.provider in self._providers
        entry["estimated_size_gb"] = float(record.estimated_size_gb or 0.0)
        entry["license"] = record.license or ""
        entry["source_paper_ids"] = list(record.source_paper_ids or [])
        entry["download"] = record.download.to_dict()
        return entry

    def _write_plan(
        self,
        workspace_root: Path,
        candidates,
        *,
        status: str,
        selected_dataset_id: str = "",
        reason: str = "",
        profile=None,
    ) -> None:
        """Plan-2026-04-30 dataset-discovery T8: persist .dataset/acquisition_plan.json
        with everything the scout considered + the final selection.

        Plan-2026-04-30 dataset-provider-repair Task 0 / blocker #5: also
        records ``task_profile`` so reviewers see what the user asked for.
        """
        try:
            payload = {
                "status": status,
                "selected_dataset_id": selected_dataset_id,
                "reason": reason,
                "task_profile": profile.to_dict() if profile is not None else {},
                "considered": [
                    self._candidate_to_plan_entry(c) for c in (candidates or [])
                ],
            }
            save_acquisition_plan(
                acquisition_plan_path_for_workspace(workspace_root),
                payload,
            )
        except Exception as e:
            logger.warning("acquisition plan persistence failed: %s", e)

    def _validate_prepared_contract(
        self,
        *,
        profile: TaskProfile,
        contract: dict[str, Any],
        workspace_root: Path,
    ) -> tuple[dict[str, Any], str, dict]:
        """Validate feature-consumer contracts before status=prepared.

        Patch/classification datasets keep their existing normalizer contract.
        Slide-level feature consumers must satisfy data readiness so acquisition
        cannot claim success for raw slides without usable labels/splits.
        """
        if profile.task_type not in _FEATURE_CONSUMER_TASKS:
            return contract, "", {}

        try:
            from .readiness import assess_data_readiness
        except Exception as e:
            return contract, f"prepared_contract_validation_error:{e}", {}

        data_mounts = dict(contract.get("data_mounts") or {})
        prepared_contract = {
            k: str(v)
            for k, v in contract.items()
            if not isinstance(v, dict)
        }
        try:
            readiness = assess_data_readiness(
                profile,
                prepared_contract=prepared_contract,
                data_mounts=data_mounts,
                generated_contract_root=workspace_root / ".dataset" / "readiness",
            )
        except Exception as e:
            return contract, f"prepared_contract_validation_error:{e}", {}

        readiness_dict = readiness.to_dict()
        if readiness.status not in {"features_ready", "raw_wsi_ready"}:
            missing = ",".join(readiness.missing or ["unknown"])
            reason = (
                f"prepared_contract_not_ready:status={readiness.status};"
                f"missing={missing}"
            )
            return contract, reason, readiness_dict

        enriched = dict(contract)
        # If readiness generated a split file from labels, persist that path in
        # the manifest so resumed sessions see the same concrete contract.
        if readiness.splits_file_host and not enriched.get("splits_file"):
            enriched["splits_file"] = readiness.splits_file_host
        return enriched, "", readiness_dict

    def _existing_prepared_contract(
        self,
        *,
        normalizer: DatasetNormalizer,
        profile: TaskProfile,
        prepared_root: Path,
    ) -> dict[str, Any]:
        """Infer a contract from an existing prepared cache when possible."""
        if profile.task_type != "mil_classification":
            return {}
        if getattr(normalizer, "name", "") != "mil_classification":
            return {}
        prepared_root = Path(prepared_root)
        if not prepared_root.is_dir():
            return {}
        wsi_dir = prepared_root / "WSIs"
        if not wsi_dir.is_dir():
            wsi_dir = prepared_root / "slides"
        labels = prepared_root / "labels.csv"
        splits = prepared_root / "splits.json"
        contract: dict[str, Any] = {
            "task_type": "mil_classification",
            "wsi_dir": str(wsi_dir),
            "labels_file": str(labels),
            "requires_feature_extraction": True,
            "data_mounts": {str(prepared_root): "/data"},
        }
        if splits.exists():
            contract["splits_file"] = str(splits)
        return contract

    def _local_discovery_path(self, workspace_root: Path) -> Path:
        return Path(workspace_root) / ".dataset" / _LOCAL_DISCOVERY_FILENAME

    def _write_local_discovery(self, workspace_root: Path, payload: dict[str, Any]) -> None:
        try:
            path = self._local_discovery_path(workspace_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("local discovery audit persistence failed: %s", e)

    def _provider_download(
        self,
        provider: DatasetProvider,
        record,
        raw_root: Path,
        progress: DownloadProgressReporter,
    ) -> DownloadResult:
        download = getattr(provider, "download")
        try:
            signature = inspect.signature(download)
            params = signature.parameters.values()
            accepts_progress = any(
                p.name == "progress" or p.kind == inspect.Parameter.VAR_KEYWORD
                for p in params
            )
        except (TypeError, ValueError):
            accepts_progress = False
        if accepts_progress:
            return download(record, raw_root, progress=progress)
        return download(record, raw_root)

    def _download_only_selection(self, allowed: list[DatasetCandidate]) -> list[DatasetCandidate]:
        """Select concrete datasets for a download-only acquisition.

        TCGA aliases such as ``TCGA-LUNG`` are useful discovery hints but not
        downloadable GDC projects. When concrete TCGA projects are also
        present, prefer those and drop the aggregate alias.
        """
        has_concrete_gdc = any(_is_concrete_gdc_project(c.record) for c in allowed)
        selected: list[DatasetCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in allowed:
            record = candidate.record
            if has_concrete_gdc and _is_gdc_aggregate_alias(record):
                continue
            remote_id = str(getattr(record.download, "remote_id", "") or "")
            key = (record.provider, (remote_id or record.dataset_id).upper())
            if key in seen:
                continue
            seen.add(key)
            selected.append(candidate)
        return selected

    def _download_only_multi_result(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates: list[DatasetCandidate],
        selected: list[DatasetCandidate],
    ) -> AcquisitionResult:
        """Download multiple selected datasets and write one aggregate manifest."""
        selected_ids = [c.record.dataset_id for c in selected]
        multi_id = "multi:" + "+".join(safe_dataset_id(s) for s in selected_ids)
        self._write_plan(
            workspace_root,
            candidates,
            status="planned",
            selected_dataset_id=multi_id,
            reason="before_download_multi",
            profile=profile,
        )

        datasets: list[dict[str, Any]] = []
        data_mounts: dict[str, str] = {}
        failures: list[str] = []
        total = len(selected)

        for index, choice in enumerate(selected, start=1):
            record = choice.record
            raw_root = _raw_root_for_record(self._cache_root, record)
            raw_root.mkdir(parents=True, exist_ok=True)
            provider = self._providers.get(record.provider)
            files: list[Path] = []
            checksum_sha256 = ""
            download_status = "failed"
            reason = ""
            completeness: dict[str, Any] = {}

            local_hit, local_files, completeness, local_reason = self._download_only_local_hit(
                record=record,
                provider=provider,
                raw_root=raw_root,
            )
            if local_hit:
                files = local_files
                download_status = "local_hit"
                reason = local_reason
            elif provider is None:
                reason = f"no_provider:{record.provider}"
            else:
                raw_root.mkdir(parents=True, exist_ok=True)
                progress = DownloadProgressReporter(
                    download_progress_path_for_workspace(workspace_root),
                    dataset_id=record.dataset_id,
                    provider=record.provider,
                    raw_root=raw_root,
                )
                progress.start(extra={
                    "multi_dataset_id": multi_id,
                    "multi_dataset_index": index,
                    "multi_dataset_total": total,
                    "multi_dataset_ids": selected_ids,
                })
                try:
                    download_result = self._provider_download(
                        provider,
                        record,
                        raw_root,
                        progress,
                    )
                    download_status = download_result.status
                    reason = download_result.reason or ""
                    files = list(download_result.files or [])
                    checksum_sha256 = download_result.checksum_sha256 or ""
                except Exception as e:
                    download_status = "failed"
                    reason = f"download_error:{e}"
                progress.finish(download_status, reason=reason)

            if download_status == "downloaded":
                expected_checksum = (record.download.checksum_sha256 or "").lower()
                actual_checksum = (checksum_sha256 or "").lower()
                if expected_checksum and actual_checksum and actual_checksum != expected_checksum:
                    download_status = "failed"
                    reason = (
                        "checksum_mismatch:"
                        f"expected={expected_checksum},actual={actual_checksum}"
                    )
                else:
                    for f in files:
                        if _looks_like_archive(f):
                            try:
                                extract_archive(f, raw_root)
                            except Exception as e:
                                logger.warning("Archive extraction failed for %s: %s", f, e)

            prepared = download_status in {"downloaded", "local_hit"}
            slide_files = self._wsi_files_under(raw_root) if prepared else []
            dataset_entry = {
                "dataset_id": record.dataset_id,
                "name": record.name,
                "provider": record.provider,
                "remote_id": record.download.remote_id,
                "raw_root": str(raw_root),
                "status": "prepared" if prepared else (
                    "skipped_policy" if download_status == "skipped_policy" else "failed"
                ),
                "download_status": download_status,
                "reason": reason,
                "files": [str(p) for p in files],
                "n_wsi": len(slide_files),
            }
            if completeness:
                dataset_entry["completeness"] = completeness
            if checksum_sha256:
                dataset_entry["checksum_sha256"] = checksum_sha256
            datasets.append(dataset_entry)

            if prepared:
                data_mounts[str(raw_root)] = f"/data/raw/{safe_dataset_id(record.dataset_id)}"
            else:
                failures.append(f"{record.dataset_id}:{reason or download_status}")

            write_acquisition_record(
                workspace_root,
                {
                    "status": dataset_entry["status"],
                    "reason": reason or ("download_only" if prepared else download_status),
                    "candidate": {
                        "dataset_id": record.dataset_id,
                        "score": choice.score,
                        "reasons": choice.reasons,
                    },
                    "download": {
                        "status": download_status,
                        "files": [str(p) for p in files],
                    },
                    "task_profile": profile.to_dict(),
                },
            )

        status = "prepared" if not failures else "failed"
        reason = (
            "download_only_multi"
            if status == "prepared"
            else "download_only_multi_partial:" + ";".join(failures)
        )
        manifest = DatasetManifest(
            dataset_id=multi_id,
            provider="multi",
            selected_for_task=profile.task_type,
            raw_root=str(self._cache_root),
            prepared_root="",
            data_mounts=data_mounts,
            prepared_contract={
                "mode": "download_only_multi",
                "datasets": datasets,
            },
            access="mixed",
            status=status,
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": status,
                "reason": reason,
                "candidate": {
                    "dataset_id": multi_id,
                    "score": max((c.score for c in selected), default=0.0),
                    "reasons": ["download_only_multi"],
                },
                "download": {
                    "status": "downloaded" if status == "prepared" else "partial",
                    "datasets": datasets,
                },
                "prepared_contract": manifest.prepared_contract,
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root,
            candidates,
            status=status,
            selected_dataset_id=multi_id,
            reason=reason,
            profile=profile,
        )
        return AcquisitionResult(
            status=status,
            manifest=manifest,
            manifest_path=manifest_path,
            candidate=selected[0] if selected else None,
            evidence_path=ev,
            reason=reason,
        )

    def _training_multi_selection(
        self,
        allowed: list[DatasetCandidate],
        profile: TaskProfile,
    ) -> list[DatasetCandidate]:
        """Select TCGA-LUAD + TCGA-LUSC for merged NSCLC MIL training."""
        if profile.task_type != "mil_classification":
            return []
        if not _is_nsclc_profile(profile):
            return []

        # Reuse aggregate-alias suppression so TCGA-LUNG remains a discovery
        # hint and never becomes a fake downloadable project.
        candidates = self._download_only_selection(allowed)
        by_label: dict[str, DatasetCandidate] = {}
        for candidate in candidates:
            label = _tcga_nsclc_label(candidate.record)
            if label and label not in by_label:
                by_label[label] = candidate

        required = ["LUAD", "LUSC"]
        if not all(label in by_label for label in required):
            return []
        return [by_label[label] for label in required]

    def _wsi_files_under(self, root: Path) -> list[Path]:
        root = Path(root)
        if not root.is_dir():
            return []
        try:
            return sorted(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in _LOCAL_WSI_EXTS
            )
        except OSError:
            return []

    def _link_or_copy(self, src: Path, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            return
        try:
            dest.symlink_to(src.resolve())
        except OSError:
            shutil.copy2(src, dest)

    def _clear_prefixed_wsi_links(self, wsi_dir: Path, prefixes: set[str]) -> None:
        if not wsi_dir.is_dir():
            return
        try:
            for child in wsi_dir.iterdir():
                if not child.is_file() and not child.is_symlink():
                    continue
                if child.suffix.lower() not in _LOCAL_WSI_EXTS:
                    continue
                if any(child.name.startswith(prefix) for prefix in prefixes):
                    child.unlink(missing_ok=True)
        except OSError:
            return

    def _failed_multi_mil_result(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates: list[DatasetCandidate],
        selected: list[DatasetCandidate],
        multi_id: str,
        multi_root: Path,
        prepared_root: Path,
        data_mounts: dict[str, str],
        datasets: list[dict[str, Any]],
        reason: str,
    ) -> AcquisitionResult:
        manifest = DatasetManifest(
            dataset_id=multi_id,
            provider="multi",
            selected_for_task=profile.task_type,
            raw_root=str(multi_root),
            prepared_root=str(prepared_root),
            data_mounts=data_mounts,
            prepared_contract={
                "mode": "multi_mil_classification",
                "datasets": datasets,
            },
            access="mixed",
            status="failed",
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": "failed",
                "reason": reason,
                "candidate": {
                    "dataset_id": multi_id,
                    "score": max((c.score for c in selected), default=0.0),
                    "reasons": ["multi_mil_classification"],
                },
                "download": {"status": "failed", "datasets": datasets},
                "prepared_contract": manifest.prepared_contract,
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root,
            candidates,
            status="failed",
            selected_dataset_id=multi_id,
            reason=reason,
            profile=profile,
        )
        return AcquisitionResult(
            status="failed",
            manifest=manifest,
            manifest_path=manifest_path,
            candidate=selected[0] if selected else None,
            evidence_path=ev,
            reason=reason,
        )

    def _multi_mil_feature_cache_hit(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates: list[DatasetCandidate],
        selected: list[DatasetCandidate],
        multi_id: str,
        multi_root: Path,
        prepared_root: Path,
        data_mounts: dict[str, str],
    ) -> AcquisitionResult | None:
        """Use an existing merged NSCLC feature cache before downloading."""
        try:
            from .readiness import assess_data_readiness
        except Exception as e:
            logger.debug("multi-MIL feature cache readiness unavailable: %s", e)
            return None
        readiness = assess_data_readiness(
            profile,
            data_mounts={str(multi_root): "/data/raw"},
        )
        if readiness.status != "features_ready":
            return None

        prepared_root.mkdir(parents=True, exist_ok=True)
        datasets = [
            {
                "dataset_id": choice.record.dataset_id,
                "name": choice.record.name,
                "provider": choice.record.provider,
                "remote_id": choice.record.download.remote_id,
                "raw_root": str(_raw_root_for_record(self._cache_root, choice.record)),
                "label": _tcga_nsclc_label(choice.record),
                "status": "prepared",
                "download_status": "cache_hit",
                "reason": "merged_feature_cache_hit",
            }
            for choice in selected
        ]
        contract: dict[str, Any] = {
            "mode": "multi_mil_classification",
            "task_type": "mil_classification",
            "features_dir": readiness.features_dir,
            "splits_file": readiness.splits_file,
            "wsi_dir": readiness.wsi_dir,
            "labels_file": readiness.labels_file,
            "features_dir_host": readiness.features_dir_host,
            "splits_file_host": readiness.splits_file_host,
            "wsi_dir_host": readiness.wsi_dir_host,
            "labels_file_host": readiness.labels_file_host,
            "requires_feature_extraction": False,
            "data_mounts": data_mounts,
            "datasets": datasets,
            "label_semantics": "tcga_project_subtype",
            "label_resolution_skill": "tcga_label_resolution",
            "split_group": "case_submitter_id",
        }
        manifest = DatasetManifest(
            dataset_id=multi_id,
            provider="multi",
            selected_for_task=profile.task_type,
            raw_root=str(multi_root),
            prepared_root=str(prepared_root),
            data_mounts=data_mounts,
            prepared_contract={
                k: str(v) if not isinstance(v, (dict, list, bool)) else v
                for k, v in contract.items()
            },
            access="mixed",
            status="prepared",
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": "prepared",
                "reason": "multi_mil_feature_cache_hit",
                "candidate": {
                    "dataset_id": multi_id,
                    "score": max((c.score for c in selected), default=0.0),
                    "reasons": ["multi_mil_classification"],
                },
                "download": {
                    "status": "cache_hit",
                    "datasets": datasets,
                },
                "prepared_contract": manifest.prepared_contract,
                "data_readiness": readiness.to_dict(),
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root,
            candidates,
            status="prepared",
            selected_dataset_id=multi_id,
            reason="multi_mil_feature_cache_hit",
            profile=profile,
        )
        return AcquisitionResult(
            status="prepared",
            manifest=manifest,
            manifest_path=manifest_path,
            candidate=selected[0] if selected else None,
            evidence_path=ev,
            reason="multi_mil_feature_cache_hit",
        )

    def _multi_mil_training_result(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates: list[DatasetCandidate],
        selected: list[DatasetCandidate],
    ) -> AcquisitionResult:
        """Download TCGA NSCLC cohorts and expose one merged MIL contract."""
        selected_ids = [c.record.dataset_id for c in selected]
        multi_id = "multi:" + "+".join(safe_dataset_id(s) for s in selected_ids)
        multi_root = self._cache_root / "TCGA-NSCLC"
        merged_wsi_dir = multi_root / "WSIs"
        prepared_root = _prepared_root_for_workspace(
            workspace_root,
            normalizer_name="mil_classification",
        )
        data_mounts = {
            str(prepared_root): "/data",
            str(multi_root): "/data/raw",
        }

        cache_hit = self._multi_mil_feature_cache_hit(
            profile=profile,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
            candidates=candidates,
            selected=selected,
            multi_id=multi_id,
            multi_root=multi_root,
            prepared_root=prepared_root,
            data_mounts=data_mounts,
        )
        if cache_hit is not None:
            return cache_hit

        self._write_plan(
            workspace_root,
            candidates,
            status="planned",
            selected_dataset_id=multi_id,
            reason="before_download_multi_mil",
            profile=profile,
        )

        datasets: list[dict[str, Any]] = []
        failures: list[str] = []
        raw_roots: dict[str, Path] = {}
        total = len(selected)
        selected_labels = {
            f"{_tcga_nsclc_label(c.record)}__"
            for c in selected
            if _tcga_nsclc_label(c.record)
        }
        merged_wsi_dir.mkdir(parents=True, exist_ok=True)
        prepared_root.mkdir(parents=True, exist_ok=True)
        self._clear_prefixed_wsi_links(merged_wsi_dir, selected_labels)

        for index, choice in enumerate(selected, start=1):
            record = choice.record
            label = _tcga_nsclc_label(record)
            raw_root = _raw_root_for_record(self._cache_root, record)
            raw_root.mkdir(parents=True, exist_ok=True)
            provider = self._providers.get(record.provider)
            files: list[Path] = []
            checksum_sha256 = ""
            download_status = "failed"
            reason = ""
            completeness: dict[str, Any] = {}

            local_hit, local_files, completeness, local_reason = self._download_only_local_hit(
                record=record,
                provider=provider,
                raw_root=raw_root,
            )
            if local_hit:
                files = local_files
                download_status = "local_hit"
                reason = local_reason
            elif provider is None:
                reason = f"no_provider:{record.provider}"
            else:
                progress = DownloadProgressReporter(
                    download_progress_path_for_workspace(workspace_root),
                    dataset_id=record.dataset_id,
                    provider=record.provider,
                    raw_root=raw_root,
                )
                progress.start(extra={
                    "multi_dataset_id": multi_id,
                    "multi_dataset_index": index,
                    "multi_dataset_total": total,
                    "multi_dataset_ids": selected_ids,
                    "multi_dataset_mode": "multi_mil_classification",
                })
                try:
                    download_result = self._provider_download(
                        provider,
                        record,
                        raw_root,
                        progress,
                    )
                    download_status = download_result.status
                    reason = download_result.reason or ""
                    files = list(download_result.files or [])
                    checksum_sha256 = download_result.checksum_sha256 or ""
                except Exception as e:
                    download_status = "failed"
                    reason = f"download_error:{e}"
                progress.finish(download_status, reason=reason)

            if download_status == "downloaded":
                expected_checksum = (record.download.checksum_sha256 or "").lower()
                actual_checksum = (checksum_sha256 or "").lower()
                if expected_checksum and actual_checksum and actual_checksum != expected_checksum:
                    download_status = "failed"
                    reason = (
                        "checksum_mismatch:"
                        f"expected={expected_checksum},actual={actual_checksum}"
                    )
                else:
                    for f in files:
                        if _looks_like_archive(f):
                            try:
                                extract_archive(f, raw_root)
                            except Exception as e:
                                logger.warning(
                                    "Archive extraction failed for %s: %s", f, e,
                                )

            prepared = download_status in {"downloaded", "local_hit"}
            slide_files = self._wsi_files_under(raw_root) if prepared else []
            if prepared and not slide_files:
                download_status = "failed"
                reason = "no_wsi_files"
                prepared = False

            dataset_entry = {
                "dataset_id": record.dataset_id,
                "name": record.name,
                "provider": record.provider,
                "remote_id": record.download.remote_id,
                "raw_root": str(raw_root),
                "label": label,
                "status": "prepared" if prepared else "failed",
                "download_status": download_status,
                "reason": reason,
                "files": [str(p) for p in files],
                "n_wsi": len(slide_files),
            }
            if completeness:
                dataset_entry["completeness"] = completeness
            if checksum_sha256:
                dataset_entry["checksum_sha256"] = checksum_sha256
            datasets.append(dataset_entry)
            raw_roots[record.dataset_id] = raw_root

            if not prepared:
                failures.append(f"{record.dataset_id}:{reason or download_status}")
                continue

            write_acquisition_record(
                workspace_root,
                {
                    "status": "prepared",
                    "reason": "multi_mil_dataset_prepared",
                    "candidate": {
                        "dataset_id": record.dataset_id,
                        "score": choice.score,
                        "reasons": choice.reasons,
                    },
                    "download": {
                        "status": download_status,
                        "files": [str(p) for p in files],
                    },
                    "task_profile": profile.to_dict(),
                },
            )

        if failures:
            return self._failed_multi_mil_result(
                profile=profile,
                workspace_root=workspace_root,
                manifest_path=manifest_path,
                candidates=candidates,
                selected=selected,
                multi_id=multi_id,
                multi_root=multi_root,
                prepared_root=prepared_root,
                data_mounts=data_mounts,
                datasets=datasets,
                reason="multi_mil_partial:" + ";".join(failures),
            )

        try:
            from .labels.tcga import TCGALabelResolutionSkill

            label_result = TCGALabelResolutionSkill().resolve(
                profile=profile,
                selected_records=[choice.record for choice in selected],
                raw_roots=raw_roots,
                workspace_root=workspace_root,
                merged_wsi_dir=merged_wsi_dir,
            )
        except (OSError, ValueError) as e:
            return self._failed_multi_mil_result(
                profile=profile,
                workspace_root=workspace_root,
                manifest_path=manifest_path,
                candidates=candidates,
                selected=selected,
                multi_id=multi_id,
                multi_root=multi_root,
                prepared_root=prepared_root,
                data_mounts=data_mounts,
                datasets=datasets,
                reason=f"multi_mil_label_error:{e}",
            )
        if label_result.status != "prepared":
            return self._failed_multi_mil_result(
                profile=profile,
                workspace_root=workspace_root,
                manifest_path=manifest_path,
                candidates=candidates,
                selected=selected,
                multi_id=multi_id,
                multi_root=multi_root,
                prepared_root=prepared_root,
                data_mounts=data_mounts,
                datasets=datasets,
                reason=f"multi_mil_label_error:{label_result.reason}",
            )

        contract: dict[str, Any] = {
            "mode": "multi_mil_classification",
            "task_type": "mil_classification",
            "wsi_dir": label_result.wsi_dir,
            "labels_file": label_result.labels_file,
            "splits_file": label_result.splits_file,
            "label_provenance_file": label_result.provenance_file,
            "patient_groups_file": label_result.patient_groups_file,
            "requires_feature_extraction": True,
            "data_mounts": data_mounts,
            "datasets": datasets,
            "label_semantics": label_result.label_semantics,
            "label_resolution_skill": "tcga_label_resolution",
            "split_group": "case_submitter_id",
            "n_slides": label_result.n_slides,
            "n_labeled": label_result.n_labeled,
            "label_coverage": label_result.label_coverage,
            "class_counts": label_result.class_counts,
        }
        contract, readiness_reason, readiness_payload = self._validate_prepared_contract(
            profile=profile,
            contract=contract,
            workspace_root=workspace_root,
        )
        if readiness_reason:
            return self._failed_multi_mil_result(
                profile=profile,
                workspace_root=workspace_root,
                manifest_path=manifest_path,
                candidates=candidates,
                selected=selected,
                multi_id=multi_id,
                multi_root=multi_root,
                prepared_root=prepared_root,
                data_mounts=data_mounts,
                datasets=datasets,
                reason=readiness_reason,
            )

        manifest = DatasetManifest(
            dataset_id=multi_id,
            provider="multi",
            selected_for_task=profile.task_type,
            raw_root=str(multi_root),
            prepared_root=str(prepared_root),
            data_mounts=data_mounts,
            prepared_contract={
                k: str(v) if not isinstance(v, (dict, list)) else v
                for k, v in contract.items()
            },
            access="mixed",
            status="prepared",
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": "prepared",
                "reason": "multi_mil_prepared",
                "candidate": {
                    "dataset_id": multi_id,
                    "score": max((c.score for c in selected), default=0.0),
                    "reasons": ["multi_mil_classification"],
                },
                "download": {
                    "status": "downloaded",
                    "datasets": datasets,
                },
                "prepared_contract": manifest.prepared_contract,
                "data_readiness": readiness_payload,
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root,
            candidates,
            status="prepared",
            selected_dataset_id=multi_id,
            reason="multi_mil_prepared",
            profile=profile,
        )
        return AcquisitionResult(
            status="prepared",
            manifest=manifest,
            manifest_path=manifest_path,
            candidate=selected[0] if selected else None,
            evidence_path=ev,
            reason="multi_mil_prepared",
        )

    def _check_local_completeness(
        self,
        *,
        record,
        local_root: Path,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Ask providers that can enumerate remote files whether local cache is complete."""
        provider = self._providers.get(record.provider)
        checker = getattr(provider, "local_completeness", None) if provider else None
        if checker is None:
            return True, "", {}
        try:
            payload = checker(record, local_root)
        except Exception as e:
            logger.warning(
                "local completeness check failed for %s at %s: %s",
                record.dataset_id,
                local_root,
                e,
            )
            return True, "local_completeness_error", {"error": str(e)}
        if not isinstance(payload, dict) or not payload.get("checked"):
            return True, "", payload if isinstance(payload, dict) else {}
        if payload.get("complete") is False:
            return False, "local_dataset_incomplete", payload
        return True, "", payload

    def _download_only_local_hit(
        self,
        *,
        record,
        provider: DatasetProvider | None,
        raw_root: Path,
    ) -> tuple[bool, list[Path], dict[str, Any], str]:
        """Return a complete raw-cache hit for download-only acquisitions.

        Download-only mode does not require labels/splits. For providers that
        can enumerate remote files, a complete local raw cache is enough to
        avoid a redundant provider download.
        """
        raw_root = Path(raw_root)
        if provider is None or not raw_root.is_dir():
            return False, [], {}, ""

        local_files = self._wsi_files_under(raw_root)
        if not local_files:
            return False, [], {}, ""

        complete, reason, completeness = self._check_local_completeness(
            record=record,
            local_root=raw_root,
        )
        if not completeness.get("checked"):
            return False, [], completeness, reason
        if not complete:
            return False, [], completeness, reason
        return True, local_files, completeness, "local_hit"

    def _local_match_tokens(self, record, profile: TaskProfile) -> set[str]:
        raw_parts = [
            record.dataset_id,
            record.name,
            record.dir_name(),
            record.download.remote_id,
            record.download.filename,
            " ".join(record.download.urls or []),
            " ".join(record.tags or []),
            " ".join(profile.dataset_keywords or []),
            profile.organ,
            profile.prediction_target,
            " ".join(profile.required_label_keywords or []),
        ]
        return _tokenize_local_text(raw_parts)

    def _local_identity_tokens(self, record, profile: TaskProfile) -> set[str]:
        """Strong tokens that must match for reusing local cache candidates.

        This intentionally excludes broad organ-only cues and generic words
        (``wsi``, ``mil``, ``dataset``). Local discovery may only reuse a
        prepared/raw folder for the selected registry record when the path
        carries a dataset-specific signal such as PANDA, CG-MIL, gastritis,
        Gleason, or the provider remote id.
        """
        raw_parts = [
            record.dataset_id,
            record.name,
            record.dir_name(),
            record.download.remote_id,
            record.download.filename,
            " ".join(record.download.urls or []),
            " ".join(record.tags or []),
            " ".join(profile.dataset_keywords or []),
            profile.prediction_target,
            " ".join(profile.required_label_keywords or []),
        ]
        return _tokenize_local_text(raw_parts, drop_generic=True)

    def _local_path_haystack(self, path: Path) -> str:
        path = Path(path)
        try:
            rel = path.resolve().relative_to(self._cache_root.resolve())
            parts = list(rel.parts)
        except (OSError, ValueError):
            parts = [path.parent.name, path.name]
        texts = [str(p).lower() for p in parts if str(p)]
        if parts:
            texts.append("/".join(str(p).lower() for p in parts))
        compact = [
            re.sub(r"[^a-z0-9]+", "", text)
            for text in texts
        ]
        return " ".join(texts + [c for c in compact if c])

    def _local_path_score(self, path: Path, tokens: set[str]) -> int:
        if not tokens:
            return 0
        haystack = self._local_path_haystack(path)
        return sum(1 for token in tokens if token in haystack)

    def _local_path_parts(self, path: Path) -> list[str]:
        try:
            rel = Path(path).resolve().relative_to(self._cache_root.resolve())
            return [str(p) for p in rel.parts if str(p)]
        except (OSError, ValueError):
            p = Path(path)
            return [p.parent.name, p.name]

    def _expected_gastritis_labels(self, profile: TaskProfile) -> bool:
        text = " ".join([
            profile.prediction_target or "",
            " ".join(profile.required_label_keywords or []),
            " ".join(profile.dataset_keywords or []),
        ]).lower()
        return (
            "gastritis" in text
            or "task1" in text
            or "task2" in text
            or "task3" in text
            or "task4" in text
        )

    def _local_candidate_evidence(
        self,
        *,
        path: Path,
        kind: str,
        identity_tokens: set[str],
    ) -> dict[str, Any]:
        parts = self._local_path_parts(path)
        haystack = self._local_path_haystack(path)
        matched = sorted(token for token in identity_tokens if token in haystack)
        label_columns = _find_label_columns_limited(path) if kind == "raw" else []
        return {
            "path": str(path),
            "kind": kind,
            "path_parts": parts,
            "provider_hint": _provider_hint_from_path_parts(parts),
            "matched_identity_tokens": matched,
            "identity_score": len(matched),
            "label_columns": label_columns,
        }

    def _llm_local_identity_decision(
        self,
        *,
        record,
        profile: TaskProfile,
        evidence: dict[str, Any],
    ) -> tuple[str, str]:
        if self._local_identity_llm_parser is None:
            return "reject", "local_dataset_identity_mismatch"
        selected_payload = {
            "dataset_id": record.dataset_id,
            "name": record.name,
            "provider": record.provider,
            "organs": list(record.organs or []),
            "tags": list(record.tags or []),
            "download": record.download.to_dict(),
            "task_profile": profile.to_dict(),
        }
        prompt = (
            "Decide whether a local pathology dataset folder is the same dataset "
            "as the selected registry record. Return ONLY JSON with schema "
            "{\"decision\":\"accept|reject|uncertain\","
            "\"confidence\":\"high|medium|low\",\"reason\":\"...\","
            "\"matched_dataset_identity\":\"...\",\"conflicts\":[\"...\"]}.\n"
            "Hard rule: if the local folder clearly names a different dataset, "
            "provider, organ, or label schema, reject. Accept only when the "
            "evidence strongly indicates the same dataset.\n\n"
            f"Selected dataset:\n{json.dumps(selected_payload, ensure_ascii=False, indent=2)}\n\n"
            f"Local candidate evidence:\n"
            f"{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )
        try:
            raw = self._local_identity_llm_parser(prompt) or ""
            from ..structured_output import extract_json

            payload = extract_json(raw)
        except Exception as e:
            logger.warning("local identity LLM judge failed: %s", e)
            return "reject", "local_dataset_identity_llm_error"
        if not isinstance(payload, dict):
            return "reject", "local_dataset_identity_llm_parse_error"
        decision = str(payload.get("decision", "") or "").strip().lower()
        confidence = str(payload.get("confidence", "") or "").strip().lower()
        reason = str(payload.get("reason", "") or "").strip()
        if decision == "accept" and confidence == "high":
            return "accept", "llm_identity_accept"
        if decision == "reject":
            return "reject", f"llm_identity_reject:{reason}" if reason else "llm_identity_reject"
        return "reject", "local_dataset_identity_uncertain"

    def _decide_local_candidate_identity(
        self,
        *,
        record,
        profile: TaskProfile,
        path: Path,
        kind: str,
    ) -> tuple[bool, str, dict[str, Any]]:
        identity_tokens = self._local_identity_tokens(record, profile)
        evidence = self._local_candidate_evidence(
            path=path,
            kind=kind,
            identity_tokens=identity_tokens,
        )

        provider_hint = evidence.get("provider_hint", "")
        if provider_hint and record.provider and provider_hint != record.provider:
            return False, "local_dataset_provider_mismatch", evidence

        label_columns = {str(c).strip().lower() for c in evidence.get("label_columns") or []}
        if (
            kind == "raw"
            and self._expected_gastritis_labels(profile)
            and label_columns
            and label_columns & _PROSTATE_LABEL_COLUMNS
            and not label_columns & _GASTRITIS_LABEL_COLUMNS
        ):
            return False, "local_dataset_label_schema_mismatch", evidence

        matched_identity_tokens = set(evidence.get("matched_identity_tokens") or [])
        if (
            evidence["identity_score"] > 0
            and not matched_identity_tokens <= _LOCAL_SOURCE_ONLY_TOKENS
        ):
            return True, "identity_token_match", evidence

        decision, reason = self._llm_local_identity_decision(
            record=record,
            profile=profile,
            evidence=evidence,
        )
        return decision == "accept", reason, evidence

    def _manifest_identity_mismatch_reason(
        self,
        *,
        record,
        profile: TaskProfile,
        paths: Iterable[Any],
    ) -> str:
        identity_tokens = self._local_identity_tokens(record, profile)
        if not identity_tokens:
            return ""
        for path in paths:
            if path and self._local_path_score(Path(path), identity_tokens) > 0:
                return ""
        return (
            "local_dataset_identity_mismatch:"
            f"selected_dataset_id={record.dataset_id}"
        )

    def _is_pathlab_dataset_record(self, record) -> bool:
        provider = str(getattr(record, "provider", "") or "").strip().lower()
        dataset_id = str(getattr(record, "dataset_id", "") or "").strip().lower()
        download_kind = str(getattr(getattr(record, "download", None), "kind", "") or "").strip().lower()
        return provider == "pathlab" or dataset_id.startswith("pathlab:") or download_kind == "pathlab_dataset"

    def _try_pathlab_dataset_resolver(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates,
        chosen,
    ) -> AcquisitionResult | None:
        record = chosen.record
        if not self._is_pathlab_dataset_record(record):
            return None
        if self._pathlab_dataset_resolver is None:
            return None

        try:
            payload = self._pathlab_dataset_resolver(record, profile, workspace_root)
        except Exception as exc:
            reason = f"pathlab_dataset_resolver_error:{exc}"
            manifest = DatasetManifest(
                dataset_id=record.dataset_id,
                provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root="",
                prepared_root="",
                data_mounts={},
                prepared_contract={},
                access=record.access,
                status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed",
                    "reason": reason,
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=reason,
                profile=profile,
            )
            return AcquisitionResult(
                status="failed",
                manifest=manifest,
                manifest_path=manifest_path,
                candidate=chosen,
                evidence_path=ev,
                reason=reason,
            )
        if not payload:
            return None
        contract = dict(payload.get("contract") or {})
        if not contract:
            return None
        contract, reason, readiness_payload = self._validate_prepared_contract(
            profile=profile,
            contract=contract,
            workspace_root=workspace_root,
        )
        if reason:
            manifest = DatasetManifest(
                dataset_id=record.dataset_id,
                provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(payload.get("raw_root") or ""),
                prepared_root=str(payload.get("prepared_root") or ""),
                data_mounts=dict(contract.get("data_mounts") or {}),
                prepared_contract={
                    k: str(v) if not isinstance(v, dict) else v
                    for k, v in contract.items()
                },
                access=record.access,
                status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed",
                    "reason": reason,
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "prepared_contract": manifest.prepared_contract,
                    "data_readiness": readiness_payload,
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=reason,
                profile=profile,
            )
            return AcquisitionResult(
                status="failed",
                manifest=manifest,
                manifest_path=manifest_path,
                candidate=chosen,
                evidence_path=ev,
                reason=reason,
            )

        raw_root = Path(str(payload.get("raw_root") or payload.get("prepared_root") or ""))
        prepared_root = Path(str(payload.get("prepared_root") or raw_root))
        return self._prepared_success_result(
            profile=profile,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
            candidates=candidates,
            chosen=chosen,
            raw_root=raw_root,
            prepared_root=prepared_root,
            contract=contract,
            readiness_payload=readiness_payload,
            reason=str(payload.get("reason") or "pathlab_dataset_resolved"),
            download_status="pathlab_dataset",
            local_identity_reason="llm_identity_accept",
        )

    def _iter_local_raw_candidates(
        self,
        record,
        profile: TaskProfile,
        *,
        audit_considered: list[dict[str, Any]] | None = None,
    ) -> list[tuple[Path, int, str]]:
        """Bounded scan under cache_root for already-present raw datasets.

        The cache root is treated as a unified data root, not a filesystem
        search seed. We never walk outside it and we cap both depth and count.
        """
        root = self._cache_root
        if not root.is_dir():
            return []

        tokens = self._local_match_tokens(record, profile)
        identity_tokens = self._local_identity_tokens(record, profile)
        queue: list[tuple[Path, int]] = [(root, 0)]
        seen: set[Path] = set()
        candidates: list[tuple[Path, int, str]] = []

        while queue and len(seen) < _LOCAL_SCAN_MAX_DIRS:
            current, depth = queue.pop(0)
            try:
                resolved = current.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)

            if not _is_within(root, current):
                continue
            if current != root and current.name in _LOCAL_SCAN_SKIP_DIRS:
                continue

            is_raw_candidate = _looks_like_local_raw_dataset(current)
            if is_raw_candidate:
                accepted, identity_reason, evidence = self._decide_local_candidate_identity(
                    record=record,
                    profile=profile,
                    path=current,
                    kind="raw",
                )
                identity_score = int(evidence.get("identity_score", 0) or 0)
                score = max(self._local_path_score(current, tokens), identity_score)
                if not accepted:
                    if audit_considered is not None:
                        audit_considered.append({
                            "path": str(current),
                            "kind": "raw",
                            "score": score,
                            "status": "skipped",
                            "reason": identity_reason,
                            "identity_evidence": evidence,
                        })
                    continue
                candidates.append((
                    current,
                    score,
                    identity_reason,
                ))

            if is_raw_candidate or depth >= _LOCAL_SCAN_MAX_DEPTH:
                continue
            try:
                children = sorted(
                    (p for p in current.iterdir() if p.is_dir()),
                    key=lambda p: p.name.lower(),
                )
            except OSError:
                continue
            for child in children:
                if child.name.startswith("."):
                    continue
                if child.name in _LOCAL_SCAN_SKIP_DIRS:
                    continue
                queue.append((child, depth + 1))

        # Prefer semantically matched directories. When the selected record
        # has dataset-specific identity tokens, unmatched roots were filtered
        # above; otherwise keep the legacy single-candidate fallback.
        positives = [(p, score, reason) for p, score, reason in candidates if score > 0]
        if positives:
            candidates = positives
        elif len(candidates) > 1:
            return []
        candidates.sort(key=lambda item: (-item[1], len(item[0].parts), str(item[0])))
        return candidates

    def _prepared_success_result(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates,
        chosen,
        raw_root: Path,
        prepared_root: Path,
        contract: dict[str, Any],
        readiness_payload: dict,
        reason: str,
        download_status: str,
        download_files: list[Path] | None = None,
        checksum_sha256: str = "",
        local_identity_reason: str = "",
    ) -> AcquisitionResult:
        record = chosen.record
        data_mounts = dict(contract.get("data_mounts") or {})
        identity_reason = ""
        if local_identity_reason != "llm_identity_accept":
            identity_reason = self._manifest_identity_mismatch_reason(
                record=record,
                profile=profile,
                paths=[
                    raw_root,
                    prepared_root,
                    *data_mounts.keys(),
                    contract.get("wsi_dir", ""),
                    contract.get("labels_file", ""),
                    contract.get("splits_file", ""),
                ],
            )
        if identity_reason:
            manifest = DatasetManifest(
                dataset_id=record.dataset_id,
                provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root),
                prepared_root=str(prepared_root),
                data_mounts=data_mounts,
                prepared_contract={
                    k: str(v) if not isinstance(v, dict) else v
                    for k, v in contract.items()
                },
                checksum_sha256=checksum_sha256,
                access=record.access,
                status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed",
                    "reason": identity_reason,
                    "candidate": {
                        "dataset_id": record.dataset_id,
                        "score": chosen.score,
                        "reasons": chosen.reasons,
                    },
                    "download": {
                        "status": download_status,
                        "files": [str(p) for p in (download_files or [])],
                    },
                    "local_identity_reason": local_identity_reason,
                    "prepared_contract": manifest.prepared_contract,
                    "data_readiness": readiness_payload,
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root,
                candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=identity_reason,
                profile=profile,
            )
            return AcquisitionResult(
                status="failed",
                manifest=manifest,
                manifest_path=manifest_path,
                candidate=chosen,
                evidence_path=ev,
                reason=identity_reason,
            )
        manifest = DatasetManifest(
            dataset_id=record.dataset_id,
            provider=record.provider,
            selected_for_task=profile.task_type,
            raw_root=str(raw_root),
            prepared_root=str(prepared_root),
            data_mounts=data_mounts,
            prepared_contract={
                k: str(v) if not isinstance(v, dict) else v
                for k, v in contract.items()
            },
            checksum_sha256=checksum_sha256,
            access=record.access,
            status="prepared",
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": "prepared",
                "reason": reason,
                "candidate": {
                    "dataset_id": record.dataset_id,
                    "score": chosen.score,
                    "reasons": chosen.reasons,
                },
                "download": {
                    "status": download_status,
                    "files": [str(p) for p in (download_files or [])],
                },
                "local_identity_reason": local_identity_reason,
                "prepared_contract": manifest.prepared_contract,
                "data_readiness": readiness_payload,
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root,
            candidates,
            status="prepared",
            selected_dataset_id=record.dataset_id,
            reason=reason,
            profile=profile,
        )
        return AcquisitionResult(
            status="prepared",
            manifest=manifest,
            manifest_path=manifest_path,
            candidate=chosen,
            evidence_path=ev,
            reason=reason,
        )

    def _try_local_discovery(
        self,
        *,
        profile: TaskProfile,
        workspace_root: Path,
        manifest_path: Path,
        candidates,
        chosen,
    ) -> AcquisitionResult | None:
        """Try existing prepared/raw data under cache_root before downloads."""
        record = chosen.record
        audit: dict[str, Any] = {
            "status": "not_found",
            "reason": "no_ready_local_dataset",
            "cache_root": str(self._cache_root),
            "selected_dataset_id": record.dataset_id,
            "task_profile": profile.to_dict(),
            "considered": [],
        }

        normalizer = self._select_normalizer(profile.task_type)
        if normalizer is None:
            audit["reason"] = f"no_normalizer:{profile.task_type}"
            self._write_local_discovery(workspace_root, audit)
            return None

        # DC-2 + DT-1 (2026-05-10/05-12): split data vs task layer.
        # Raw data stays in the persistent cache; task-shaped artifacts
        # (labels/splits/symlinks) live in the per-session workspace.
        raw_root = _raw_root_for_record(self._cache_root, record)
        prepared_root = _prepared_root_for_workspace(
            workspace_root, normalizer_name=normalizer.name,
        )
        tokens = self._local_match_tokens(record, profile)
        identity_tokens = self._local_identity_tokens(record, profile)

        # 1. Exact prepared cache for this registry record.
        cached_contract = self._existing_prepared_contract(
            normalizer=normalizer,
            profile=profile,
            prepared_root=prepared_root,
        )
        if cached_contract:
            cached_contract, cache_reason, readiness_payload = self._validate_prepared_contract(
                profile=profile,
                contract=cached_contract,
                workspace_root=workspace_root,
            )
            audit["considered"].append({
                "path": str(prepared_root),
                "kind": "prepared_cache",
                "status": "not_ready" if cache_reason else "ready",
                "reason": cache_reason or "cache_hit",
                "prepared_root": str(prepared_root),
            })
            if not cache_reason:
                audit["status"] = "prepared"
                audit["reason"] = "cache_hit"
                self._write_local_discovery(workspace_root, audit)
                return self._prepared_success_result(
                    profile=profile,
                    workspace_root=workspace_root,
                    manifest_path=manifest_path,
                    candidates=candidates,
                    chosen=chosen,
                    raw_root=raw_root,
                    prepared_root=prepared_root,
                    contract=cached_contract,
                    readiness_payload=readiness_payload,
                    reason="cache_hit",
                    download_status="cache_hit",
                )

        # 2. Other already-prepared datasets under the same unified root.
        # DC-2 (2026-05-10): scan ``<cache>/<dataset_dir>/prepared/<normalizer>/``
        # across all dataset folders, instead of the legacy flat
        # ``<cache>/prepared/<normalizer>/<id>/`` layout.
        prepared_candidates: list[tuple[Path, int, dict[str, Any], str]] = []
        if self._cache_root.is_dir():
            for dataset_dir in sorted(self._cache_root.iterdir()):
                if not dataset_dir.is_dir():
                    continue
                prepared_candidate = (
                    dataset_dir / "prepared" / normalizer.name
                )
                if (
                    not prepared_candidate.is_dir()
                    or prepared_candidate == prepared_root
                ):
                    continue
                contract = self._existing_prepared_contract(
                    normalizer=normalizer,
                    profile=profile,
                    prepared_root=prepared_candidate,
                )
                if not contract:
                    continue
                accepted, identity_reason, identity_evidence = self._decide_local_candidate_identity(
                    record=record,
                    profile=profile,
                    path=prepared_candidate,
                    kind="prepared",
                )
                identity_score = int(identity_evidence.get("identity_score", 0) or 0)
                if not accepted:
                    audit["considered"].append({
                        "path": str(prepared_candidate),
                        "kind": "prepared",
                        "score": self._local_path_score(prepared_candidate, tokens),
                        "status": "skipped",
                        "reason": identity_reason,
                        "prepared_root": str(prepared_candidate),
                        "identity_evidence": identity_evidence,
                    })
                    continue
                score = max(
                    self._local_path_score(prepared_candidate, tokens),
                    identity_score,
                )
                prepared_candidates.append((
                    prepared_candidate,
                    score,
                    contract,
                    identity_reason,
                ))
        if prepared_candidates:

            positive_prepared = [
                item for item in prepared_candidates if item[1] > 0
            ]
            if positive_prepared:
                prepared_candidates = positive_prepared
            elif len(prepared_candidates) > 1:
                for prepared_candidate, score, _contract, _identity_reason in prepared_candidates:
                    audit["considered"].append({
                        "path": str(prepared_candidate),
                        "kind": "prepared",
                        "score": score,
                        "status": "skipped",
                        "reason": "ambiguous_unmatched_prepared_candidate",
                        "prepared_root": str(prepared_candidate),
                    })
                prepared_candidates = []

            for prepared_candidate, score, contract, identity_reason in prepared_candidates:
                contract, reason, readiness_payload = self._validate_prepared_contract(
                    profile=profile,
                    contract=contract,
                    workspace_root=workspace_root,
                )
                audit["considered"].append({
                    "path": str(prepared_candidate),
                    "kind": "prepared",
                    "score": score,
                    "status": "not_ready" if reason else "ready",
                    "reason": reason or "local_hit",
                    "prepared_root": str(prepared_candidate),
                })
                if not reason:
                    audit["status"] = "prepared"
                    audit["reason"] = "local_hit"
                    self._write_local_discovery(workspace_root, audit)
                    return self._prepared_success_result(
                        profile=profile,
                        workspace_root=workspace_root,
                        manifest_path=manifest_path,
                        candidates=candidates,
                        chosen=chosen,
                        raw_root=prepared_candidate,
                        prepared_root=prepared_candidate,
                        contract=contract,
                        readiness_payload=readiness_payload,
                        reason="local_hit",
                        download_status="local_hit",
                        local_identity_reason=identity_reason,
                    )

        # 3. Raw-like local datasets. Normalize into the per-session
        # prepared/ root under workspace (DT-1, 2026-05-12). Pre-DT-1
        # the prepared output lived under ``<cache>/<dataset>/prepared/<norm>/``
        # which polluted the user's dataset folder with task-shaped
        # artifacts (labels, splits, symlinks). Now the task layer
        # lives strictly under workspace, keeping cache data-only.
        for local_raw, score, identity_reason in self._iter_local_raw_candidates(
            record,
            profile,
            audit_considered=audit["considered"],
        ):
            local_prepared = _prepared_root_for_workspace(
                workspace_root, normalizer_name=normalizer.name,
            )
            item = {
                "path": str(local_raw),
                "kind": "raw",
                "score": score,
                "status": "skipped",
                "reason": identity_reason,
                "prepared_root": str(local_prepared),
            }
            complete, completeness_reason, completeness = self._check_local_completeness(
                record=record,
                local_root=local_raw,
            )
            if completeness:
                item["completeness"] = completeness
            if not complete:
                item.update({
                    "status": "skipped",
                    "reason": completeness_reason,
                })
                audit["considered"].append(item)
                continue
            try:
                contract = normalizer.prepare(local_raw, local_prepared)
                contract, reason, readiness_payload = self._validate_prepared_contract(
                    profile=profile,
                    contract=dict(contract),
                    workspace_root=workspace_root,
                )
            except NormalizerError as e:
                item.update({"status": "normalize_empty", "reason": str(e)})
                audit["considered"].append(item)
                continue
            except Exception as e:
                item.update({"status": "normalize_error", "reason": str(e)})
                audit["considered"].append(item)
                continue

            if reason:
                item.update({"status": "not_ready", "reason": reason})
                audit["considered"].append(item)
                continue

            item.update({"status": "ready", "reason": "local_hit"})
            audit["considered"].append(item)
            audit["status"] = "prepared"
            audit["reason"] = "local_hit"
            self._write_local_discovery(workspace_root, audit)
            return self._prepared_success_result(
                profile=profile,
                workspace_root=workspace_root,
                manifest_path=manifest_path,
                candidates=candidates,
                chosen=chosen,
                raw_root=local_raw,
                prepared_root=local_prepared,
                contract=contract,
                readiness_payload=readiness_payload,
                reason="local_hit",
                download_status="local_hit",
                local_identity_reason=identity_reason,
            )

        self._write_local_discovery(workspace_root, audit)
        return None

    def acquire(self, profile: TaskProfile, workspace_root: Path) -> AcquisitionResult:
        workspace_root = Path(workspace_root)
        manifest_path = manifest_path_for_workspace(workspace_root)

        # Plan-2026-04-30 dataset-discovery T6: probe each registry record
        # before scout sees it. Probe never upgrades access; it only annotates
        # tags so downstream evidence reflects what was checked.
        all_records = self._probe_records(self._registry.load())

        semantic_matcher = DatasetSemanticMatcher(self._local_identity_llm_parser)
        scout = DatasetScout(
            self._registry,
            policy=self._policy,
            semantic_matcher=semantic_matcher,
        )
        candidates = scout.find_candidates(profile, top_k=10, records=all_records)

        # 1. No candidates at all
        if not candidates:
            manifest = self._empty_manifest("failed", "no_candidate", workspace_root)
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {"status": "failed", "reason": "no_candidate", "task_profile": profile.to_dict()},
            )
            self._write_plan(
                workspace_root, [],
                status="failed", reason="no_candidate", profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                evidence_path=ev, reason="no_candidate",
            )

        # 2. Filter by relevance first (Review fix R2 / P1 #3): a candidate
        #    must demonstrate task-shape compatibility before it's eligible,
        #    so we never pick a public-but-unrelated dataset over a relevant
        #    gated one.
        relevant_candidates = [c for c in candidates if c.relevant]
        if not relevant_candidates:
            manifest = self._empty_manifest("failed", "no_relevant_candidate", workspace_root)
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed", "reason": "no_relevant_candidate",
                    "task_profile": profile.to_dict(),
                    "considered": [
                        {"dataset_id": c.record.dataset_id, "score": c.score, "reasons": c.reasons}
                        for c in candidates
                    ],
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed", reason="no_relevant_candidate",
                profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                evidence_path=ev, reason="no_relevant_candidate",
            )

        multi_training_candidates = self._training_multi_selection(
            [c for c in relevant_candidates if c.decision.allowed],
            profile,
        )

        # 2b. Local-first acquisition. The configured cache root is treated
        # as the user's unified data root: if a ready matching dataset already
        # exists there, use it before applying download-only policy gates.
        #
        # NSCLC multi-cohort training is intentionally excluded from this
        # single-candidate shortcut; otherwise a ready LUAD cache could block
        # the required LUAD+LUSC merged contract.
        if not multi_training_candidates:
            for local_choice in relevant_candidates:
                local_result = self._try_local_discovery(
                    profile=profile,
                    workspace_root=workspace_root,
                    manifest_path=manifest_path,
                    candidates=candidates,
                    chosen=local_choice,
                )
                if local_result is not None:
                    return local_result

        # 3. Pick first allowed candidate from the relevant set
        allowed = [c for c in relevant_candidates if c.decision.allowed]
        if not allowed:
            # Best relevant candidate is policy-blocked: report skipped_policy.
            top = relevant_candidates[0]   # already sorted by score desc
            manifest = DatasetManifest(
                dataset_id=top.record.dataset_id,
                provider=top.record.provider,
                selected_for_task=profile.task_type,
                raw_root="", prepared_root="",
                data_mounts={}, prepared_contract={},
                access=top.record.access,
                status="skipped_policy",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "skipped_policy",
                    "reason": top.decision.reason,
                    "candidate": {
                        "dataset_id": top.record.dataset_id,
                        "score": top.score,
                        "reasons": top.reasons,
                    },
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="skipped_policy", reason=top.decision.reason,
                selected_dataset_id=top.record.dataset_id,
                profile=profile,
            )
            return AcquisitionResult(
                status="skipped_policy", manifest=manifest, manifest_path=manifest_path,
                candidate=top, evidence_path=ev, reason=top.decision.reason,
            )

        if self._download_only:
            selected_for_download = self._download_only_selection(allowed)
            if len(selected_for_download) > 1:
                return self._download_only_multi_result(
                    profile=profile,
                    workspace_root=workspace_root,
                    manifest_path=manifest_path,
                    candidates=candidates,
                    selected=selected_for_download,
                )
        else:
            selected_for_training = (
                multi_training_candidates
                or self._training_multi_selection(allowed, profile)
            )
            if len(selected_for_training) > 1:
                return self._multi_mil_training_result(
                    profile=profile,
                    workspace_root=workspace_root,
                    manifest_path=manifest_path,
                    candidates=candidates,
                    selected=selected_for_training,
                )

        chosen = allowed[0]
        record = chosen.record

        pathlab_result = self._try_pathlab_dataset_resolver(
            profile=profile,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
            candidates=candidates,
            chosen=chosen,
        )
        if pathlab_result is not None:
            return pathlab_result

        if (
            profile.task_type == "mil_classification"
            and _is_nsclc_profile(profile)
            and _tcga_nsclc_label(record)
        ):
            reason = "tcga_nsclc_requires_luad_lusc"
            manifest = DatasetManifest(
                dataset_id=record.dataset_id,
                provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root="",
                prepared_root="",
                data_mounts={},
                prepared_contract={},
                access=record.access,
                status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed",
                    "reason": reason,
                    "candidate": {
                        "dataset_id": record.dataset_id,
                        "score": chosen.score,
                        "reasons": chosen.reasons,
                    },
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root,
                candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=reason,
                profile=profile,
            )
            return AcquisitionResult(
                status="failed",
                manifest=manifest,
                manifest_path=manifest_path,
                candidate=chosen,
                evidence_path=ev,
                reason=reason,
            )

        # 3. Provider download
        provider = self._providers.get(record.provider)
        if provider is None:
            manifest = DatasetManifest(
                dataset_id=record.dataset_id, provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root="", prepared_root="",
                data_mounts={}, prepared_contract={},
                access=record.access, status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed", "reason": f"no_provider:{record.provider}",
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=f"no_provider:{record.provider}",
                profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                candidate=chosen, evidence_path=ev,
                reason=f"no_provider:{record.provider}",
            )

        # DC-2 + DT-1 (2026-05-10/05-12): raw under cache, prepared under workspace.
        raw_root = _raw_root_for_record(self._cache_root, record)
        normalizer_for_cache = self._select_normalizer(profile.task_type)
        if normalizer_for_cache is not None:
            prepared_root_for_cache = _prepared_root_for_workspace(
                workspace_root,
                normalizer_name=normalizer_for_cache.name,
            )
            cached_contract = self._existing_prepared_contract(
                normalizer=normalizer_for_cache,
                profile=profile,
                prepared_root=prepared_root_for_cache,
            )
            if cached_contract:
                cached_contract, cache_reason, readiness_payload = self._validate_prepared_contract(
                    profile=profile,
                    contract=cached_contract,
                    workspace_root=workspace_root,
                )
                if not cache_reason:
                    data_mounts = dict(cached_contract.get("data_mounts") or {})
                    manifest = DatasetManifest(
                        dataset_id=record.dataset_id, provider=record.provider,
                        selected_for_task=profile.task_type,
                        raw_root=str(raw_root),
                        prepared_root=str(prepared_root_for_cache),
                        data_mounts=data_mounts,
                        prepared_contract={
                            k: str(v) if not isinstance(v, dict) else v
                            for k, v in cached_contract.items()
                        },
                        access=record.access, status="prepared",
                    )
                    save_manifest(manifest_path, manifest)
                    ev = write_acquisition_record(
                        workspace_root,
                        {
                            "status": "prepared",
                            "reason": "cache_hit",
                            "candidate": {
                                "dataset_id": record.dataset_id,
                                "score": chosen.score,
                                "reasons": chosen.reasons,
                            },
                            "download": {"status": "cache_hit", "files": []},
                            "prepared_contract": manifest.prepared_contract,
                            "data_readiness": readiness_payload,
                            "task_profile": profile.to_dict(),
                        },
                    )
                    self._write_plan(
                        workspace_root, candidates,
                        status="prepared",
                        selected_dataset_id=record.dataset_id,
                        reason="cache_hit",
                        profile=profile,
                    )
                    return AcquisitionResult(
                        status="prepared", manifest=manifest,
                        manifest_path=manifest_path,
                        candidate=chosen, evidence_path=ev,
                        reason="cache_hit",
                    )

        raw_root.mkdir(parents=True, exist_ok=True)

        if self._download_only:
            local_hit, local_files, completeness, local_reason = self._download_only_local_hit(
                record=record,
                provider=provider,
                raw_root=raw_root,
            )
            if local_hit:
                data_mounts = {str(raw_root): "/data/raw"}
                manifest = DatasetManifest(
                    dataset_id=record.dataset_id,
                    provider=record.provider,
                    selected_for_task=profile.task_type,
                    raw_root=str(raw_root),
                    prepared_root="",
                    data_mounts=data_mounts,
                    prepared_contract={
                        "mode": "download_only",
                        "raw_root": str(raw_root),
                        "downloaded_files": [str(p) for p in local_files],
                        "download_status": "local_hit",
                        "n_wsi": len(local_files),
                        "local_completeness": completeness,
                    },
                    access=record.access,
                    status="prepared",
                )
                save_manifest(manifest_path, manifest)
                ev = write_acquisition_record(
                    workspace_root,
                    {
                        "status": "prepared",
                        "reason": "download_only",
                        "candidate": {
                            "dataset_id": record.dataset_id,
                            "score": chosen.score,
                            "reasons": chosen.reasons,
                        },
                        "download": {
                            "status": "local_hit",
                            "files": [str(p) for p in local_files],
                            "local_completeness": completeness,
                        },
                        "prepared_contract": manifest.prepared_contract,
                        "task_profile": profile.to_dict(),
                    },
                )
                self._write_plan(
                    workspace_root,
                    candidates,
                    status="prepared",
                    selected_dataset_id=record.dataset_id,
                    reason="download_only_local_hit",
                    profile=profile,
                )
                return AcquisitionResult(
                    status="prepared",
                    manifest=manifest,
                    manifest_path=manifest_path,
                    candidate=chosen,
                    evidence_path=ev,
                    reason="download_only",
                )

        # Plan-2026-04-30 dataset-provider-repair Task 0 / blocker #1:
        # write a provisional "planned" plan BEFORE the download fires.
        # If download() takes minutes / hangs / crashes, reviewers under
        # --stop-before-execution still have a complete audit artifact.
        self._write_plan(
            workspace_root, candidates,
            status="planned",
            selected_dataset_id=record.dataset_id,
            reason="before_download",
            profile=profile,
        )

        progress = DownloadProgressReporter(
            download_progress_path_for_workspace(workspace_root),
            dataset_id=record.dataset_id,
            provider=record.provider,
            raw_root=raw_root,
        )
        progress.start()
        download_result: DownloadResult = self._provider_download(
            provider,
            record,
            raw_root,
            progress,
        )
        progress.finish(
            download_result.status,
            reason=download_result.reason or "",
        )

        if download_result.status not in ("downloaded",):
            manifest = DatasetManifest(
                dataset_id=record.dataset_id, provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root), prepared_root="",
                data_mounts={}, prepared_contract={},
                access=record.access,
                status="skipped_policy" if download_result.status == "skipped_policy" else "failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": manifest.status, "reason": download_result.reason,
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "download": {"status": download_result.status, "files": [str(p) for p in download_result.files]},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status=manifest.status,
                selected_dataset_id=record.dataset_id,
                reason=download_result.reason or "",
                profile=profile,
            )
            return AcquisitionResult(
                status=manifest.status, manifest=manifest, manifest_path=manifest_path,
                candidate=chosen, evidence_path=ev, reason=download_result.reason,
            )

        # 3b. Verify checksum if record specifies one (Review fix R6 / P2 #7).
        expected_checksum = (record.download.checksum_sha256 or "").lower()
        actual_checksum = (download_result.checksum_sha256 or "").lower()
        if expected_checksum:
            if not actual_checksum:
                # Provider didn't compute one (e.g., multi-file). For v1, treat
                # as unverifiable rather than failing - record it for the manifest.
                logger.info(
                    "Provider did not compute checksum for %s; expected=%s",
                    record.dataset_id, expected_checksum,
                )
            elif actual_checksum != expected_checksum:
                manifest = DatasetManifest(
                    dataset_id=record.dataset_id, provider=record.provider,
                    selected_for_task=profile.task_type,
                    raw_root=str(raw_root), prepared_root="",
                    data_mounts={}, prepared_contract={},
                    access=record.access, status="failed",
                )
                save_manifest(manifest_path, manifest)
                reason = f"checksum_mismatch:expected={expected_checksum},actual={actual_checksum}"
                ev = write_acquisition_record(
                    workspace_root,
                    {
                        "status": "failed",
                        "reason": reason,
                        "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                        "task_profile": profile.to_dict(),
                    },
                )
                self._write_plan(
                    workspace_root, candidates,
                    status="failed",
                    selected_dataset_id=record.dataset_id,
                    reason=reason,
                    profile=profile,
                )
                return AcquisitionResult(
                    status="failed", manifest=manifest, manifest_path=manifest_path,
                    candidate=chosen, evidence_path=ev,
                    reason=reason,
                )

        # 4. Extract archives if needed
        for f in list(download_result.files):
            if _looks_like_archive(f):
                try:
                    extract_archive(f, raw_root)
                except Exception as e:
                    logger.warning("Archive extraction failed for %s: %s", f, e)
                    # Don't bail on extraction failure; let the normalizer
                    # try with whatever was extracted.

        if self._download_only:
            data_mounts = {str(raw_root): "/data/raw"}
            manifest = DatasetManifest(
                dataset_id=record.dataset_id,
                provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root),
                prepared_root="",
                data_mounts=data_mounts,
                prepared_contract={
                    "mode": "download_only",
                    "raw_root": str(raw_root),
                    "downloaded_files": [
                        str(p) for p in (download_result.files or [])
                    ],
                    "download_status": download_result.status,
                    "n_wsi": len(self._wsi_files_under(raw_root)),
                },
                checksum_sha256=download_result.checksum_sha256,
                access=record.access,
                status="prepared",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "prepared",
                    "reason": "download_only",
                    "candidate": {
                        "dataset_id": record.dataset_id,
                        "score": chosen.score,
                        "reasons": chosen.reasons,
                    },
                    "download": {
                        "status": download_result.status,
                        "files": [str(p) for p in download_result.files],
                    },
                    "prepared_contract": manifest.prepared_contract,
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root,
                candidates,
                status="prepared",
                selected_dataset_id=record.dataset_id,
                reason="download_only",
                profile=profile,
            )
            return AcquisitionResult(
                status="prepared",
                manifest=manifest,
                manifest_path=manifest_path,
                candidate=chosen,
                evidence_path=ev,
                reason="download_only",
            )

        if record.provider in {"gdc", "tcia"} and profile.task_type == "mil_classification":
            try:
                from .labels.tcga import TCGALabelResolutionSkill

                tcga_skill = TCGALabelResolutionSkill()
                label_spec = tcga_skill.plan(profile, [record])
                if label_spec.label_type == "molecular_mutation":
                    prepared_root = _prepared_root_for_workspace(
                        workspace_root,
                        normalizer_name="mil_classification",
                    )
                    label_result = tcga_skill.resolve(
                        profile=profile,
                        selected_records=[record],
                        raw_roots={record.dataset_id: raw_root},
                        workspace_root=workspace_root,
                        merged_wsi_dir=prepared_root / "WSIs",
                        label_spec=label_spec,
                    )
                    if label_result.status != "prepared":
                        raise NormalizerError(label_result.reason)
                    data_mounts = {str(prepared_root): "/data"}
                    contract = {
                        "mode": "tcga_labeled_raw_wsi",
                        "task_type": "mil_classification",
                        "wsi_dir": label_result.wsi_dir,
                        "labels_file": label_result.labels_file,
                        "splits_file": label_result.splits_file,
                        "label_provenance_file": label_result.provenance_file,
                        "patient_groups_file": label_result.patient_groups_file,
                        "requires_feature_extraction": True,
                        "data_mounts": data_mounts,
                        "label_semantics": label_result.label_semantics,
                        "label_resolution_skill": "tcga_label_resolution",
                        "split_group": "case_submitter_id",
                        "n_slides": label_result.n_slides,
                        "n_labeled": label_result.n_labeled,
                        "label_coverage": label_result.label_coverage,
                        "class_counts": label_result.class_counts,
                    }
                    contract, readiness_reason, readiness_payload = self._validate_prepared_contract(
                        profile=profile,
                        contract=contract,
                        workspace_root=workspace_root,
                    )
                    if readiness_reason:
                        raise NormalizerError(readiness_reason)
                    manifest = DatasetManifest(
                        dataset_id=record.dataset_id,
                        provider=record.provider,
                        selected_for_task=profile.task_type,
                        raw_root=str(raw_root),
                        prepared_root=str(prepared_root),
                        data_mounts=data_mounts,
                        prepared_contract={
                            k: str(v) if not isinstance(v, (dict, list)) else v
                            for k, v in contract.items()
                        },
                        checksum_sha256=download_result.checksum_sha256,
                        access=record.access,
                        status="prepared",
                    )
                    save_manifest(manifest_path, manifest)
                    ev = write_acquisition_record(
                        workspace_root,
                        {
                            "status": "prepared",
                            "reason": "tcga_label_resolution",
                            "candidate": {
                                "dataset_id": record.dataset_id,
                                "score": chosen.score,
                                "reasons": chosen.reasons,
                            },
                            "download": {
                                "status": download_result.status,
                                "files": [str(p) for p in download_result.files],
                            },
                            "prepared_contract": manifest.prepared_contract,
                            "data_readiness": readiness_payload,
                            "task_profile": profile.to_dict(),
                        },
                    )
                    self._write_plan(
                        workspace_root,
                        candidates,
                        status="prepared",
                        selected_dataset_id=record.dataset_id,
                        reason="tcga_label_resolution",
                        profile=profile,
                    )
                    return AcquisitionResult(
                        status="prepared",
                        manifest=manifest,
                        manifest_path=manifest_path,
                        candidate=chosen,
                        evidence_path=ev,
                        reason="tcga_label_resolution",
                    )
            except NormalizerError as e:
                manifest = DatasetManifest(
                    dataset_id=record.dataset_id,
                    provider=record.provider,
                    selected_for_task=profile.task_type,
                    raw_root=str(raw_root),
                    prepared_root="",
                    data_mounts={},
                    prepared_contract={},
                    access=record.access,
                    status="failed",
                )
                save_manifest(manifest_path, manifest)
                ev = write_acquisition_record(
                    workspace_root,
                    {
                        "status": "failed",
                        "reason": f"tcga_label_resolution:{e}",
                        "candidate": {
                            "dataset_id": record.dataset_id,
                            "score": chosen.score,
                            "reasons": chosen.reasons,
                        },
                        "task_profile": profile.to_dict(),
                    },
                )
                self._write_plan(
                    workspace_root,
                    candidates,
                    status="failed",
                    selected_dataset_id=record.dataset_id,
                    reason=f"tcga_label_resolution:{e}",
                    profile=profile,
                )
                return AcquisitionResult(
                    status="failed",
                    manifest=manifest,
                    manifest_path=manifest_path,
                    candidate=chosen,
                    evidence_path=ev,
                    reason=f"tcga_label_resolution:{e}",
                )

        # 5. Pick normalizer + prepare
        normalizer = self._select_normalizer(profile.task_type)
        if normalizer is None:
            manifest = DatasetManifest(
                dataset_id=record.dataset_id, provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root), prepared_root="",
                data_mounts={}, prepared_contract={},
                access=record.access, status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed", "reason": f"no_normalizer:{profile.task_type}",
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=f"no_normalizer:{profile.task_type}",
                profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                candidate=chosen, evidence_path=ev,
                reason=f"no_normalizer:{profile.task_type}",
            )

        prepared_root = _prepared_root_for_workspace(
            workspace_root,
            normalizer_name=normalizer.name,
        )
        try:
            try:
                contract = normalizer.prepare(
                    raw_root,
                    prepared_root,
                    task_profile=profile.to_dict(),
                )
            except TypeError as exc:
                if "task_profile" not in str(exc):
                    raise
                contract = normalizer.prepare(raw_root, prepared_root)
            contract, readiness_reason, readiness_payload = self._validate_prepared_contract(
                profile=profile,
                contract=dict(contract),
                workspace_root=workspace_root,
            )
            if readiness_reason:
                manifest = DatasetManifest(
                    dataset_id=record.dataset_id, provider=record.provider,
                    selected_for_task=profile.task_type,
                    raw_root=str(raw_root), prepared_root=str(prepared_root),
                    data_mounts=dict(contract.get("data_mounts") or {}),
                    prepared_contract={
                        k: str(v) if not isinstance(v, dict) else v
                        for k, v in contract.items()
                    },
                    access=record.access, status="failed",
                )
                save_manifest(manifest_path, manifest)
                ev = write_acquisition_record(
                    workspace_root,
                    {
                        "status": "failed",
                        "reason": readiness_reason,
                        "candidate": {
                            "dataset_id": record.dataset_id,
                            "score": chosen.score,
                            "reasons": chosen.reasons,
                        },
                        "prepared_contract": manifest.prepared_contract,
                        "data_readiness": readiness_payload,
                        "task_profile": profile.to_dict(),
                    },
                )
                self._write_plan(
                    workspace_root, candidates,
                    status="failed",
                    selected_dataset_id=record.dataset_id,
                    reason=readiness_reason,
                    profile=profile,
                )
                return AcquisitionResult(
                    status="failed", manifest=manifest, manifest_path=manifest_path,
                    candidate=chosen, evidence_path=ev,
                    reason=readiness_reason,
                )
        except NormalizerError as e:
            logger.warning("Normalizer rejected: %s", e)
            manifest = DatasetManifest(
                dataset_id=record.dataset_id, provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root), prepared_root=str(prepared_root),
                data_mounts={}, prepared_contract={},
                access=record.access, status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed", "reason": f"normalize_empty:{e}",
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=f"normalize_empty:{e}",
                profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                candidate=chosen, evidence_path=ev,
                reason=f"normalize_empty:{e}",
            )
        except Exception as e:
            logger.warning("Normalizer failed: %s", e)
            manifest = DatasetManifest(
                dataset_id=record.dataset_id, provider=record.provider,
                selected_for_task=profile.task_type,
                raw_root=str(raw_root), prepared_root=str(prepared_root),
                data_mounts={}, prepared_contract={},
                access=record.access, status="failed",
            )
            save_manifest(manifest_path, manifest)
            ev = write_acquisition_record(
                workspace_root,
                {
                    "status": "failed", "reason": f"normalize_error:{e}",
                    "candidate": {"dataset_id": record.dataset_id, "score": chosen.score},
                    "task_profile": profile.to_dict(),
                },
            )
            self._write_plan(
                workspace_root, candidates,
                status="failed",
                selected_dataset_id=record.dataset_id,
                reason=f"normalize_error:{e}",
                profile=profile,
            )
            return AcquisitionResult(
                status="failed", manifest=manifest, manifest_path=manifest_path,
                candidate=chosen, evidence_path=ev,
                reason=f"normalize_error:{e}",
            )

        # 6. Manifest + evidence (success path)
        data_mounts = dict(contract.get("data_mounts") or {})
        manifest = DatasetManifest(
            dataset_id=record.dataset_id, provider=record.provider,
            selected_for_task=profile.task_type,
            raw_root=str(raw_root), prepared_root=str(prepared_root),
            data_mounts=data_mounts,
            prepared_contract={k: str(v) if not isinstance(v, dict) else v for k, v in contract.items()},
            checksum_sha256=download_result.checksum_sha256,
            access=record.access, status="prepared",
        )
        save_manifest(manifest_path, manifest)
        ev = write_acquisition_record(
            workspace_root,
            {
                "status": "prepared",
                "candidate": {
                    "dataset_id": record.dataset_id,
                    "score": chosen.score,
                    "reasons": chosen.reasons,
                },
                "download": {"status": download_result.status, "files": [str(p) for p in download_result.files]},
                "prepared_contract": manifest.prepared_contract,
                "task_profile": profile.to_dict(),
            },
        )
        self._write_plan(
            workspace_root, candidates,
            status="prepared",
            selected_dataset_id=record.dataset_id,
            profile=profile,
        )
        return AcquisitionResult(
            status="prepared", manifest=manifest, manifest_path=manifest_path,
            candidate=chosen, evidence_path=ev,
        )
