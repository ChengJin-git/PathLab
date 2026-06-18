"""Tests for the ``validate_script`` → ``run_experiment`` state handoff.

Review Finding 1 (Critical) of
``docs/review/2026-04-22-pathscientist-latest-run-review.md``:

> event-00163-51fb8272-f911-471b-8124-5d0bf27314d5.json:
>   validate_script returns ``Valid: True``.
> Immediately after, event-00165-b69aed97-da0f-4bb7-b54a-a590a8c020ec.json:
>   run_experiment still returns
>   ``Policy violation: Cannot run full experiment: current script has not
>   been validated.``
> The same pattern repeats later: event-00290 says Valid: True,
> event-00292 immediately fails with the same policy violation.

Root cause: ``validate_script`` hashed the LLM-supplied ``script_content``
string, while ``run_experiment`` hashed the on-disk file at
``workspace.root / script_path``. When the agent's in-context copy of the
script differed from disk (whitespace, condensation-refreshed paraphrase,
forgotten trailing bytes), the hashes diverged without any file edit and
the run was blocked even though validation had just succeeded.

Fix: ``validate_script`` now reads the on-disk file at the same
``script_path`` ``run_experiment`` will execute, hashes THAT, and rejects
calls whose supplied ``script_content`` disagrees with disk. The refusal
text from ``run_experiment`` names the specific invariant that failed —
either "no validation record" or "hash mismatch" with both hashes shown —
so the agent doesn't reach for workaround wrappers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from pathscientist.config import PathScientistConfig
from pathscientist.runtime.iteration_state import IterationState
from pathscientist.runtime.session_registry import (
    SessionDeps,
    register_session,
    remove_session,
)
from pathscientist.runtime.workspace import Workspace
from pathscientist.tools.metrics import MetricsTracker
from pathscientist.tools.run_experiment import (
    RunExperimentAction,
    RunExperimentExecutor,
)
from pathscientist.tools.validate_script import (
    ValidateScriptAction,
    ValidateScriptExecutor,
)


# A small script that passes validate_script's syntax / entry-point / metrics
# / safety checks. Anything the validator needs to see must appear verbatim.
_VALID_SCRIPT = '''\
"""Minimal script to exercise the validate→run handoff."""
import json
from pathlib import Path


def main() -> None:
    metrics = {"auc": 0.5}
    Path("output").mkdir(parents=True, exist_ok=True)
    Path("output/metrics.json").write_text(json.dumps(metrics))


if __name__ == "__main__":
    main()
'''


class _StubWorkspace:
    """Workspace stand-in that records run_script calls without executing.

    The real ``Workspace.run_script`` subprocesses ``python train.py``. We
    want to assert "policy check passed" without running Python, so we
    keep the filesystem-backed root from the real Workspace (for on-disk
    hashing) and swap ``run_script`` for a recording stub.
    """

    def __init__(self, real_workspace):
        self._real = real_workspace
        self.root = real_workspace.root
        self.calls: list[dict] = []
        # Stable exit code used by the stub; tests may override in-place.
        self.exit_code = 0

    def run_script(
        self,
        script_path,
        env_vars=None,
        timeout=600.0,
        data_mounts=None,
        **kwargs,
    ):
        self.calls.append(
            {
                "script_path": script_path,
                "env_vars": dict(env_vars or {}),
                "timeout": timeout,
                "kwargs": dict(kwargs or {}),
            }
        )
        from openhands.sdk.workspace.models import CommandResult
        return CommandResult(
            command=f"python {script_path}",
            exit_code=self.exit_code,
            stdout="",
            stderr="",
            timeout_occurred=False,
        )


def _register_handoff_session(tmp_path: Path, *, initial_script: str = _VALID_SCRIPT):
    """Build a SessionDeps with a stubbed workspace and register it.

    Returns ``(session_id, deps, stub_workspace, cleanup)``. Callers must
    invoke ``cleanup()`` in a ``finally`` block to drop the session from
    the registry.
    """
    ws_dir = tmp_path / "workspace"
    real_ws = Workspace(ws_dir)
    real_ws.write_file("train.py", initial_script)
    real_ws.commit("baseline")

    stub = _StubWorkspace(real_ws)

    tracker = MetricsTracker(primary_metric="auc")
    iteration_state = IterationState(max_iterations=5)
    config = PathScientistConfig(
        workspace_dir=str(ws_dir),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=5,
        primary_metric="auc",
        conversation_persistence_dir=str(tmp_path),
    )
    deps = SessionDeps(
        workspace=stub,
        tracker=tracker,
        config=config,
        iteration_state=iteration_state,
        conversation=None,
    )
    session_id = f"test_handoff_{tmp_path.name}"
    register_session(session_id, deps)

    def _cleanup() -> None:
        remove_session(session_id)

    return session_id, deps, stub, _cleanup


def _validate(session_id: str, *, script_content: str | None = None,
              script_path: str = "train.py"):
    executor = ValidateScriptExecutor(session_id=session_id)
    kwargs = {"script_path": script_path}
    if script_content is not None:
        kwargs["script_content"] = script_content
    obs = executor(ValidateScriptAction(**kwargs))
    return obs


def _run(session_id: str, *, workspace, config,
         quick_check: bool = False,
         script_path: str = "train.py",
         script_type: str = "auto",
         run_kind: str = "auto",
         script_inputs: list[str] | None = None):
    executor = RunExperimentExecutor(
        workspace=workspace, config=config, session_id=session_id,
    )
    return executor(RunExperimentAction(
        script_path=script_path,
        script_type=script_type,
        run_kind=run_kind,
        script_inputs=script_inputs or [],
        quick_check=quick_check,
        timeout=60,
    ))


# ------------------------------------------------------------------
# Test 1: validate then run succeeds when script is unchanged on disk
# ------------------------------------------------------------------


def test_validate_then_run_succeeds_when_script_unchanged(tmp_path):
    """The core Finding 1 scenario. validate_script accepts, run_experiment
    should NOT emit the policy violation afterwards."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        vobs = _validate(session_id, script_content=_VALID_SCRIPT)
        assert vobs.valid is True, (
            f"validate_script must accept the unchanged on-disk script; "
            f"got errors={vobs.errors!r}"
        )
        assert vobs.validated_hash, (
            "validate_script must record a validated_hash on success"
        )
        assert deps.iteration_state.last_validated_hash == vobs.validated_hash, (
            "validate_script must write the hash it reports into "
            f"iteration_state; got state={deps.iteration_state.last_validated_hash!r}, "
            f"obs={vobs.validated_hash!r}"
        )

        # quick_check=True first to satisfy check_can_full_run preconditions
        # and let us assert the validate→quick-check handoff too.
        robs = _run(session_id, workspace=stub, config=deps.config, quick_check=True)
        assert robs.exit_code == 0, (
            f"run_experiment must pass the policy check after validate; "
            f"instead got exit_code={robs.exit_code} content={robs.content!r}"
        )
        assert stub.calls, (
            "run_experiment must reach the workspace execution stage; "
            "the stub recorded no run_script call"
        )

        # Now the full run, after quick-check recorded its hash.
        robs2 = _run(session_id, workspace=stub, config=deps.config, quick_check=False)
        assert robs2.exit_code == 0, (
            f"full run must also be unlocked once validate+quick_check pass; "
            f"got exit_code={robs2.exit_code} content={robs2.content!r}"
        )
    finally:
        cleanup()


# ------------------------------------------------------------------
# Test 2: run is refused when script changed between validate and run
# ------------------------------------------------------------------


def test_run_refused_when_script_edited_between_validate_and_run(tmp_path):
    """Validate, then edit the file on disk, then run — the refusal must
    name "hash mismatch" so the agent knows re-validation is the fix."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        vobs = _validate(session_id, script_content=_VALID_SCRIPT)
        assert vobs.valid, f"prereq: validate must accept initial script; {vobs.errors!r}"
        validated_hash = vobs.validated_hash

        # Mutate the on-disk file — agent edited train.py with file_editor.
        edited = _VALID_SCRIPT + "\n# added a comment after validation\n"
        (stub.root / "train.py").write_text(edited)

        robs = _run(session_id, workspace=stub, config=deps.config, quick_check=True)
        assert robs.exit_code == -1, (
            "run_experiment must refuse when the on-disk hash no longer "
            f"matches the recorded validated hash; got exit_code={robs.exit_code}, "
            f"content={robs.content!r}"
        )
        text = robs.content[0].text
        assert "hash mismatch" in text, (
            "refusal must name the 'hash mismatch' invariant (not the "
            f"generic 'not been validated' text); got: {text!r}"
        )
        assert validated_hash in text, (
            "refusal must show the last_validated_hash so the agent can "
            f"see WHICH validation is stale; got: {text!r}"
        )
        # The stubbed workspace must NOT have been called — refusal blocks execution.
        assert not stub.calls, (
            f"refusal must block execution entirely; got stub.calls={stub.calls!r}"
        )
    finally:
        cleanup()


# ------------------------------------------------------------------
# Test 3: run is refused when validate_script was never called
# ------------------------------------------------------------------


def test_run_refused_when_never_validated(tmp_path):
    """Skip validate_script entirely. run_experiment must refuse with text
    that distinguishes this from the hash-mismatch shape."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        # Sanity: no validation has been recorded.
        assert deps.iteration_state.last_validated_hash == "", (
            "prereq: fresh IterationState must have no validated hash"
        )

        robs = _run(session_id, workspace=stub, config=deps.config, quick_check=True)
        assert robs.exit_code == -1, (
            "run_experiment must refuse when validate_script was never called; "
            f"got exit_code={robs.exit_code}, content={robs.content!r}"
        )
        text = robs.content[0].text
        assert "no validation record" in text, (
            "refusal must name the 'no validation record' invariant so the "
            f"agent knows this is missing-validation (not a hash mismatch); got: {text!r}"
        )
        # And — crucially — it must NOT produce the old generic message, which
        # was the exact text that drove the run_train.py wrapper workaround.
        assert "has not been validated" not in text, (
            "refusal must NOT use the old generic 'has not been validated' "
            f"text that drove wrapper-script workarounds (review Finding 8); got: {text!r}"
        )
        assert not stub.calls, (
            f"refusal must block execution; got stub.calls={stub.calls!r}"
        )
    finally:
        cleanup()


# ------------------------------------------------------------------
# Test 4: the refusal text is ACTIONABLE — names the invariant, shows hashes
# ------------------------------------------------------------------


def test_refusal_message_is_actionable_on_hash_mismatch(tmp_path):
    """Assert concrete, agent-actionable content: refusal names what was
    checked, shows both hashes, and tells the agent what tool to call."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        vobs = _validate(session_id, script_content=_VALID_SCRIPT)
        assert vobs.valid, f"prereq: validate must accept initial script; {vobs.errors!r}"

        # Edit disk so hashes diverge.
        edited = _VALID_SCRIPT + "\n# edit\n"
        (stub.root / "train.py").write_text(edited)

        robs = _run(session_id, workspace=stub, config=deps.config, quick_check=True)
        text = robs.content[0].text

        # 1. Names the invariant
        assert "hash mismatch" in text, (
            f"refusal must name the invariant 'hash mismatch'; got: {text!r}"
        )
        # 2. Shows the last validated hash
        assert vobs.validated_hash in text, (
            "refusal must show last_validated_hash; "
            f"expected {vobs.validated_hash!r} in: {text!r}"
        )
        # 3. Names the two hashes explicitly
        assert "last_validated_hash" in text, (
            f"refusal must label last_validated_hash; got: {text!r}"
        )
        assert "current_hash" in text, (
            f"refusal must label current_hash; got: {text!r}"
        )
        # 4. Tells the agent what to do next
        assert "validate_script" in text, (
            f"refusal must point at validate_script as the next action; got: {text!r}"
        )
    finally:
        cleanup()


def test_refusal_message_is_actionable_when_never_validated(tmp_path):
    """Companion to the hash-mismatch actionability check: the
    never-validated branch must also name the invariant and point at a
    concrete next action, not the old vague text."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        robs = _run(session_id, workspace=stub, config=deps.config, quick_check=True)
        text = robs.content[0].text

        assert "no validation record" in text, (
            f"refusal must name 'no validation record' invariant; got: {text!r}"
        )
        assert "validate_script" in text, (
            f"refusal must point at validate_script; got: {text!r}"
        )
        # Nothing about 'run_train.py' / wrappers — we want to steer the
        # agent TOWARD validate_script, not away from run_experiment.
        assert "run_train.py" not in text.lower(), (
            f"refusal must not suggest wrapper scripts; got: {text!r}"
        )
    finally:
        cleanup()


def test_feature_extraction_run_ignores_training_iteration_budget(tmp_path):
    """External feature extraction is setup for external validation, not a
    ratcheted training iteration, so it must still execute after the training
    iteration budget has been consumed.
    """
    script = '''\
#!/usr/bin/env bash
mkdir -p "$DATA_OUTPUT_DIR/features/virchow2/debug"
printf fake > "$DATA_OUTPUT_DIR/features/virchow2/debug/example.pt"
printf '{"patches_extracted": 1}' > "$OUTPUT_DIR/metrics.json"
'''
    session_id, deps, stub, cleanup = _register_handoff_session(
        tmp_path,
        initial_script=script,
    )
    try:
        script_path = stub.root / "feature_extraction_launcher.sh"
        script_path.write_text(script)
        deps.iteration_state.remaining_budget = 0
        deps.iteration_state.iteration_index = deps.iteration_state.max_iterations
        deps.config.planned_data_output_dir = str(tmp_path / "feature_output")
        deps.config.planned_feature_extractor = "virchow2"
        expected_feature = tmp_path / "feature_output" / "features" / "virchow2" / "debug" / "example.pt"
        expected_feature.parent.mkdir(parents=True)
        expected_feature.write_bytes(b"pt")

        vobs = _validate(session_id, script_path="feature_extraction_launcher.sh")
        assert vobs.valid, f"prereq: feature extraction launcher must validate; {vobs.errors!r}"

        robs = _run(
            session_id,
            workspace=stub,
            config=deps.config,
            quick_check=True,
            script_path="feature_extraction_launcher.sh",
            script_type="bash",
            run_kind="feature_extraction",
        )

        assert robs.exit_code == 0, (
            "feature_extraction run_experiment should not be blocked by "
            f"training iteration budget; got content={robs.content!r}"
        )
        assert stub.calls, "policy should allow the feature extraction script to execute"
    finally:
        cleanup()


# ------------------------------------------------------------------
# Bonus: validate_script refuses when script_content disagrees with disk
# ------------------------------------------------------------------


def test_validate_rejects_content_that_disagrees_with_disk(tmp_path):
    """Belt-and-suspenders: catch the drift at validate-time too. If the
    agent's ``script_content`` parameter does not match the file on disk,
    validate_script must refuse and show both hashes so the agent can see
    which side is stale."""
    session_id, deps, stub, cleanup = _register_handoff_session(tmp_path)
    try:
        supplied = _VALID_SCRIPT + "\n# agent-side paraphrase\n"
        vobs = _validate(session_id, script_content=supplied)
        assert vobs.valid is False, (
            "validate_script must refuse when script_content != disk content; "
            f"got valid=True with hash={vobs.validated_hash!r}"
        )
        # Combined errors text — the drift message mentions both hashes.
        joined = "\n".join(vobs.errors)
        assert "does not match" in joined, (
            f"mismatch errors must say 'does not match'; got: {joined!r}"
        )
        assert "supplied_hash" in joined and "disk_hash" in joined, (
            "drift error must show both hashes to help the agent locate the "
            f"stale side; got: {joined!r}"
        )
        # And iteration_state must NOT have been marked validated.
        assert deps.iteration_state.last_validated_hash == "", (
            "validation must not record a hash when it rejected the call; "
            f"got state={deps.iteration_state.last_validated_hash!r}"
        )
    finally:
        cleanup()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
