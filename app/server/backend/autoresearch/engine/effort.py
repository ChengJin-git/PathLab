"""Server-owned execution ceilings for the user-facing effort selector."""

from typing import Literal

ResearchEffort = Literal["low", "medium", "high"]
ResearchStandard = Literal["standard", "scientific"]

# (experiment attempts, wall-clock seconds); useful work may finish sooner. Scientific studies
# plan for full-data baselines and several pitches, so their ceilings span days.
EFFORT_BUDGETS: dict[ResearchStandard, dict[ResearchEffort, tuple[int, int]]] = {
    "standard": {"low": (3, 3600), "medium": (8, 14400), "high": (20, 43200)},
    "scientific": {"low": (36, 86400), "medium": (120, 172800), "high": (300, 259200)},
}

# Highest attempt ceiling any session can hold; advanced settings, study stages and
# continuations validate against it so a granted budget can always be resumed.
MAX_EXPERIMENTS = max(attempts for tiers in EFFORT_BUDGETS.values() for attempts, _ in tiers.values())


def effort_budget(effort: ResearchEffort, standard: ResearchStandard | None) -> tuple[int, int]:
    return EFFORT_BUDGETS["scientific" if standard == "scientific" else "standard"][effort]
