"""
Loss functions for segmentation tasks using segmentation_models_pytorch.
"""
from typing import List, Optional, Union
import torch
import torch.nn as nn
import segmentation_models_pytorch as smp
from segmentation_models_pytorch.losses import (
    DiceLoss,
    JaccardLoss,
    FocalLoss,
    TverskyLoss,
    LovaszLoss,
    SoftBCEWithLogitsLoss,
    SoftCrossEntropyLoss,
    MCCLoss
)
from segmentation_models_pytorch.losses import constants

# Constants
BINARY_MODE: str = constants.BINARY_MODE
MULTICLASS_MODE: str = constants.MULTICLASS_MODE
MULTILABEL_MODE: str = constants.MULTILABEL_MODE

__all__ = [
    "BINARY_MODE",
    "MULTICLASS_MODE",
    "MULTILABEL_MODE",
    "DiceLoss",
    "JaccardLoss",
    "FocalLoss",
    "TverskyLoss",
    "LovaszLoss",
    "SoftBCEWithLogitsLoss",
    "SoftCrossEntropyLoss",
    "MCCLoss",
    "get_loss",
    "CombinedLoss",
]


def get_loss(
    name: str,
    mode: str = MULTICLASS_MODE,
    classes: Optional[List[int]] = None,
    log_loss: bool = False,
    from_logits: bool = True,
    smooth: float = 0.0,
    ignore_index: Optional[int] = None,
    eps: float = 1e-7,
    alpha: float = 0.5,
    beta: float = 0.5,
    gamma: float = 2.0,
    normalized: bool = False,
    reduction: str = "mean",
    smooth_factor: Optional[float] = None,
    **kwargs
) -> nn.Module:
    """
    Factory to get loss function by name from segmentation_models_pytorch.
    
    Args:
        name: Name of the loss function (e.g., 'DiceLoss', 'JaccardLoss', 'FocalLoss', 'CE', 'BCE')
        mode: 'binary', 'multiclass', or 'multilabel'
        classes: List of classes that contribute in loss computation
        log_loss: If True, loss computed as -log(metric)
        from_logits: If True, assumes input is raw logits
        smooth: Smoothness constant for dice/jaccard
        ignore_index: Label that indicates ignored pixels
        eps: Small epsilon for numerical stability
        alpha: Weight constant for TverskyLoss/FocalLoss
        beta: Weight constant for TverskyLoss
        gamma: Power factor for FocalLoss/TverskyLoss
        normalized: Compute normalized FocalLoss
        reduction: Reduction method ('mean', 'sum', 'none')
        smooth_factor: Label smoothing factor for SoftCrossEntropy/SoftBCE
    """
    
    if name == "DiceLoss":
        return DiceLoss(
            mode=mode, classes=classes, log_loss=log_loss, 
            from_logits=from_logits, smooth=smooth, ignore_index=ignore_index, eps=eps
        )
    
    elif name == "JaccardLoss":
        return JaccardLoss(
            mode=mode, classes=classes, log_loss=log_loss, 
            from_logits=from_logits, smooth=smooth, eps=eps
        )
        
    elif name == "TverskyLoss":
        return TverskyLoss(
            mode=mode, classes=classes, log_loss=log_loss, 
            from_logits=from_logits, smooth=smooth, ignore_index=ignore_index, eps=eps,
            alpha=alpha, beta=beta, gamma=gamma if gamma is not None else 1.0
        )
        
    elif name == "FocalLoss":
        return FocalLoss(
            mode=mode, alpha=alpha, gamma=gamma, ignore_index=ignore_index, 
            reduction=reduction, normalized=normalized
        )
        
    elif name == "LovaszLoss":
        return LovaszLoss(
            mode=mode, per_image=kwargs.get('per_image', False), 
            ignore_index=ignore_index, from_logits=from_logits
        )
        
    elif name == "SoftBCEWithLogitsLoss" or name == "BCE":
        return SoftBCEWithLogitsLoss(
            weight=kwargs.get('weight'), ignore_index=ignore_index if ignore_index is not None else -100,
            reduction=reduction, smooth_factor=smooth_factor, pos_weight=kwargs.get('pos_weight')
        )
        
    elif name == "SoftCrossEntropyLoss" or name == "CE":
        return SoftCrossEntropyLoss(
            reduction=reduction, smooth_factor=smooth_factor, 
            ignore_index=ignore_index if ignore_index is not None else -100,
            dim=kwargs.get('dim', 1)
        )
        
    elif name == "MCCLoss":
        return MCCLoss(eps=kwargs.get('eps', 1e-5))
        
    else:
        # Try to find in smp.losses
        if hasattr(smp.losses, name):
            loss_cls = getattr(smp.losses, name)
            # Pass all valid kwargs
            return loss_cls(mode=mode, **kwargs)
        else:
            raise ValueError(f"Loss {name} not found in segmentation_models_pytorch")


class CombinedLoss(nn.Module):
    """
    Combine multiple loss functions with weights.
    Example: DiceLoss + CrossEntropyLoss
    """
    def __init__(self, losses: List[nn.Module], weights: List[float]):
        super().__init__()
        assert len(losses) == len(weights)
        self.losses = nn.ModuleList(losses)
        self.weights = weights
        
    def forward(self, y_pred, y_true):
        total_loss = 0
        for loss_fn, weight in zip(self.losses, self.weights):
            total_loss += weight * loss_fn(y_pred, y_true)
        return total_loss

