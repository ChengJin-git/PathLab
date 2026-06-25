from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["AUTORESEARCH_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK"] = "1"

from autoresearch.runtime.workspace import Workspace


def test_workspace_sdk_fallback_requires_explicit_test_flag(monkeypatch, tmp_path):
    source_path = Path(__file__).parents[1] / "runtime" / "workspace.py"
    real_import = builtins.__import__

    def import_without_openhands_workspace(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("openhands.sdk.workspace"):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_openhands_workspace)
    module_name = "_autoresearch_workspace_fallback_gate_test"

    monkeypatch.delenv("AUTORESEARCH_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK", raising=False)
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        try:
            module.Workspace(tmp_path / "without_flag")
        except RuntimeError as exc:
            assert "OpenHands SDK LocalWorkspace is required" in str(exc)
        else:
            raise AssertionError("Workspace fallback should require an explicit test flag")
    finally:
        sys.modules.pop(module_name, None)

    monkeypatch.setenv("AUTORESEARCH_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK", "1")
    allowed_name = "_autoresearch_workspace_fallback_allowed_test"
    allowed_spec = importlib.util.spec_from_file_location(allowed_name, source_path)
    assert allowed_spec is not None and allowed_spec.loader is not None
    allowed_module = importlib.util.module_from_spec(allowed_spec)
    sys.modules[allowed_name] = allowed_module
    try:
        allowed_spec.loader.exec_module(allowed_module)
        workspace = allowed_module.Workspace(tmp_path / "with_flag")
        assert workspace.execute_command("printf ok").stdout == "ok"
    finally:
        sys.modules.pop(allowed_name, None)


def test_subprocess_workspace_fallback_does_not_execute_shell_metacharacters(monkeypatch, tmp_path):
    source_path = Path(__file__).parents[1] / "runtime" / "workspace.py"
    real_import = builtins.__import__

    def import_without_openhands_workspace(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("openhands.sdk.workspace"):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_openhands_workspace)
    monkeypatch.setenv("AUTORESEARCH_ALLOW_SUBPROCESS_WORKSPACE_FALLBACK", "1")
    module_name = "_autoresearch_workspace_fallback_shell_test"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        workspace = module.Workspace(tmp_path / "workspace")
        marker = workspace.root / "pwned"
        result = workspace.execute_command(f"printf ok ; touch {marker.name}")
        assert result.exit_code != 0
        assert not marker.exists()
    finally:
        sys.modules.pop(module_name, None)


def test_run_script_preserves_external_dataset_json_env_value(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    expected = json.dumps(
        [
            {
                "role": "external",
                "dataset_name": "External cohort A",
                "paths": ["/tmp/path with spaces/external"],
            }
        ]
    )
    workspace.write_file(
        "dump_env.sh",
        "printf '%s' \"$AUTORESEARCH_EXTERNAL_DATASETS\" > actual.txt\n",
    )

    result = workspace.run_script(
        "dump_env.sh",
        script_type="bash",
        env_vars={"AUTORESEARCH_EXTERNAL_DATASETS": expected},
        timeout=10,
    )

    assert result.exit_code == 0, result.stderr
    assert (workspace.root / "actual.txt").read_text(encoding="utf-8") == expected


def test_run_script_passes_env_without_shell_reparsing(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file(
        "dump_safe_env.sh",
        "printf '%s' \"$SAFE_VALUE\" > actual.txt\n",
    )
    value = '$(printf injected) "quoted" spaces | pipe'

    result = workspace.run_script(
        "dump_safe_env.sh",
        script_type="bash",
        env_vars={"SAFE_VALUE": value},
        timeout=10,
    )

    assert result.exit_code == 0, result.stderr
    assert (workspace.root / "actual.txt").read_text(encoding="utf-8") == value


def test_run_script_uses_current_python_when_python_is_not_on_path(monkeypatch, tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file(
        "hello.py",
        "import sys\nprint(\"ok:\" + str(bool(sys.executable)))\n",
    )
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    result = workspace.run_script(
        "hello.py",
        script_type="python",
        timeout=10,
    )
