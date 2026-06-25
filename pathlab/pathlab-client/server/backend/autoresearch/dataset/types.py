"""Dataset domain models — profiles, download specs, records, manifests."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskProfile:
    """Normalized task descriptor for dataset matching.

    Plan-2026-04-29 P1-6: ``prediction_target`` and
    ``required_label_keywords`` distinguish the prediction *target*
    (e.g. microsatellite instability) from the task type
    (patch_classification). Pre-fix, an MSI prompt with task_type=
    patch_classification + organ=colorectal would gladly accept
    NCT-CRC-HE-100K (a 9-class tissue dataset) because organ+task_type
    matched. Now the scout requires label-semantics overlap when these
    fields are set.
    """
    task_type: str                           # "patch_classification" | "mil_classification" | "segmentation" | "survival_analysis" | "feature_extraction"
    asset_level: str                         # "patch" | "slide" | "region"
    input_modality: str                      # "patch_images" | "wsi" | "features" | "clinical_table"
    label_granularity: str                   # "patch" | "slide" | "pixel"
    organ: str = ""
    dataset_keywords: list[str] = field(default_factory=list)
    requires_feature_extraction: bool = False
    preferred_skill: str = ""
    # Plan-2026-04-29 P1-6 — prediction-target semantics.
    prediction_target: str = ""              # canonical: "microsatellite_instability", "tumor_vs_normal", ...
    required_label_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskProfile":
        return cls(
            task_type=d.get("task_type", ""),
            asset_level=d.get("asset_level", ""),
            input_modality=d.get("input_modality", ""),
            label_granularity=d.get("label_granularity", ""),
            organ=d.get("organ", ""),
            dataset_keywords=list(d.get("dataset_keywords", []) or []),
            requires_feature_extraction=bool(d.get("requires_feature_extraction", False)),
            preferred_skill=d.get("preferred_skill", ""),
            prediction_target=d.get("prediction_target", ""),
            required_label_keywords=list(
                d.get("required_label_keywords", []) or []
            ),
        )


@dataclass
class DownloadSpec:
    """How to fetch a dataset from its provider."""
    kind: str                                # "hf_dataset" | "zenodo" | "direct_http" | "manual" | ""
    remote_id: str = ""                      # repo id / DOI / etc.
    urls: list[str] = field(default_factory=list)
    filename: str = ""
    checksum_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DownloadSpec":
        return cls(
            kind=d.get("kind", ""),
            remote_id=d.get("remote_id", ""),
            urls=list(d.get("urls", []) or []),
            filename=d.get("filename", ""),
            checksum_sha256=d.get("checksum_sha256", ""),
        )


@dataclass
class DatasetRecord:
    """A curated dataset entry."""
    dataset_id: str
    name: str
    provider: str                            # "huggingface" | "zenodo" | "direct_http" | "kaggle" | "tcia" | ...
    access: str                              # "public" | "gated" | "manual"
    task_types: list[str]
    asset_types: list[str]
    organs: list[str] = field(default_factory=list)
    license: str = ""
    estimated_size_gb: float = 0.0
    tags: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    download: DownloadSpec = field(default_factory=lambda: DownloadSpec(kind=""))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # asdict already recurses DownloadSpec; nothing special needed.
        return d

    def dir_name(self) -> str:
        """Filesystem-friendly short folder name for this dataset.

        DC-1 (2026-05-10): the cache layout is dataset-centric — every
        dataset gets its own ``<cache_root>/<dir_name>/`` containing
        ``WSIs/``, ``pt_files/``, ``labels.csv``, ``splits.json`` etc.

        Resolution order:
          1. First whitespace-delimited token of ``self.name`` (e.g.,
             "PANDA — Prostate ..." → "PANDA"). Single-token canonical
             names like "NCT-CRC-HE-100K" / "CRC-MSI" pass through.
          2. Fallback to ``safe_dataset_id(dataset_id)`` when name is
             empty or yields an unsafe slug.

        The token is stripped of unsafe path characters (``/``, ``..``,
        whitespace) so a malicious ``record.name`` cannot escape the
        cache root.
        """
        from .downloader import safe_dataset_id

        token = ""
        if self.name:
            token = self.name.strip().split()[0] if self.name.strip() else ""
        # Reject path-traversal tokens.
        if token in ("", "..", ".") or "/" in token or "\\" in token:
            token = ""
        if token:
            # Drop dots that would make this a hidden / invisible dir
            # but allow internal dots (e.g., "v1.0" datasets).
            return token.lstrip(".")
        return safe_dataset_id(self.dataset_id) if self.dataset_id else "_"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetRecord":
        return cls(
            dataset_id=d.get("dataset_id", ""),
            name=d.get("name", ""),
            provider=d.get("provider", ""),
            access=d.get("access", ""),
            task_types=list(d.get("task_types", []) or []),
            asset_types=list(d.get("asset_types", []) or []),
            organs=list(d.get("organs", []) or []),
            license=d.get("license", ""),
            estimated_size_gb=float(d.get("estimated_size_gb", 0.0) or 0.0),
            tags=list(d.get("tags", []) or []),
            source_paper_ids=list(d.get("source_paper_ids", []) or []),
            download=DownloadSpec.from_dict(d.get("download") or {}),
        )


@dataclass
class DatasetManifest:
    """Manifest written into a workspace after acquisition."""
    dataset_id: str
    provider: str
    selected_for_task: str
    raw_root: str
    prepared_root: str
    data_mounts: dict[str, str]              # host_path -> container_path
    prepared_contract: dict[str, str]        # e.g. {"images_dir": "/data/images", "splits_file": "/data/splits.json"}
    checksum_sha256: str = ""
    access: str = "public"
    status: str = "pending"                  # "pending" | "prepared" | "failed" | "skipped_policy"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetManifest":
        return cls(
            dataset_id=d.get("dataset_id", ""),
            provider=d.get("provider", ""),
            selected_for_task=d.get("selected_for_task", ""),
            raw_root=d.get("raw_root", ""),
            prepared_root=d.get("prepared_root", ""),
            data_mounts=dict(d.get("data_mounts") or {}),
            prepared_contract=dict(d.get("prepared_contract") or {}),
            checksum_sha256=d.get("checksum_sha256", ""),
            access=d.get("access", "public"),
            status=d.get("status", "pending"),
        )
