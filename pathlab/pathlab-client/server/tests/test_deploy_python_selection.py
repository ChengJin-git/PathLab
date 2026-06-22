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
