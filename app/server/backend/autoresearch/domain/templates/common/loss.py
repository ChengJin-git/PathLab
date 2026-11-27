from typing import Any
import torch



LOSS_MAPPING = {
    "CrossEntropyLoss": torch.nn.CrossEntropyLoss,
    "BCEWithLogitsLoss": torch.nn.BCEWithLogitsLoss,
}


class ClassificationLoss:
    def __init__(self, loss_cfg: dict[str, Any], loss_weights: dict[str, Any]):
        self.loss_fns = {}
        self.loss_weights = loss_weights
        for loss_name, params in loss_cfg.items():
            if loss_name in LOSS_MAPPING:
                self.loss_fns[loss_name] = LOSS_MAPPING[loss_name](**params)
            else:
                raise ValueError(f"Unsupported loss function: {loss_name}")

    def compute_loss(self, predictions, targets):
        total_loss = 0.0
        for loss_name, loss_fn in self.loss_fns.items():
            loss_value = loss_fn(predictions, targets)
            weight = self.loss_weights.get(loss_name, 1.0)
            total_loss += weight * loss_value
        return total_loss
    
    def __call__(self, predictions, targets):
        return self.compute_loss(predictions, targets)