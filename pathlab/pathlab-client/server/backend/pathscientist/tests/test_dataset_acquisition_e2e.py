"""End-to-end acquisition test with fake providers + fake normalizer.

Drives _run_acquisition_stage through:
  1. registry scout → public candidate
  2. fake provider downloads a fake .zip file
  3. fake normalizer extracts to a prepared layout
  4. manifest + evidence written
  5. config.data_mounts mutated
  6. brief renders Selected dataset / Dataset manifest

No network. Plan T9 from 2026-04-25-pathscientist-dataset-download-next-implementation-plan.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.dataset.acquisition import DatasetAcquisitionService
from pathscientist.dataset.policy import AcquisitionPolicy
from pathscientist.dataset.providers.base import DownloadResult
from pathscientist.dataset.registry import DatasetRegistry
from pathscientist.dataset.types import DatasetRecord, DownloadSpec, TaskProfile
from pathscientist.orchestrator.prompts import build_execution_brief
from pathscientist.orchestrator.types import (
    ResearchObjective, ResearchSessionState, STAGE_ACQUISITION, STAGE_GROUNDING,
)


# ---- fakes ----

class _FakeProvider:
    provider_name = "huggingface"

    def __init__(self, files_to_create):
        self._files_to_create = files_to_create

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
        return DownloadResult(status="downloaded", raw_root=target_dir, files=files)


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


def _public_record():
    return DatasetRecord(
        dataset_id="hf:demo/x",
        name="Demo Patches",
        provider="huggingface",
        access="public",
        task_types=["patch_classification"],
        asset_types=["patch_images"],
        organs=["colorectal"],
        license="CC-BY-4.0",
        estimated_size_gb=1.0,
        download=DownloadSpec(kind="hf_dataset", remote_id="demo/x"),
    )


def _profile():
    return TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="colorectal",
    )


def _state():
    return ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(),
        objective=ResearchObjective(question="patch classification on CRC-MSI", success_metric="auc"),
    )


# ---- test ----

def test_grounding_acquisition_execution_contract(tmp_path):
    """The full grounding → acquisition → execution contract with fakes.

    Pins:
    - manifest is written and reflects the prepared status
    - state.dataset_manifest_path is set
    - state.selected_dataset has the chosen record's name + provider
    - config.data_mounts is mutated with the prepared paths
    - the execution brief shows the Selected dataset / Dataset manifest lines
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cache = tmp_path / "cache"

    registry = DatasetRegistry(tmp_path / "datasets.json")
    registry.save([_public_record()])

    service = DatasetAcquisitionService(
        registry=registry,
        providers={"huggingface": _FakeProvider([("data.bin", b"hello")])},
        normalizers=[_FakeNormalizer()],
        cache_root=cache,
        policy=AcquisitionPolicy(),  # default public_only / 20GB
    )

    result = service.acquire(_profile(), workspace_root=workspace)

    # Direct service-level assertions
    assert result.status == "prepared"
    assert result.manifest_path == workspace / ".dataset" / "manifest.json"
    assert result.manifest_path.exists()
    manifest_data = json.loads(result.manifest_path.read_text())
    assert manifest_data["status"] == "prepared"
    assert manifest_data["dataset_id"] == "hf:demo/x"
    assert manifest_data["data_mounts"]
    assert result.evidence_path and result.evidence_path.exists()

    # Now verify the full integration: copy result onto state + mutate config,
    # then render the brief — this mirrors what _run_acquisition_stage does.
    state = _state()
    state.advance(STAGE_GROUNDING)
    state.grounding = {
        "task_profile": _profile().to_dict(),
    }
    state.advance(STAGE_ACQUISITION)
    state.acquisition_status = result.status
    state.dataset_manifest_path = str(result.manifest_path)
    state.selected_dataset = {
        "dataset_id": result.candidate.record.dataset_id,
        "name": result.candidate.record.name,
        "provider": result.candidate.record.provider,
        "access": result.candidate.record.access,
        "license": result.candidate.record.license,
    }
    config_data_mounts = {}
    config_data_mounts.update(result.manifest.data_mounts)

    assert config_data_mounts   # was mutated
    brief = build_execution_brief(state)
    assert "Selected dataset: Demo Patches" in brief
    assert "huggingface" in brief
    assert str(result.manifest_path) in brief


def test_run_acquisition_stage_e2e_with_monkeypatched_service(tmp_path, monkeypatch):
    """Drive the orchestrator's _run_acquisition_stage helper directly.

    We monkeypatch DatasetAcquisitionService inside the runner module so we
    don't depend on the real seed registry, providers, or normalizers.
    """
    from pathscientist.orchestrator import runner as runner_mod

    # Build a fake service that returns a 'prepared' AcquisitionResult.
    from pathscientist.dataset.acquisition import AcquisitionResult
    from pathscientist.dataset.types import DatasetManifest

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    manifest_path = workspace_root / ".dataset" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    fake_manifest = DatasetManifest(
        dataset_id="demo:fake",
        provider="huggingface",
        selected_for_task="patch_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(tmp_path / "prepared"),
        data_mounts={str(tmp_path / "prepared"): "/data"},
        prepared_contract={
            "task_type": "patch_classification",
            "images_dir": str(tmp_path / "prepared" / "images"),
        },
        access="public",
        status="prepared",
    )

    class _FakeCandidate:
        class _Rec:
            dataset_id = "demo:fake"
            name = "FakeDataset"
            provider = "huggingface"
            access = "public"
            license = "MIT"
        record = _Rec()
        score = 5.0
        reasons = ["task_type_match"]

    fake_result = AcquisitionResult(
        status="prepared",
        manifest=fake_manifest,
        manifest_path=manifest_path,
        candidate=_FakeCandidate(),
        evidence_path=None,
    )

    class _FakeService:
        def __init__(self, **kwargs):
            pass
        def acquire(self, profile, workspace_root):
            # Persist the manifest to disk like the real service does.
            manifest_path.write_text(json.dumps(fake_manifest.to_dict()))
            return fake_result

    # Patch on runner_mod (visible attribute) and on the source module so the
    # function-local ``from ..dataset.acquisition import DatasetAcquisitionService``
    # picks up the fake. Without the latter the runner re-imports the real
    # service every call (import-time aliasing).
    monkeypatch.setattr(runner_mod, "DatasetAcquisitionService", _FakeService, raising=False)
    from pathscientist.dataset import acquisition as acq_mod
    monkeypatch.setattr(acq_mod, "DatasetAcquisitionService", _FakeService, raising=False)

    state = _state()
    state.advance(STAGE_GROUNDING)
    state.grounding = {"task_profile": _profile().to_dict()}
    state.advance(STAGE_ACQUISITION)
    state.task_profile = _profile().to_dict()

    config = type("Cfg", (), {})()
    config.data_mounts = {}
    config.dataset_cache_dir = str(tmp_path / "cache")
    config.download_policy = "public_only"
    config.max_download_size_gb = 20.0
    config.allow_large_downloads = False

    session = type("S", (), {})()
    session.persistence_root = tmp_path / "persist"
    session.persistence_root.mkdir()
    session.workspace_dir = workspace_root

    state = runner_mod._run_acquisition_stage(state, session, config)

    # Pin the integration outcomes
    assert state.acquisition_status == "prepared"
    assert state.dataset_manifest_path == str(manifest_path)
    assert state.selected_dataset["name"] == "FakeDataset"
    assert state.selected_dataset["provider"] == "huggingface"
    # config.data_mounts mutated with the prepared paths
    assert config.data_mounts == {str(tmp_path / "prepared"): "/data"}
