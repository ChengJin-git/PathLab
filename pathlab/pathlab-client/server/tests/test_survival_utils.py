import numpy as np
import torch

from backend.ai.survival import compute_risk_from_survival, compute_survival_from_hazards


def test_compute_survival_from_hazards_supports_numpy_arrays():
    hazards = np.asarray([0.25, 0.5, 0.1])

    survival = compute_survival_from_hazards(hazards)

    np.testing.assert_allclose(survival, np.asarray([0.75, 0.375, 0.3375]))


def test_compute_risk_from_survival_supports_numpy_arrays():
    survival = np.asarray([0.75, 0.375, 0.3375])

    risk = compute_risk_from_survival(survival)

    assert risk == -1.4625


def test_survival_helpers_preserve_torch_tensor_inputs():
    hazards = torch.tensor([[0.25, 0.5, 0.1], [0.1, 0.2, 0.3]])


    survival = compute_survival_from_hazards(hazards)
    risk = compute_risk_from_survival(survival)

    expected_survival = torch.tensor([[0.75, 0.375, 0.3375], [0.9, 0.72, 0.504]])

    assert isinstance(survival, torch.Tensor)
    assert isinstance(risk, torch.Tensor)
    torch.testing.assert_close(survival, expected_survival)
    torch.testing.assert_close(risk, torch.tensor([-1.4625, -2.124]))
