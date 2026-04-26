"""Sandbox + workspace + brief render of acquisition-supplied data_mounts.

R4 from docs/review/2026-04-25-pathscientist-dataset-download-implementation-review.md.
Tests command-construction (no actual apptainer exec) — the bind args land
in the cmd list, and the brief renders the prepared contract paths.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.dataset.types import DatasetManifest
from pathscientist.dataset.manifests import save_manifest, manifest_path_for_workspace
from pathscientist.orchestrator.prompts import build_execution_brief
from pathscientist.orchestrator.types import (
    ResearchObjective, ResearchSessionState, STAGE_ACQUISITION, STAGE_GROUNDING,
)
from pathscientist.runtime.sandbox import ApptainerSandbox


def _build_sandbox_for_test(monkeypatch) -> ApptainerSandbox:
    """ApptainerSandbox checks apptainer existence in __init__-ish helpers;
    instantiate without that gate."""
    s = ApptainerSandbox.__new__(ApptainerSandbox)
    s.apptainer = "/usr/bin/apptainer"
    s.image = "/tmp/fake-image.sif"
    s.gpu_ids = []
    s.memory_limit = "16g"
    s.cpus = "4"
    s._cgroups_available = False
    return s


# ---- Sandbox cmd construction ----

def test_sandbox_binds_data_mounts(tmp_path, monkeypatch):
    """R4: ApptainerSandbox._build_exec_cmd must add --bind args for
    every entry in data_mounts."""
    s = _build_sandbox_for_test(monkeypatch)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    prepared = tmp_path / "prepared"
    prepared.mkdir()

    cmd = s._build_exec_cmd(
        workspace, output,
        data_mounts={str(prepared): "/data"},
    )
    cmd_str = " ".join(cmd)
    assert f"{prepared}:/data:rw" in cmd_str


def test_sandbox_skips_data_mount_when_host_path_missing(tmp_path):
    s = _build_sandbox_for_test(None)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    bogus = tmp_path / "does-not-exist"
    cmd = s._build_exec_cmd(
        workspace, output,
        data_mounts={str(bogus): "/data"},
    )
    cmd_str = " ".join(cmd)
    assert f"{bogus}:/data" not in cmd_str


def test_sandbox_does_not_double_bind_workspace(tmp_path):
    """Workspace_dir is already bound; if user passes the same host path
    in data_mounts, do NOT emit a duplicate bind."""
    s = _build_sandbox_for_test(None)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    cmd = s._build_exec_cmd(
        workspace, output,
        data_mounts={str(workspace): "/somewhere"},
    )
    # The "duplicate" bind to /somewhere must NOT appear.
    cmd_str = " ".join(cmd)
    assert ":/somewhere" not in cmd_str
    # The original workspace bind is still there.
    assert f"{workspace}:{workspace}:rw" in cmd_str


def test_sandbox_supports_multiple_data_mounts(tmp_path):
    s = _build_sandbox_for_test(None)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    cmd = s._build_exec_cmd(
        workspace, output,
        data_mounts={str(a): "/data/a", str(b): "/data/b"},
    )
    cmd_str = " ".join(cmd)
    assert f"{a}:/data/a:rw" in cmd_str
    assert f"{b}:/data/b:rw" in cmd_str


def test_sandbox_data_mounts_default_none_keeps_existing_binds(tmp_path):
    s = _build_sandbox_for_test(None)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True); output.mkdir(parents=True)
    cmd_no_mounts = s._build_exec_cmd(workspace, output)
    cmd_empty_mounts = s._build_exec_cmd(workspace, output, data_mounts={})
    assert cmd_no_mounts == cmd_empty_mounts


# ---- Workspace passthrough ----

def test_workspace_run_script_passes_data_mounts_to_sandbox(tmp_path):
    """Workspace.run_script forwards data_mounts to the sandbox."""
    from pathscientist.runtime.workspace import Workspace

    captured = {}

    class _StubSandbox:
        def run_script(self, *, script_path, workspace_dir, output_dir,
                        env_vars=None, timeout=600.0, data_mounts=None):
            captured["data_mounts"] = data_mounts
            from openhands.sdk.workspace.models import CommandResult
            from pathscientist.runtime.sandbox import SandboxResult
            return SandboxResult(exit_code=0, stdout="", stderr="", duration=0.1, timed_out=False, early_failed=False)

    ws = Workspace(tmp_path / "wsroot", sandbox=_StubSandbox())
    (tmp_path / "wsroot").mkdir(exist_ok=True)
    ws.write_file("train.py", "print('hi')\n")
    ws.run_script("train.py", data_mounts={str(tmp_path / "x"): "/data"})
    assert captured["data_mounts"] == {str(tmp_path / "x"): "/data"}


# ---- Brief rendering ----

def test_brief_renders_prepared_contract_paths(tmp_path):
    """R4: build_execution_brief must surface images_dir, splits_file, etc.
    so the agent sees the actual paths to use, not just the manifest path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    images = prepared / "images"
    images.mkdir()
    splits = prepared / "splits.json"
    splits.write_text("{}")

    manifest = DatasetManifest(
        dataset_id="hf:demo/x",
        provider="huggingface",
        selected_for_task="patch_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(prepared),
        data_mounts={str(prepared): "/data"},
        prepared_contract={
            "task_type": "patch_classification",
            "images_dir": str(images),
            "splits_file": str(splits),
        },
        access="public",
        status="prepared",
    )
    manifest_path = manifest_path_for_workspace(workspace)
    save_manifest(manifest_path, manifest)

    state = ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(),
        objective=ResearchObjective(question="train", success_metric="auc"),
    )
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    state.acquisition_status = "prepared"
    state.dataset_manifest_path = str(manifest_path)
    state.selected_dataset = {
        "dataset_id": "hf:demo/x",
        "name": "Demo",
        "provider": "huggingface",
        "access": "public",
    }

    brief = build_execution_brief(state)
    assert "Prepared contract:" in brief
    assert f"images_dir: {images}" in brief
    assert f"splits_file: {splits}" in brief
    assert f"data_mounts: {prepared} -> /data" in brief


def test_brief_has_no_prepared_contract_when_manifest_missing(tmp_path):
    """No manifest path → no 'Prepared contract' block (selected dataset
    line still appears)."""
    state = ResearchSessionState.create(
        session_id="sid", conversation_id=uuid4(),
        objective=ResearchObjective(question="train", success_metric="auc"),
    )
    state.advance(STAGE_GROUNDING)
    state.advance(STAGE_ACQUISITION)
    state.acquisition_status = "prepared"
    state.dataset_manifest_path = ""
    state.selected_dataset = {"name": "Demo", "provider": "huggingface", "access": "public"}
    brief = build_execution_brief(state)
    assert "Selected dataset: Demo" in brief
    assert "Prepared contract:" not in brief
