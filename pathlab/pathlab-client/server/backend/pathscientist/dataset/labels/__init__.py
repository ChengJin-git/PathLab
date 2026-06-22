"""Label-resolution helpers for acquired pathology datasets."""
from .tcga import TCGALabelResolutionSkill
from .types import LabelResolutionResult, LabelSpec

__all__ = ["LabelResolutionResult", "LabelSpec", "TCGALabelResolutionSkill"]
