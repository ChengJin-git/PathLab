"""Deployment launcher Python selection policy tests."""
from pathlib import Path


CLIENT_ROOT = Path(__file__).resolve().parents[2]


def _deploy_script_text(name: str) -> str:
    return (CLIENT_ROOT / "deploy" / name).read_text()


def test_deploy_scripts_allow_explicit_python_override_before_conda():
    for script in ("start.sh", "hot-reload.sh"):
        text = _deploy_script_text(script)

        assert "PATHLAB_PYTHON" in text
        assert text.index("PATHLAB_PYTHON") < text.index("CONDA_PREFIX")


def test_deploy_scripts_prefer_pathscientist_venv_before_conda():
    for script in ("start.sh", "hot-reload.sh"):
        text = _deploy_script_text(script)

        expected = 'PATHSCIENTIST_PYTHON="$SERVER_DIR/backend/pathscientist/.venv/bin/python"'
        assert expected in text
        assert text.index("PATHSCIENTIST_PYTHON") < text.index("CONDA_PREFIX")


def test_start_script_checks_pathscientist_runtime_dependencies():
    text = _deploy_script_text("start.sh")

    assert "check_pathscientist_environment" in text
    for module_name in ("openhands.sdk", "torch", "kaggle"):
        assert module_name in text


def test_start_script_checks_apptainer_and_sandbox_image():
    text = _deploy_script_text("start.sh")

    assert "PATHSCIENTIST_SANDBOX" in text
    assert "PATHSCIENTIST_SANDBOX_IMAGE" in text
    assert "apptainer" in text.lower()
    assert "sandbox image" in text.lower()


def test_start_script_runs_pathscientist_preflight_before_service_cleanup():
    text = _deploy_script_text("start.sh")

    assert "check_pathscientist_environment\n\n# ========== Step 1" in text


def test_pathscientist_sandbox_build_script_is_documented_and_configurable():
    script = CLIENT_ROOT / "deploy" / "build-pathscientist-sandbox.sh"
    text = script.read_text()
    deploy_readme = (CLIENT_ROOT / "deploy" / "README.md").read_text()
    pathscientist_readme = (CLIENT_ROOT / "server" / "backend" / "pathscientist" / "README.md").read_text()

    assert "pathlab-sandbox.def" in text
    assert "PATHSCIENTIST_SANDBOX_IMAGE" in text
    assert "APPTAINER_TMPDIR" in text
    assert "apptainer build" in text
    assert "apptainer exec --nv" in text
    assert "deploy/build-pathscientist-sandbox.sh" in deploy_readme
    assert "deploy/build-pathscientist-sandbox.sh" in pathscientist_readme


def test_pathscientist_requirements_file_contains_agent_only_dependencies():
    requirements = (CLIENT_ROOT / "server" / "backend" / "pathscientist" / "requirements.txt").read_text()
    deploy_readme = (CLIENT_ROOT / "deploy" / "README.md").read_text()
    pathscientist_readme = (CLIENT_ROOT / "server" / "backend" / "pathscientist" / "README.md").read_text()

    for package in ("openhands-sdk", "openhands-tools", "kaggle"):
        assert package in requirements
    assert "backend/pathscientist/requirements.txt" in deploy_readme
    assert "backend/pathscientist/requirements.txt" in pathscientist_readme
