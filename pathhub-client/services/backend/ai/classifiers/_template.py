"""
Patch Classifier Template
=========================

This is a template for creating new patch-level classifiers.
Copy this file and rename it to your classifier name (e.g., linear_head.py, vit_patch.py).

Steps to add a new classifier:
1. Copy this file (e.g., to linear_head.py)
2. Rename the class (e.g., LinearHead)
3. Implement __init__/forward
4. Register in registry.py
5. Test with get_classifier("your_name", num_classes=..., in_dim=...)
"""
from __future__ import annotations
from typing import Any, Optional
import torch
import torch.nn as nn
from .base import BaseClassifier


class TemplateClassifier(BaseClassifier):
    """Template patch-level classifier.

    By default, this classifier expects feature vectors [B, D] and maps them to
    logits [B, num_classes]. For image-based classifiers, document the expected
    input shape [B, 3, H, W] clearly in this docstring and adapt forward().
    """

    def __init__(self, num_classes: int, in_dim: Optional[int] = None, **kwargs: Any):
        """
        Args:
            num_classes: number of output classes
            in_dim: input feature dimension (for feature-based classifiers)
            **kwargs: custom arguments (e.g., hidden_dim)
        """
        super().__init__(num_classes=num_classes, in_dim=in_dim)
        hidden_dim = int(kwargs.get("hidden_dim", 512))

        # Example: simple MLP head for feature vectors [B, in_dim]
        if in_dim is None:
            raise ValueError("TemplateClassifier expects in_dim for feature-based example")
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.Dropout(0.25),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, X: torch.Tensor) -> torch.Tensor:
        """
        Args:
            X: features [B, in_dim]
        Returns:
            logits: [B, num_classes]
        """
        return self.net(X)

    @classmethod
    def build(
        cls,
        num_classes: int,
        in_dim: Optional[int] = None,
        **kwargs: Any,
    ) -> TemplateClassifier:
        return cls(num_classes=num_classes, in_dim=in_dim, **kwargs)


# ==============================================================================
# CHECKLIST BEFORE REGISTERING
# ==============================================================================
# [ ] Renamed class from TemplateClassifier to YourClassifier
# [ ] Implemented __init__ & forward()
# [ ] Documented expected input shape (features or images)
# [ ] Added import in registry.py: from .your_file import YourClassifier
# [ ] Added to _CLASSIFIER_REGISTRY: "your_name": YourClassifier
# [ ] Tested with: get_classifier("your_name", num_classes=..., in_dim=...)

# ==============================================================================
# COMMON PITFALLS
# ==============================================================================
# 1) Wrong input shape: ensure features are [B, D] or images are [B, 3, H, W]
# 2) Forgetting to set in_dim for feature-based classifiers
# 3) Returning logits of shape [num_classes] instead of [B, num_classes]
# 4) Not using dropout/batchnorm when needed -> overfitting

