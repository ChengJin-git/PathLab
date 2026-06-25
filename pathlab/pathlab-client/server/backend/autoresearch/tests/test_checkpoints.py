"""Tests for checkpoint create/restore/list/delete."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from autoresearch.runtime.workspace import Workspace


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory(prefix="cp_test_") as tmpdir:
        ws = Workspace(Path(tmpdir))
        ws.set_baseline({"train.py": "print('v1')\n"})
        yield ws


def test_create_and_list_checkpoint(workspace):
    workspace.create_checkpoint("v1_baseline")
    cps = workspace.list_checkpoints()
    assert len(cps) == 1
    assert cps[0]["name"] == "v1_baseline"


def test_restore_checkpoint(workspace):
    # Create checkpoint at v1
    workspace.create_checkpoint("v1")

    # Modify file
    workspace.write_file("train.py", "print('v2')\n")
    workspace.commit("v2 change")
    assert workspace.read_file("train.py") == "print('v2')\n"

    # Restore to v1
    workspace.restore_checkpoint("v1")
    assert workspace.read_file("train.py") == "print('v1')\n"


def test_restore_nonexistent_checkpoint(workspace):
    with pytest.raises(ValueError, match="not found"):
        workspace.restore_checkpoint("nope")


def test_multiple_checkpoints(workspace):
    workspace.create_checkpoint("step1")

    workspace.write_file("train.py", "print('step2')\n")
    workspace.commit("step2")
    workspace.create_checkpoint("step2")

    workspace.write_file("train.py", "print('step3')\n")
    workspace.commit("step3")
    workspace.create_checkpoint("step3")

    cps = workspace.list_checkpoints()
    names = [cp["name"] for cp in cps]
    assert "step1" in names
    assert "step2" in names
    assert "step3" in names

    # Restore to step1, skip step2
    workspace.restore_checkpoint("step1")
    assert workspace.read_file("train.py") == "print('v1')\n"


def test_delete_checkpoint(workspace):
    workspace.create_checkpoint("temp")
    assert len(workspace.list_checkpoints()) == 1

    workspace.delete_checkpoint("temp")
    assert len(workspace.list_checkpoints()) == 0


def test_checkpoint_name_rejects_shell_metacharacters(workspace):
    pwned = workspace.root / "pwned"

    with pytest.raises(ValueError, match="Invalid checkpoint name"):
        workspace.create_checkpoint(f"bad; touch {pwned}")

    assert not pwned.exists()


def test_checkpoint_does_not_affect_other_session(workspace):
    """Checkpoints are git tags scoped to this workspace's repo."""
    with tempfile.TemporaryDirectory(prefix="cp_other_") as tmpdir:
        other = Workspace(Path(tmpdir))
        other.set_baseline({"train.py": "other\n"})

        workspace.create_checkpoint("mine")

        # Other workspace should not see this checkpoint
        assert len(other.list_checkpoints()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
