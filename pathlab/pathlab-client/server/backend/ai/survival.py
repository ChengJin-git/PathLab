"""Shared survival-analysis utilities for AI tasks and gateway inference."""

from __future__ import annotations

from typing import cast, overload

import numpy as np
import numpy.typing as npt
import torch


@overload
def compute_survival_from_hazards(hazards: torch.Tensor) -> torch.Tensor:
    ...


@overload
def compute_survival_from_hazards(hazards: npt.ArrayLike) -> npt.NDArray[np.float64]:
    ...


def compute_survival_from_hazards(
    hazards: torch.Tensor | npt.ArrayLike,
) -> torch.Tensor | npt.NDArray[np.float64]:
    """Compute cumulative survival probabilities from discrete hazards."""
    if isinstance(hazards, torch.Tensor):
        return torch.cumprod(torch.ones_like(hazards) - hazards, dim=-1)
    return np.cumprod(1.0 - np.asarray(hazards, dtype=float), axis=-1)


@overload
def compute_risk_from_survival(survival: torch.Tensor) -> torch.Tensor:
    ...


@overload
def compute_risk_from_survival(
    survival: npt.ArrayLike,
) -> np.float64 | npt.NDArray[np.float64]:
    ...


def compute_risk_from_survival(
    survival: torch.Tensor | npt.ArrayLike,
) -> torch.Tensor | np.float64 | npt.NDArray[np.float64]:
    """Compute scalar risk score with higher values indicating higher risk."""
    if isinstance(survival, torch.Tensor):
        return -torch.sum(survival, dim=-1)
    return cast(
        np.float64 | npt.NDArray[np.float64],
        -np.sum(np.asarray(survival, dtype=float), axis=-1),
    )
