"""Tests for runtime iteration policy enforcement."""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

import pytest

from autoresearch.runtime.iteration_state import IterationState, PolicyViolation


def test_full_run_blocked_without_validation():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    # No prior validate_script call — refusal names the "no validation record"
    # invariant so the agent can distinguish this from a stale-hash mismatch.
    with pytest.raises(PolicyViolation, match="no validation record"):
        state.check_can_full_run(file_hash)


def test_full_run_blocked_without_quick_check():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    state.mark_validated(file_hash)
    with pytest.raises(PolicyViolation, match="not passed quick check"):
        state.check_can_full_run(file_hash)


def test_full_run_allowed_after_validate_and_quick_check():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    state.mark_validated(file_hash)
    state.mark_quick_check_passed(file_hash)
    # Should not raise
    state.check_can_full_run(file_hash)


def test_quick_check_blocked_without_validation():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    # See test_full_run_blocked_without_validation — same message contract.
    with pytest.raises(PolicyViolation, match="no validation record"):
        state.check_can_quick_check(file_hash)


def test_quick_check_allowed_after_validation():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    state.mark_validated(file_hash)
    # Should not raise
    state.check_can_quick_check(file_hash)


def test_file_change_invalidates_previous_validation():
    state = IterationState(max_iterations=5)
    hash_v1 = "abc123"
    hash_v2 = "def456"

    state.mark_validated(hash_v1)
    state.mark_quick_check_passed(hash_v1)

    # File changed → new hash doesn't match recorded validation. This is
    # the "hash mismatch" branch (vs the "no validation record" branch).
    with pytest.raises(PolicyViolation, match="hash mismatch"):
        state.check_can_full_run(hash_v2)


def test_iteration_record_resets_hashes():
    state = IterationState(max_iterations=5)
    file_hash = "abc123"
    state.mark_validated(file_hash)
    state.mark_quick_check_passed(file_hash)

    # Record iteration → resets validation state
    state.record_iteration(metrics={"auc": 0.8}, committed=True)

    # Same hash no longer valid — need to re-validate. After the reset,
    # last_validated_hash is blank so this hits the "no validation record"
    # branch, not the hash-mismatch branch.
    with pytest.raises(PolicyViolation, match="no validation record"):
        state.check_can_quick_check(file_hash)


def test_budget_exhaustion():
    state = IterationState(max_iterations=2)

    # Burn both iterations
    state.record_iteration(metrics={}, committed=True)
    state.record_iteration(metrics={}, committed=False)

    assert state.remaining_budget == 0
    with pytest.raises(PolicyViolation, match="budget exhausted"):
        state.check_can_quick_check("any_hash")


def test_iteration_index_increments():
    state = IterationState(max_iterations=5)
    assert state.iteration_index == 0
    state.record_iteration(metrics={}, committed=True)
    assert state.iteration_index == 1
    state.record_iteration(metrics={}, committed=False)
    assert state.iteration_index == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
