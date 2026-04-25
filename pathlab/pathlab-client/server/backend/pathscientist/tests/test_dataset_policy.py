from __future__ import annotations

from dataset.policy import AcquisitionPolicy, PolicyDecision


def test_default_policy_allows_public_small():
    decision = AcquisitionPolicy().allow(access="public", estimated_size_gb=1.0)
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_public_only_rejects_gated_records():
    decision = AcquisitionPolicy(download_policy="public_only").allow(
        access="gated", estimated_size_gb=1.0
    )
    assert decision.allowed is False
    assert "access" in decision.reason


def test_public_only_rejects_manual_records():
    decision = AcquisitionPolicy(download_policy="public_only").allow(
        access="manual", estimated_size_gb=1.0
    )
    assert decision.allowed is False


def test_manual_only_allows_manual_rejects_public():
    pol = AcquisitionPolicy(download_policy="manual_only")
    assert pol.allow(access="manual", estimated_size_gb=1.0).allowed is True
    assert pol.allow(access="public", estimated_size_gb=1.0).allowed is False


def test_disabled_policy_blocks_everything():
    pol = AcquisitionPolicy(download_policy="disabled")
    assert pol.allow(access="public", estimated_size_gb=0.1).allowed is False


def test_large_download_rejected_by_default():
    decision = AcquisitionPolicy(max_download_size_gb=20.0).allow(
        access="public", estimated_size_gb=700.0
    )
    assert decision.allowed is False
    assert decision.reason == "too_large"


def test_large_download_allowed_with_opt_in():
    decision = AcquisitionPolicy(max_download_size_gb=20.0, allow_large_downloads=True).allow(
        access="public", estimated_size_gb=700.0
    )
    assert decision.allowed is True


def test_size_at_threshold_is_allowed():
    pol = AcquisitionPolicy(max_download_size_gb=20.0)
    assert pol.allow(access="public", estimated_size_gb=20.0).allowed is True


def test_decision_is_dataclass():
    """PolicyDecision should be hashable / comparable as a dataclass."""
    d = PolicyDecision(True, "ok")
    assert d.allowed is True
    assert d.reason == "ok"
