from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json

import pytest

from pathscientist.dataset.acquisition import AcquisitionResult, DatasetAcquisitionService
from pathscientist.dataset.policy import AcquisitionPolicy
from pathscientist.dataset.providers.base import DownloadResult
from pathscientist.dataset.registry import DatasetRegistry
from pathscientist.dataset.types import DatasetRecord, DownloadSpec, TaskProfile


# ---- fakes ----

class _FakeProvider:
    provider_name = "huggingface"

    def __init__(self, status="downloaded", reason="", files_to_create=None):
        self._status = status
        self._reason = reason
        self._files_to_create = files_to_create or []

    def probe(self, record):
        return record

    def download(self, record, target_dir):
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for fname, content in self._files_to_create:
            p = target_dir / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
            files.append(p)
        return DownloadResult(
            status=self._status, raw_root=target_dir, files=files,
            reason=self._reason,
        )


class _FakeNormalizer:
    name = "patch_classification"
    supported_task_types = {"patch_classification"}

    def supports(self, task_type):
        return task_type in self.supported_task_types

    def prepare(self, raw_root, prepared_root):
        prepared_root = Path(prepared_root)
        (prepared_root / "images").mkdir(parents=True, exist_ok=True)
        (prepared_root / "splits.json").write_text("{}")
        return {
            "task_type": "patch_classification",
            "images_dir": str(prepared_root / "images"),
            "splits_file": str(prepared_root / "splits.json"),
            "data_mounts": {str(prepared_root): "/data"},
        }


def _profile(task_type="patch_classification", organ="colorectal"):
    return TaskProfile(
        task_type=task_type, asset_level="patch",
        input_modality="patch_images", label_granularity="patch",
        organ=organ,
    )


def _registry_with(records, tmp_path) -> DatasetRegistry:
    reg = DatasetRegistry(tmp_path / "reg.json")
    reg.save(records)
    return reg


def _public_record(dataset_id="hf:demo/x"):
    return DatasetRecord(
        dataset_id=dataset_id,
        name="Demo",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="demo/x"),
    )


# ---- tests ----


def test_acquisition_no_candidate_returns_failed_manifest(tmp_path):
    reg = _registry_with([], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg, providers={}, normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert result.reason == "no_candidate"
    assert result.manifest_path.exists()
    assert json.loads(result.manifest_path.read_text())["status"] == "failed"
    assert result.evidence_path and result.evidence_path.exists()


def test_acquisition_skips_when_only_candidate_is_policy_rejected(tmp_path):
    reg = _registry_with([
        DatasetRecord(
            dataset_id="g", name="G", provider="huggingface",
            access="gated",
            task_types=["patch_classification"], asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="g"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "skipped_policy"
    assert result.manifest.status == "skipped_policy"
    assert "access=gated" in result.reason


def test_acquisition_downloads_prepares_and_writes_manifest(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(
        status="downloaded",
        files_to_create=[("data.bin", b"hello")],
    )
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "prepared"
    assert result.manifest_path.exists()
    assert result.manifest.prepared_contract["task_type"] == "patch_classification"
    assert result.manifest.data_mounts
    assert result.manifest.status == "prepared"
    assert result.evidence_path and result.evidence_path.exists()
    ev = json.loads(result.evidence_path.read_text())
    assert ev["status"] == "prepared"


def test_acquisition_failed_when_provider_returns_failed(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="failed", reason="auth")
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert "auth" in result.reason


def test_download_only_wsi_uses_pathlab_dataset_layout(tmp_path):
    rec = DatasetRecord(
        dataset_id="hf:demo/wsi",
        name="DemoWSI",
        provider="huggingface",
        access="public",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["lung"],
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="demo/wsi"),
    )
    reg = _registry_with([rec], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={
            "huggingface": _FakeProvider(
                status="downloaded",
                files_to_create=[("slide_001.svs", b"wsi")],
            )
        },
        normalizers=[],
        cache_root=tmp_path / "uploads",
        policy=AcquisitionPolicy(download_policy="all"),
        download_only=True,
    )

    result = service.acquire(_profile("mil_classification", organ="lung"), workspace_root=workspace)

    assert result.status == "prepared"
    assert Path(result.manifest.raw_root) == tmp_path / "uploads" / "DemoWSI" / "wsi_files"
    assert (tmp_path / "uploads" / "DemoWSI" / "wsi_files" / "slide_001.svs").exists()


class _FailingProvider:
    provider_name = "huggingface"

    def probe(self, record):
        return record

    def download(self, record, target_dir):
        raise AssertionError(
            "download should be skipped for feature-ready TCGA-NSCLC cache"
        )


def _tcga_record(project: str, label: str) -> DatasetRecord:
    return DatasetRecord(
        dataset_id=f"gdc:{project}",
        name=project,
        provider="huggingface",
        access="public",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["lung"],
        estimated_size_gb=1.0,
        tags=[label, "nsclc"],
        download=DownloadSpec(kind="gdc", remote_id=project),
    )


def _write_tcga_nsclc_feature_cache(root: Path) -> None:
    (root / "WSIs").mkdir(parents=True)
    (root / "features" / "virchow2").mkdir(parents=True)
    slide_ids = [
        "LUAD__slide_001",
        "LUAD__slide_002",
        "LUSC__slide_003",
        "LUSC__slide_004",
    ]
    for slide_id in slide_ids:
        (root / "WSIs" / f"{slide_id}.svs").write_text("wsi")
        (root / "features" / "virchow2" / f"{slide_id}.pt").write_bytes(b"pt")
    (root / "labels.csv").write_text(
        "slide_id,label\n"
        "LUAD__slide_001,0\n"
        "LUAD__slide_002,0\n"
        "LUSC__slide_003,1\n"
        "LUSC__slide_004,1\n",
        encoding="utf-8",
    )
    (root / "splits.json").write_text(json.dumps({
        "train": ["LUAD__slide_001", "LUSC__slide_003"],
        "val": ["LUAD__slide_002"],
        "test": ["LUSC__slide_004"],
        "labels": {
            "LUAD__slide_001": 0,
            "LUAD__slide_002": 0,
            "LUSC__slide_003": 1,
            "LUSC__slide_004": 1,
        },
    }))


def test_multi_mil_uses_existing_tcga_nsclc_feature_cache_without_download(tmp_path):
    cache_root = tmp_path / "uploads"
    nsclc_root = cache_root / "TCGA-NSCLC"
    _write_tcga_nsclc_feature_cache(nsclc_root)
    reg = _registry_with([
        _tcga_record("TCGA-LUAD", "LUAD"),
        _tcga_record("TCGA-LUSC", "LUSC"),
    ], tmp_path)
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FailingProvider()},
        normalizers=[],
        cache_root=cache_root,
        policy=AcquisitionPolicy(download_policy="all"),
        download_only=False,
    )
    profile = TaskProfile(
        task_type="mil_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
        organ="lung",
        prediction_target="nsclc_subtype",
    )

    result = service.acquire(profile, workspace_root=tmp_path / "workspace")

    assert result.status == "prepared"
    assert result.reason == "multi_mil_feature_cache_hit"
    contract = result.manifest.prepared_contract
    assert contract["features_dir"] == "/data/raw/features/virchow2"
    assert contract["splits_file"] == "/data/raw/splits.json"
    assert contract["requires_feature_extraction"] is False
    assert Path(result.manifest.prepared_root).is_dir()
    assert result.manifest.data_mounts[str(nsclc_root)] == "/data/raw"


def test_local_discovery_rejects_source_only_dataset_identity_match(tmp_path):
    """A shared source token such as Nanfang must not make NSCLC match GC-IM."""
    from pathscientist.dataset.normalizers.mil_classification import (
        MILClassificationNormalizer,
    )

    cache_root = tmp_path / "tmp_test_data"
    wrong_root = cache_root / "Nanfang-NSCLC-subset4"
    (wrong_root / "WSIs").mkdir(parents=True)
    for slide_id in ("1015654", "1015659", "1015664", "1018204"):
        (wrong_root / "WSIs" / f"{slide_id}.svs").write_text("wsi")
    (wrong_root / "labels.csv").write_text(
        "slide_id,label\n"
        "1015654,1\n"
        "1015659,0\n"
        "1015664,0\n"
        "1018204,1\n",
        encoding="utf-8",
    )
    (wrong_root / "splits.json").write_text(json.dumps({
        "train": ["1015654", "1018204"],
        "val": ["1015664"],
        "test": ["1015659"],
        "labels": {
            "1015654": 1,
            "1015659": 0,
            "1015664": 0,
            "1018204": 1,
        },
    }))
    reg = _registry_with([
        DatasetRecord(
            dataset_id="discovered:nanfang-gc-im",
            name="Nanfang-GC-IM",
            provider="manual",
            access="manual",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=["stomach"],
            tags=[
                "intestinal_metaplasia",
                "intestinal metaplasia",
                "metaplasia",
                "IM",
                "Task4",
            ],
            download=DownloadSpec(kind="manual"),
        )
    ], tmp_path)
    service = DatasetAcquisitionService(
        registry=reg,
        providers={},
        normalizers=[MILClassificationNormalizer()],
        cache_root=cache_root,
        policy=AcquisitionPolicy(download_policy="all"),
        local_identity_llm_parser=lambda _prompt: (
            '{"decision":"reject","confidence":"high",'
            '"reason":"NSCLC is not gastric intestinal metaplasia",'
            '"matched_dataset_identity":"","conflicts":["organ","target"]}'
        ),
    )
    profile = TaskProfile(
        task_type="mil_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
        organ="stomach",
        prediction_target="intestinal_metaplasia",
        dataset_keywords=["Nanfang-GC-IM", "PWH-GC-IM"],
        required_label_keywords=["intestinal_metaplasia", "IM", "Task4"],
    )

    result = service.acquire(profile, workspace_root=tmp_path / "workspace")

    assert result.status != "prepared"
    assert result.manifest.raw_root != str(wrong_root)


def test_local_discovery_prefers_canonical_pathscientist_record_over_discovered_alias(tmp_path):
    """Do not create a session-local discovered dataset when a canonical one exists."""
    from pathscientist.dataset.normalizers.mil_classification import (
        MILClassificationNormalizer,
    )

    cache_root = tmp_path / "tmp_test_data"
    pwh_root = cache_root / "PWH-GC-IM"
    (pwh_root / "WSIs").mkdir(parents=True)
    for slide_id in ("23S000033", "23S000034", "23S000035", "23S000036"):
        (pwh_root / "WSIs" / f"{slide_id}.svs").write_text("wsi")
    (pwh_root / "labels.csv").write_text(
        "slide_id,label\n"
        "23S000033,Intestinal metaplasia\n"
        "23S000034,Not Intestinal metaplasia\n"
        "23S000035,Intestinal metaplasia\n"
        "23S000036,Not Intestinal metaplasia\n",
        encoding="utf-8",
    )
    (pwh_root / "splits.json").write_text(json.dumps({
        "train": ["23S000033", "23S000034"],
        "val": ["23S000035"],
        "test": ["23S000036"],
        "labels": {
            "23S000033": 1,
            "23S000034": 0,
            "23S000035": 1,
            "23S000036": 0,
        },
    }))

    canonical = DatasetRecord(
        dataset_id="pathlab:pwh-gc-im",
        name="PathScientist PWH-GC-IM",
        provider="manual",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["stomach"],
        tags=[
            "PWH-GC-IM",
            "intestinal_metaplasia",
            "intestinal metaplasia",
            "metaplasia",
            "IM",
            "Task4",
        ],
        download=DownloadSpec(kind="manual"),
    )
    discovered = DatasetRecord(
        dataset_id="discovered:pwh-gc-im",
        name="PWH-GC-IM",
        provider="manual",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["stomach"],
        tags=[
            "PWH-GC-IM",
            "intestinal_metaplasia",
            "intestinal metaplasia",
            "metaplasia",
            "IM",
            "Task4",
            "discovered",
        ],
        download=DownloadSpec(kind="manual"),
    )
    reg = _registry_with([discovered, canonical], tmp_path)
    service = DatasetAcquisitionService(
        registry=reg,
        providers={},
        normalizers=[MILClassificationNormalizer()],
        cache_root=cache_root,
        policy=AcquisitionPolicy(download_policy="all"),
    )
    profile = TaskProfile(
        task_type="mil_classification",
        asset_level="slide",
        input_modality="wsi",
        label_granularity="slide",
        organ="stomach",
        prediction_target="intestinal_metaplasia",
        dataset_keywords=["PWH-GC-IM"],
        required_label_keywords=["intestinal_metaplasia", "IM", "Task4"],
    )

    result = service.acquire(profile, workspace_root=tmp_path / "workspace")

    assert result.status == "prepared"
    assert result.candidate is not None
    assert result.candidate.record.dataset_id == "pathlab:pwh-gc-im"
    assert result.manifest.dataset_id == "pathlab:pwh-gc-im"
    assert result.manifest.raw_root == str(pwh_root)



def test_pathlab_dataset_record_uses_resolver_instead_of_download_provider(tmp_path):
    root = tmp_path / "Nanfang-GC-IM"
    wsi_dir = root / "WSIs"
    labels = root / "labels.csv"
    splits = root / "splits.json"
    wsi_dir.mkdir(parents=True)
    for slide_id in ("slide-1", "slide-2", "slide-3", "slide-4"):
        (wsi_dir / f"{slide_id}.svs").write_text("wsi", encoding="utf-8")
    labels.write_text(
        "slide_id,label\n"
        "slide-1,0\n"
        "slide-2,1\n"
        "slide-3,0\n"
        "slide-4,1\n",
        encoding="utf-8",
    )
    splits.write_text(json.dumps({
        "train": ["slide-1", "slide-2"],
        "val": ["slide-3"],
        "test": ["slide-4"],
        "labels": {
            "slide-1": 0,
            "slide-2": 1,
            "slide-3": 0,
            "slide-4": 1,
        },
    }), encoding="utf-8")
    rec = DatasetRecord(
        dataset_id="pathlab:dataset-nanfang-gc-im",
        name="PathScientist Nanfang-GC-IM",
        provider="pathlab",
        access="manual",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["stomach"],
        tags=["Nanfang-GC-IM", "intestinal_metaplasia"],
        download=DownloadSpec(kind="pathlab_dataset", remote_id="dataset-nanfang-gc-im"),
    )
    reg = _registry_with([rec], tmp_path)

    def resolver(record, profile, workspace_root):
        assert record.dataset_id == "pathlab:dataset-nanfang-gc-im"
        assert profile.task_type == "mil_classification"
        return {
            "raw_root": str(root),
            "prepared_root": str(root),
            "contract": {
                "task_type": "mil_classification",
                "wsi_dir": str(wsi_dir),
                "labels_file": str(labels),
                "splits_file": str(splits),
                "requires_feature_extraction": True,
                "data_mounts": {str(root): "/data"},
            },
            "reason": "pathlab_dataset_resolved",
        }

    service = DatasetAcquisitionService(
        registry=reg,
        providers={},
        normalizers=[],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="all"),
        pathlab_dataset_resolver=resolver,
    )

    result = service.acquire(
        TaskProfile(
            task_type="mil_classification",
            asset_level="slide",
            input_modality="wsi",
            label_granularity="slide",
            organ="stomach",
            dataset_keywords=["Nanfang-GC-IM"],
            prediction_target="intestinal_metaplasia",
        ),
        workspace_root=tmp_path / "workspace",
    )

    assert result.status == "prepared"
    assert result.reason == "pathlab_dataset_resolved"
    assert result.manifest.dataset_id == "pathlab:dataset-nanfang-gc-im"
    assert result.manifest.provider == "pathlab"
    assert result.manifest.raw_root == str(root)
    assert result.manifest.data_mounts == {str(root): "/data"}
    assert result.manifest.prepared_contract["splits_file"] == str(splits)

def test_acquisition_failed_when_no_normalizer_supports_task(tmp_path):
    reg = _registry_with([
        DatasetRecord(
            dataset_id="x", name="X", provider="huggingface",
            access="public",
            task_types=["survival_analysis"],
            asset_types=["clinical_table"],
            organs=["lung"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],   # only patch_classification
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(
        TaskProfile(
            task_type="survival_analysis", asset_level="slide",
            input_modality="clinical_table", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "failed"
    assert "no_normalizer" in result.reason


def test_acquisition_failed_when_no_provider_for_record(tmp_path):
    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={},   # no huggingface provider registered
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert "no_provider" in result.reason


def test_acquisition_evidence_written_with_safe_id(tmp_path):
    reg = _registry_with([_public_record(dataset_id="hf:org/path")], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.evidence_path.name == "hf_org_path.json"


# ---- Review fix R2 (P1): relevance gate ----


def test_acquisition_failed_when_no_relevant_candidate(tmp_path):
    """Review P1 #3: only-irrelevant-public candidates should NOT be picked.

    Profile = survival_analysis. Registry has only a public patch dataset
    that happens to pass policy. Acquisition must return failed/no_relevant_candidate
    rather than silently selecting the wrong dataset.
    """
    reg = _registry_with([
        DatasetRecord(
            dataset_id="x", name="CRC Patches",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(
        TaskProfile(
            task_type="survival_analysis", asset_level="slide",
            input_modality="clinical_table", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "failed"
    assert result.reason == "no_relevant_candidate"


def test_acquisition_skipped_policy_cites_relevant_candidate(tmp_path):
    """Review P1 #3: when the only relevant candidate is policy-blocked,
    skipped_policy evidence should cite the relevant blocked candidate,
    not an irrelevant public one."""
    reg = _registry_with([
        # Irrelevant but public — must NOT be selected.
        DatasetRecord(
            dataset_id="public-patches", name="Public Patches",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="x"),
        ),
        # Relevant but gated.
        DatasetRecord(
            dataset_id="gated-mil", name="Gated MIL Cohort",
            provider="huggingface", access="gated",
            task_types=["mil_classification"],
            asset_types=["wsi"],
            organs=["lung"], estimated_size_gb=2.0,
            download=DownloadSpec(kind="hf_dataset", remote_id="g"),
        ),
    ], tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    result = service.acquire(
        TaskProfile(
            task_type="mil_classification", asset_level="slide",
            input_modality="wsi", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "skipped_policy"
    assert "access=gated" in result.reason
    # Evidence cites the relevant candidate, not the irrelevant public one.
    assert result.candidate is not None
    assert result.candidate.record.dataset_id == "gated-mil"


# ---- Review fix R2-followup (P1): relevant blocked candidate must not be truncated ----


def test_acquisition_finds_relevant_blocked_candidate_despite_many_irrelevant(tmp_path):
    """R2-followup: with 11 irrelevant public + 1 relevant gated, acquisition
    returns skipped_policy (citing the relevant gated record), NOT failed/no_relevant_candidate."""
    records = []
    for i in range(11):
        records.append(DatasetRecord(
            dataset_id=f"public-irrel-{i}",
            name=f"Irrelevant patch {i}",
            provider="huggingface", access="public",
            task_types=["patch_classification"],
            asset_types=["patch_images"],
            organs=["colorectal"], estimated_size_gb=1.0,
            download=DownloadSpec(kind="hf_dataset", remote_id=f"x/{i}"),
        ))
    records.append(DatasetRecord(
        dataset_id="gated-mil",
        name="Gated MIL Cohort",
        provider="huggingface", access="gated",
        task_types=["mil_classification"],
        asset_types=["wsi"],
        organs=["lung"], estimated_size_gb=2.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="g"),
    ))
    reg = _registry_with(records, tmp_path)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _FakeProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
        policy=AcquisitionPolicy(download_policy="public_only"),
    )
    result = service.acquire(
        TaskProfile(
            task_type="mil_classification", asset_level="slide",
            input_modality="wsi", label_granularity="slide", organ="lung",
        ),
        workspace_root=workspace,
    )
    assert result.status == "skipped_policy"
    assert result.candidate is not None
    assert result.candidate.record.dataset_id == "gated-mil"
    assert "access=gated" in result.reason


# ---- Review fix R3 (P1): normalizer empty-output validation ----


def test_acquisition_failed_when_normalizer_raises_normalizer_error(tmp_path):
    """Empty raw layout -> NormalizerError -> manifest.status=failed with normalize_empty reason."""
    from pathscientist.dataset.normalizers.base import NormalizerError

    class _RaisingNormalizer:
        name = "patch_classification"
        supported_task_types = {"patch_classification"}

        def supports(self, task_type):
            return task_type in self.supported_task_types

        def prepare(self, raw_root, prepared_root):
            raise NormalizerError("no_images")

    reg = _registry_with([_public_record()], tmp_path)
    workspace = tmp_path / "workspace"
    fake_provider = _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_RaisingNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert result.reason.startswith("normalize_empty:no_images")
    assert result.manifest.status == "failed"


# ---- Review fix R6 (P2): checksum verification ----


def test_acquisition_passes_when_checksum_matches(tmp_path):
    """R6: when record.download.checksum_sha256 matches the downloaded file,
    acquisition proceeds normally."""
    # SHA256 of b"hello"
    expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    rec = DatasetRecord(
        dataset_id="hf:demo/x",
        name="Demo",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=1.0,
        download=DownloadSpec(
            kind="hf_dataset", remote_id="demo/x",
            checksum_sha256=expected,
        ),
    )
    reg = _registry_with([rec], tmp_path)

    class _ChecksumProvider:
        provider_name = "huggingface"
        def __init__(self, files_to_create, sha):
            self._f = files_to_create
            self._sha = sha
        def probe(self, record): return record
        def download(self, record, target_dir):
            target_dir = Path(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            files = []
            for fname, content in self._f:
                p = target_dir / fname
                p.write_bytes(content)
                files.append(p)
            from pathscientist.dataset.providers.base import DownloadResult
            return DownloadResult(
                status="downloaded", raw_root=target_dir, files=files,
                checksum_sha256=self._sha,
            )

    provider = _ChecksumProvider([("data.bin", b"hello")], expected)
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "prepared"


def test_acquisition_fails_on_checksum_mismatch(tmp_path):
    """R6: mismatching checksum -> status='failed', reason='checksum_mismatch:...'."""
    expected = "0" * 64   # certainly not the actual hash of 'hello'
    rec = DatasetRecord(
        dataset_id="hf:demo/x",
        name="Demo",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=1.0,
        download=DownloadSpec(
            kind="hf_dataset", remote_id="demo/x",
            checksum_sha256=expected,
        ),
    )
    reg = _registry_with([rec], tmp_path)

    class _ChecksumProvider:
        provider_name = "huggingface"
        def probe(self, record): return record
        def download(self, record, target_dir):
            target_dir = Path(target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "data.bin").write_bytes(b"hello")
            from pathscientist.dataset.providers.base import DownloadResult
            return DownloadResult(
                status="downloaded", raw_root=target_dir,
                files=[target_dir / "data.bin"],
                checksum_sha256="2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )

    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": _ChecksumProvider()},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "failed"
    assert result.reason.startswith("checksum_mismatch:")


def test_acquisition_proceeds_when_provider_no_checksum_but_record_has_one(tmp_path):
    """R6: when expected checksum is set but provider returned blank checksum
    (e.g., multi-file snapshot), acquisition proceeds with a log warning rather
    than failing - multi-file checksumming is out of v1 scope."""
    expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    rec = DatasetRecord(
        dataset_id="hf:demo/x",
        name="Demo",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        estimated_size_gb=1.0,
        download=DownloadSpec(
            kind="hf_dataset", remote_id="demo/x",
            checksum_sha256=expected,
        ),
    )
    reg = _registry_with([rec], tmp_path)
    fake_provider = _FakeProvider(status="downloaded", files_to_create=[("a.bin", b"x")])
    # _FakeProvider's DownloadResult has empty checksum_sha256 by default,
    # which is the multi-file / snapshot case the test pins.
    workspace = tmp_path / "workspace"
    service = DatasetAcquisitionService(
        registry=reg,
        providers={"huggingface": fake_provider},
        normalizers=[_FakeNormalizer()],
        cache_root=tmp_path / "cache",
    )
    result = service.acquire(_profile(), workspace_root=workspace)
    assert result.status == "prepared"
