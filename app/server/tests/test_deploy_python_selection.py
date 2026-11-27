"""Deployment launcher Python selection policy tests."""
import importlib.util
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

CLIENT_ROOT = Path(__file__).resolve().parents[2]


def _deploy_script_text(name: str) -> str:
    return (CLIENT_ROOT / "deploy" / name).read_text()


def test_deploy_scripts_use_shared_python_selection():
    for script in ("start.sh", "hot-reload.sh"):
        text = _deploy_script_text(script)
        assert 'source "$SCRIPT_DIR/python-runtime.sh"' in text
        assert "select_pathlab_python" in text


@pytest.mark.parametrize("selected", ["explicit", "research", "project", "conda", "system"])
def test_python_selection_executes_precedence_policy(tmp_path, selected):
    paths = {
        "explicit": tmp_path / "explicit/python",
        "research": tmp_path / "server/backend/autoresearch/.venv/bin/python",
        "project": tmp_path / "venv/bin/python3",
        "conda": tmp_path / "conda/bin/python3",
        "system": tmp_path / "bin/python3",
    }
    choices = list(paths)
    for choice in choices[choices.index(selected):]:
        executable = paths[choice]
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
    environment = {
        "PATH": str(tmp_path / "bin"),
        "SERVER_DIR": str(tmp_path / "server"),
        "PROJECT_DIR": str(tmp_path),
        "CONDA_PREFIX": str(tmp_path / "conda"),
    }
    if selected == "explicit":
        environment["PATHLAB_PYTHON"] = str(paths[selected])
        bundle = tmp_path / "server/.venv/pathlab.env"
        bundle.parent.mkdir(parents=True)
        bundle.write_text(f'export PATHLAB_PYTHON="{paths["research"]}"\n')
    result = subprocess.run(
        ["/bin/bash", "-eu", "-c", 'source "$1"; select_pathlab_python; printf "%s" "$PYTHON"',
         "bash", str(CLIENT_ROOT / "deploy/python-runtime.sh")],
        env=environment, capture_output=True, text=True, check=True,
    )
    assert result.stdout == str(paths[selected])


def test_invalid_explicit_python_is_rejected(tmp_path):
    result = subprocess.run(
        ["/bin/bash", "-eu", "-c", 'source "$1"; select_pathlab_python',
         "bash", str(CLIENT_ROOT / "deploy/python-runtime.sh")],
        env={**os.environ, "SERVER_DIR": str(tmp_path), "PROJECT_DIR": str(tmp_path),
             "PATHLAB_PYTHON": str(tmp_path / "missing")},
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not executable/found" in result.stderr


def test_runtime_verifier_discovers_kaggle_without_importing_it(monkeypatch):
    spec = importlib.util.spec_from_file_location('runtime_verifier', CLIENT_ROOT / 'deploy/verify-runtime.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    imported, discovered = [], []
    monkeypatch.setattr(verifier, 'importlib', SimpleNamespace(
        import_module=lambda name: imported.append(name),
        util=SimpleNamespace(find_spec=lambda name: discovered.append(name) or object()),
    ))
    verifier.main()
    assert imported == verifier.MODULES
    assert discovered == ['kaggle'] and 'kaggle' not in imported


def test_failed_runtime_preflight_returns_failure_without_installing_packages(tmp_path):
    text = _deploy_script_text('start.sh')
    functions = []
    for name in ['check_autoresearch_python_packages', 'install_autoresearch_python_packages']:
        functions.append(re.search(rf'^{name}\(\) \{{\n.*?^\}}', text, re.MULTILINE | re.DOTALL).group())
    script = '\n'.join(functions) + '''
PYTHON=false
SCRIPT_DIR=/fixture
check_autoresearch_python_packages
check_status=$?
install_autoresearch_python_packages
install_status=$?
test "$check_status" -ne 0 && test "$install_status" -ne 0
'''
    result = subprocess.run(['bash', '-c', script], cwd=tmp_path, text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert 'install-runtime.sh' in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_start_script_checks_apptainer_and_sandbox_image():
    text = _deploy_script_text("start.sh")

    assert "AUTORESEARCH_SANDBOX" in text
    assert "AUTORESEARCH_SANDBOX_IMAGE" in text
    assert "apptainer" in text.lower()
    assert "sandbox image" in text.lower()


def test_launch_image_resolution_uses_persistent_home_and_explicit_override(tmp_path):
    text = _deploy_script_text('start.sh')
    function = re.search(r'^resolve_autoresearch_sandbox_image\(\) \{\n.*?^\}', text, re.MULTILINE | re.DOTALL).group()
    for overrides, expected in [
        ({}, tmp_path / '.local/share/PathLab/sandbox/pathlab-sandbox.sif'),
        ({'XDG_DATA_HOME':str(tmp_path / 'data')}, tmp_path / 'data/PathLab/sandbox/pathlab-sandbox.sif'),
        ({'AUTORESEARCH_SANDBOX_IMAGE':str(tmp_path / 'explicit.sif')}, tmp_path / 'explicit.sif'),
    ]:
        result = subprocess.run(['bash', '-c', function + '\nresolve_autoresearch_sandbox_image'],
            env={'HOME':str(tmp_path), **overrides}, text=True, capture_output=True, check=True)
        assert result.stdout.strip() == str(expected)


def test_start_script_runs_autoresearch_preflight_before_service_cleanup():
    text = _deploy_script_text("start.sh")

    assert "check_autoresearch_environment\n\n# ========== Step 1" in text


def test_autoresearch_sandbox_build_script_is_documented_and_configurable():
    script = CLIENT_ROOT / "deploy" / "build-autoresearch-sandbox.sh"
    text = script.read_text()
    deploy_readme = (CLIENT_ROOT / "deploy" / "README.md").read_text()
    autoresearch_readme = (CLIENT_ROOT / "server" / "backend" / "autoresearch" / "README.md").read_text()

    assert "pathlab-sandbox.def" in text
    assert "AUTORESEARCH_SANDBOX_IMAGE" in text
    assert "APPTAINER_TMPDIR" in text
    assert "apptainer build" in text
    assert "apptainer exec --nv" in text
    assert "deploy/build-autoresearch-sandbox.sh" in deploy_readme
    assert "deploy/build-autoresearch-sandbox.sh" in autoresearch_readme


def test_autoresearch_sandbox_definition_avoids_build_time_tmp_chmod():
    definition = (
        CLIENT_ROOT
        / "server"
        / "backend"
        / "autoresearch"
        / "runtime"
        / "containers"
        / "pathlab-sandbox.def"
    ).read_text()

    assert "MPLCONFIGDIR=${MPLCONFIGDIR:-/var/cache/matplotlib}" in definition
    assert "/var/cache/matplotlib" in definition
    assert "/tmp/matplotlib" not in definition

    chmod_lines = [
        line.strip()
        for line in definition.splitlines()
        if line.strip().startswith("chmod ")
    ]
    assert any(
        "/workspace" in line and "/results" in line and "/data" in line
        for line in chmod_lines
    )
    assert all("/tmp" not in line for line in chmod_lines)


def test_autoresearch_requirements_uses_the_shared_runtime_declaration():
    requirements = (CLIENT_ROOT / "server" / "backend" / "autoresearch" / "requirements.txt").read_text()
    declarations = [line for line in requirements.splitlines() if line and not line.startswith('#')]
    assert declarations == ['-r ../../requirements.txt']
    assert (CLIENT_ROOT / 'server/requirements.txt').is_file()


def test_failed_scientific_image_verification_keeps_the_published_image(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('skills_builder', CLIENT_ROOT / 'deploy/build-skills-runtime.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    target = tmp_path / 'sandbox/pathlab-sandbox.sif'
    target.parent.mkdir()
    target.write_bytes(b'previous verified image')
    monkeypatch.setattr(builder, '_resolve_default_image', lambda: str(target))
    monkeypatch.setattr(builder.sys, 'argv', ['build-skills-runtime.py'])
    monkeypatch.setattr(builder.runtime, 'sandbox_command', lambda *_: ['verification'])
    monkeypatch.setattr(builder.runtime, '_resolve_default_image', lambda: str(target))
    monkeypatch.setattr(builder.Config, 'get_autoresearch_dir', classmethod(lambda cls: tmp_path/'research'))
    def execute(command, **kwargs):
        if command[0] == 'verification':
            raise subprocess.CalledProcessError(1, command)
        Path(command[-2]).write_bytes(b'candidate image')
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(builder.subprocess, 'run', execute)
    with pytest.raises(subprocess.CalledProcessError):
        builder.main()
    assert target.read_bytes() == b'previous verified image'
    assert list(target.parent.iterdir()) == [target]
