"""End-to-end dataset acquisition service.

Composes scout + provider + downloader + normalizer + manifest into one
``acquire()`` call so the orchestrator stage doesn't have to.

Pure orchestrator logic - every IO failure is captured in the resulting
manifest's ``status`` / ``reason`` rather than raised, so the upstream
acquisition stage can persist the manifest and continue.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .acquisition_plan import (
    acquisition_plan_path_for_workspace,
    candidate_to_plan_entry,
    save_acquisition_plan,
)
from .downloader import compute_sha256, extract_archive, safe_dataset_id
from .evidence import write_acquisition_record
from .manifests import manifest_path_for_workspace, save_manifest
from .normalizers.base import DatasetNormalizer, NormalizerError
from .policy import AcquisitionPolicy
from .providers.base import DatasetProvider, DownloadResult
from .registry import DatasetRegistry
from .scout import DatasetCandidate, DatasetScout
from .types import DatasetManifest, TaskProfile

logger = logging.getLogger(__name__)

_ARCHIVE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz")


def _looks_like_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in _ARCHIVE_EXTS)


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
    ):
        self._registry = registry
        self._providers = dict(providers)
        self._normalizers = list(normalizers)
        self._cache_root = Path(cache_root)
        self._policy = policy or AcquisitionPolicy()

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

    def acquire(self, profile: TaskProfile, workspace_root: Path) -> AcquisitionResult:
        workspace_root = Path(workspace_root)
        manifest_path = manifest_path_for_workspace(workspace_root)

        # Plan-2026-04-30 dataset-discovery T6: probe each registry record
        # before scout sees it. Probe never upgrades access; it only annotates
        # tags so downstream evidence reflects what was checked.
        all_records = self._probe_records(self._registry.load())

        scout = DatasetScout(self._registry, policy=self._policy)
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

        chosen = allowed[0]
        record = chosen.record

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

        raw_root = self._cache_root / "raw" / record.provider / safe_dataset_id(record.dataset_id)
        raw_root.mkdir(parents=True, exist_ok=True)

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

        download_result: DownloadResult = provider.download(record, raw_root)

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

        prepared_root = self._cache_root / "prepared" / normalizer.name / safe_dataset_id(record.dataset_id)
        try:
            contract = normalizer.prepare(raw_root, prepared_root)
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
