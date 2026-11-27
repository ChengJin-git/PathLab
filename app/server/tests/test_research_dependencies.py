from unittest.mock import AsyncMock

import pytest

from backend.autoresearch.engine import dependencies
from backend.autoresearch.engine.jobs import python_command


@pytest.mark.parametrize(
    "package", ["tabulate==0.9.0", "pandas>=2.2,<3", "package[extra]>=1.2"]
)
def test_dependency_specs_accept_normal_package_requirements(package):
    assert dependencies.SPEC.fullmatch(package)


@pytest.mark.parametrize(
    "package",
    [
        "--target=/host",
        "tabulate; rm -rf /",
        "https://untrusted/package.whl",
        "../outside",
    ],
)
async def test_dependency_tool_rejects_flags_paths_and_shell_commands(
    tmp_path, package
):
    with pytest.raises(ValueError):
        await dependencies.install(tmp_path, {}, [package], [])


async def test_dependency_tool_verifies_imports_and_runs_inside_sandbox(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        dependencies,
        "sandbox_command",
        lambda root, mounts: ["apptainer", "exec", "test.sif"],
    )
    process = AsyncMock()
    process.returncode = 0
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(dependencies.asyncio, "create_subprocess_exec", spawn)
    result = await dependencies.install(tmp_path, {}, ["tabulate==0.9.0"], ["tabulate"])
    assert result["python"] == str(tmp_path / ".venv/bin/python")
    assert spawn.call_args.args[:4] == ("apptainer", "exec", "test.sif", "python")
    assert "tabulate==0.9.0" in spawn.call_args.args[-2]
    assert "tabulate" in spawn.call_args.args[-1]


def test_python_jobs_automatically_use_session_environment(tmp_path):
    assert python_command(tmp_path, ["python", "train.py"]) == ["python", "train.py"]
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/pyvenv.cfg").write_text("home = /opt/conda/bin")
    assert python_command(tmp_path, ["python", "train.py"]) == [
        str(tmp_path / ".venv/bin/python"),
        "train.py",
    ]
    assert python_command(tmp_path, ["bash", "run.sh"]) == ["bash", "run.sh"]
