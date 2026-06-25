"""Acquisition policy: gates which dataset records may be auto-downloaded.

Plan: docs/plans/2026-04-25-autoresearch-dataset-download-next-implementation-plan.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = "ok"


@dataclass
class AcquisitionPolicy:
    """Decide whether a candidate dataset is allowed to download.

    Defaults are conservative:
    - public_only: refuse gated/manual datasets
    - max 20 GB download by default; opt-in flag for larger
    """
    download_policy: str = "public_only"   # "disabled" | "public_only" | "manual_only" | "public_or_manual" | "all"
    max_download_size_gb: float = 20.0
    allow_large_downloads: bool = False

    def allow(self, *, access: str, estimated_size_gb: float) -> PolicyDecision:
        valid_policies = {
            "disabled",
            "public_only",
            "manual_only",
            "public_or_manual",
            "all",
        }
        if self.download_policy not in valid_policies:
            return PolicyDecision(False, f"invalid_policy:{self.download_policy}")
        if self.download_policy == "disabled":
            return PolicyDecision(False, "disabled")
        if self.download_policy == "public_only" and access != "public":
            return PolicyDecision(False, f"access={access}")
        if self.download_policy == "manual_only" and access != "manual":
            return PolicyDecision(False, f"access={access}")
        if self.download_policy == "public_or_manual" and access not in {"public", "manual"}:
            return PolicyDecision(False, f"access={access}")
        if estimated_size_gb > self.max_download_size_gb and not self.allow_large_downloads:
            return PolicyDecision(False, "too_large")
        return PolicyDecision(True, "ok")
