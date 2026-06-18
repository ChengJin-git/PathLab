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


def test_sandbox_resolves_apptainer_from_path_when_env_unset(tmp_path, monkeypatch):
    """jhcpu5 installs apptainer under /usr/bin, not the cluster module path."""
    import pathscientist.runtime.sandbox as sandbox_module

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    apptainer = bin_dir / "apptainer"
    apptainer.write_text("#!/bin/sh\necho apptainer version test\n")
    apptainer.chmod(0o755)

    monkeypatch.delenv("APPTAINER_BIN", raising=False)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert sandbox_module._resolve_apptainer_bin() == str(apptainer)


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


def test_default_image_prefers_pathscientist_local_sandbox(tmp_path, monkeypatch):
    """Default runtime images should live under PathScientist-owned local state."""
    import pathscientist.runtime.sandbox as sandbox_module

    monkeypatch.delenv("PATHSCIENTIST_SANDBOX_IMAGE", raising=False)
    monkeypatch.delenv("PATHLAB_SANDBOX_IMAGE", raising=False)

    backend_dir = tmp_path / "pathlab-client" / "server" / "backend"
    image_dir = backend_dir.parent.parent / ".local" / "pathscientist" / "sandbox"
    image_dir.mkdir(parents=True)
    image = image_dir / "pathlab-sandbox.sif"
    image.write_text("fake image")

    assert sandbox_module._resolve_default_image(backend_dir) == str(image)


def test_default_image_ignores_stale_env_image_when_local_sandbox_exists(tmp_path, monkeypatch):
    """A stale image path from an old worktree must not silently disable sandbox."""
    import pathscientist.runtime.sandbox as sandbox_module

    stale_image = tmp_path / "old-worktree" / "pathlab-sandbox.sif"
    monkeypatch.setenv("PATHSCIENTIST_SANDBOX_IMAGE", str(stale_image))
    monkeypatch.delenv("PATHLAB_SANDBOX_IMAGE", raising=False)

    backend_dir = tmp_path / "pathlab-client" / "server" / "backend"
    image_dir = backend_dir.parent.parent / ".local" / "pathscientist" / "sandbox"
    image_dir.mkdir(parents=True)
    image = image_dir / "pathlab-sandbox.sif"
    image.write_text("fake image")

    assert sandbox_module._resolve_default_image(backend_dir) == str(image)


def test_sandbox_constructor_ignores_missing_image_when_default_exists(tmp_path, monkeypatch):
    """Agent-created sandboxes must not execute a stale non-existent image path."""
    import pathscientist.runtime.sandbox as sandbox_module

    fallback_image = tmp_path / "current" / "pathlab-sandbox.sif"
    fallback_image.parent.mkdir(parents=True)
    fallback_image.write_text("fake image")
    missing_image = tmp_path / "old" / "pathlab-sandbox.sif"

    monkeypatch.setattr(sandbox_module, "_DEFAULT_IMAGE", str(fallback_image))

    sandbox = sandbox_module.ApptainerSandbox(image=str(missing_image))

    assert sandbox.image == str(fallback_image)


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




def test_sandbox_binds_symlink_target_chain_for_data_mounts(tmp_path, monkeypatch):
    """Absolute symlinks inside mounted datasets must remain readable in --no-home sandboxes."""
    import pathscientist.runtime.sandbox as sandbox_module

    original_exists = sandbox_module.Path.exists

    def fake_exists(self):
        if str(self) == "/tmp":
            return False
        return original_exists(self)

    monkeypatch.setattr(sandbox_module.Path, "exists", fake_exists)

    s = _build_sandbox_for_test(monkeypatch)
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    dataset = tmp_path / "dataset"
    middle = tmp_path / "middle_features"
    final = tmp_path / "final_features"
    (dataset / "features").mkdir(parents=True)
    middle.mkdir()
    final.mkdir()
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)
    (final / "slide.pt").write_text("feature")
    (middle / "slide.pt").symlink_to(final / "slide.pt")
    (dataset / "features" / "slide.pt").symlink_to(middle / "slide.pt")

    cmd = s._build_exec_cmd(
        workspace,
        output,
        data_mounts={str(dataset): "/data"},
    )
    cmd_str = " ".join(cmd)

    assert f"{dataset}:/data:rw" in cmd_str
    assert f"{middle}:{middle}:ro" in cmd_str
    assert f"{final}:{final}:ro" in cmd_str


def test_sandbox_can_disable_cgroup_limits(tmp_path, monkeypatch):
    """Some user.slice cgroups reject Apptainer --memory/--cpus at runtime."""
    monkeypatch.setenv("PATHSCIENTIST_SANDBOX_CGROUPS", "0")
    s = ApptainerSandbox()
    workspace = tmp_path / "ws"
    output = tmp_path / "ws" / "output"
    workspace.mkdir(parents=True)
    output.mkdir(parents=True)

    cmd = s._build_exec_cmd(workspace, output)

    assert "--memory" not in cmd
    assert "--cpus" not in cmd
    assert f"{workspace}:{workspace}:rw" in " ".join(cmd)


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


def test_sandbox_run_script_quotes_workspace_and_script_path(tmp_path, monkeypatch):
    s = _build_sandbox_for_test(monkeypatch)
    workspace = tmp_path / "ws with spaces"
    output = workspace / "output"
    workspace.mkdir(parents=True)
    captured = {}

    def fake_run(cmd, env, timeout, start, **kwargs):
        captured["cmd"] = cmd
        return 0, "ok", False

    monkeypatch.setattr(s, "_run_with_early_detection", fake_run)

    result = s.run_script(
        "safe script.py",
        workspace_dir=workspace,
        output_dir=output,
        script_type="python",
    )

    assert result.exit_code == 0
    shell_fragment = captured["cmd"][-1]
    assert f"cd '{workspace}'" in shell_fragment
    assert "python 'safe script.py'" in shell_fragment


def test_sandbox_run_script_rejects_non_relative_script_path(tmp_path, monkeypatch):
    s = _build_sandbox_for_test(monkeypatch)
    workspace = tmp_path / "ws"
    output = workspace / "output"
    workspace.mkdir(parents=True)

    result = s.run_script(
        "../outside.py",
        workspace_dir=workspace,
        output_dir=output,
        script_type="python",
    )

    assert result.exit_code == -1
    assert "workspace-relative" in result.stderr


# ---- Workspace passthrough ----

def test_workspace_run_script_passes_data_mounts_to_sandbox(tmp_path):
    """Workspace.run_script forwards data_mounts to the sandbox."""
    from pathscientist.runtime.workspace import Workspace

    captured = {}

    class _StubSandbox:
        def run_script(self, *, script_path, workspace_dir, output_dir,
                        env_vars=None, timeout=600.0, data_mounts=None, **_kwargs):
            captured["data_mounts"] = data_mounts
            from pathscientist.runtime.sandbox import SandboxResult
            return SandboxResult(exit_code=0, stdout="", stderr="", duration=0.1, timed_out=False, early_failed=False)

    ws = Workspace(tmp_path / "wsroot", sandbox=_StubSandbox())
    (tmp_path / "wsroot").mkdir(exist_ok=True)
    ws.write_file("train.py", "print('hi')\n")
    ws.run_script("train.py", data_mounts={str(tmp_path / "x"): "/data"})
    assert captured["data_mounts"] == {str(tmp_path / "x"): "/data"}


def test_sandbox_forwards_huggingface_token_env(monkeypatch):
    """HF credentials inherited by PathScientist must reach Apptainer."""
    s = _build_sandbox_for_test(monkeypatch)
    monkeypatch.setenv("HF_TOKEN", "pathlab-hf-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "pathlab-hf-token")

    env = s._build_env()

    assert env["APPTAINERENV_HF_TOKEN"] == "pathlab-hf-token"
    assert env["APPTAINERENV_HUGGING_FACE_HUB_TOKEN"] == "pathlab-hf-token"


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
