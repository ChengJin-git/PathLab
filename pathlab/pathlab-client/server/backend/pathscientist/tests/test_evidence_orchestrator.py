"""Tests for evidence ↔ orchestrator RunRecord linkage."""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.types import RunRecord


def test_run_record_uses_canonical_runtime_run_id():
    record = RunRecord(run_id="run_abc123", iteration=0)
    assert record.run_id == "run_abc123"


def test_run_record_run_id_matches_evidence_path_convention():
    """RunRecord.run_id should be usable as .evidence/runs/<run_id>/ directory name.

    After Fix 5, run_ids have canonical shape ``run_<hex8>`` so the
    evidence-store directory name preserves the ``run_`` prefix.
    """
    record = RunRecord(run_id="run_a1b2c3d4", iteration=0, metric_value=0.85, committed=True)
    evidence_path = f".evidence/runs/{record.run_id}/record.json"
    assert "run_a1b2c3d4" in evidence_path


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
