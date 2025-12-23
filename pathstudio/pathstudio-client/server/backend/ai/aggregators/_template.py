"""
Aggregator Template
===================

This is a template for creating new aggregators (MIL models).
Copy this file and rename it to your aggregator name (e.g., transmil.py, clam.py).

Steps to add a new aggregator:
1. Copy this file to a new file (e.g., transmil.py)
2. Rename the class (e.g., TransMILAggregator)
3. Implement the __init__ method to build your model architecture
4. Implement the forward method for bag-level prediction
5. Implement the build class method (usually just pass through to __init__)
6. Register in registry.py: from .transmil import TransMILAggregator
7. Add to _AGGREGATOR_REGISTRY: "transmil": TransMILAggregator

Example usage after registration:
    from pathstudio.services.backend.ai.aggregators import get_aggregator
    aggregator = get_aggregator("your_model_name", in_dim=2048, num_classes=3)
    logits, attention = aggregator(instance_features)  # [N, in_dim] -> [1, num_classes]
"""
from __future__ import annotations
from typing import Tuple, Optional
import torch
import torch.nn as nn
from .base import BaseAggregator


class TemplateAggregator(BaseAggregator):
    """
    Template Aggregator for Multiple Instance Learning.
    
    Replace this docstring with your model description.
    Example: "ABMIL aggregator using gated attention mechanism."
    
    This aggregator takes a bag of instance features and produces:
    1. A bag-level prediction (logits)
    2. Optional attention weights showing which instances are important
    """
    
    def __init__(
        self,
        in_dim: int,
        num_classes: int,
        hidden_dim: int = 256,
        dropout: float = 0.25,
        **kwargs
    ):
        """
        Initialize the aggregator.
        
        Args:
            in_dim: Input feature dimension (from feature extractor)
                   Example: 2048 for ResNet50, 1024 for UNI
            num_classes: Number of output classes
                        Example: 2 for binary classification, 3 for 3-class
            hidden_dim: Hidden layer dimension (model-specific)
            dropout: Dropout rate for regularization
            **kwargs: Additional model-specific arguments
        
        Example:
            def __init__(self, in_dim, num_classes, num_heads=8, num_layers=2):
                super().__init__(in_dim, num_classes)
                self.transformer = nn.TransformerEncoder(...)
                self.classifier = nn.Linear(in_dim, num_classes)
        """
        super().__init__(in_dim=in_dim, num_classes=num_classes)
        
        # TODO: Build your model architecture here
        # Common components:
        # 1. Attention mechanism (to weight instances)
        # 2. Feature aggregation (to combine weighted instances)
        # 3. Classification head (to produce final logits)
        
        # Example 1: Simple attention-based aggregator
        # self.attention = nn.Sequential(
        #     nn.Linear(in_dim, hidden_dim),
        #     nn.Tanh(),
        #     nn.Linear(hidden_dim, 1)
        # )
        # self.classifier = nn.Linear(in_dim, num_classes)
        
        # Example 2: Gated attention (ABMIL-style)
        # self.attention_V = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.Tanh())
        # self.attention_U = nn.Sequential(nn.Linear(in_dim, hidden_dim), nn.Sigmoid())
        # self.attention_weights = nn.Linear(hidden_dim, 1)
        # self.classifier = nn.Linear(in_dim, num_classes)
        
        # Example 3: Transformer-based (TransMIL-style)
        # self.feature_proj = nn.Linear(in_dim, hidden_dim)
        # encoder_layer = nn.TransformerEncoderLayer(d_model=hidden_dim, nhead=8)
        # self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
        # self.classifier = nn.Linear(hidden_dim, num_classes)
        
        # Example 4: Instance-level + bag-level (CLAM-style)
        # self.instance_classifier = nn.Linear(in_dim, num_classes)
        # self.attention = nn.Sequential(...)
        # self.bag_classifier = nn.Linear(in_dim, num_classes)
        
        self.attention = None  # TODO: Replace with your attention mechanism
        self.classifier = None  # TODO: Replace with your classifier
        self.dropout = nn.Dropout(dropout)
    
    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Aggregate instance features to produce bag-level prediction.
        
        This method should:
        1. Take a bag of instance features as input
        2. Compute attention weights (optional but recommended)
        3. Aggregate instances using attention weights
        4. Produce bag-level classification logits
        
        Args:
            H: Instance features, shape [N, in_dim]
               - N: number of instances in the bag (variable, e.g., 100-10000)
               - in_dim: feature dimension (e.g., 2048)
        
        Returns:
            Tuple of (logits, attention_weights):
            - logits: Bag-level prediction, shape [1, num_classes]
                     Note: Shape is [1, num_classes] not [num_classes]
            - attention_weights: Instance importance, shape [N] or None
                                Higher values = more important instances
        
        Example implementation (attention-based):
            # Compute attention scores
            A = self.attention(H)  # [N, 1]
            A = torch.softmax(A, dim=0)  # [N, 1]
            
            # Aggregate features
            M = torch.sum(A * H, dim=0, keepdim=True)  # [1, in_dim]
            
            # Classify
            logits = self.classifier(M)  # [1, num_classes]
            
            return logits, A.squeeze(-1)  # [1, num_classes], [N]
        """
        # TODO: Implement your aggregation logic
        # Make sure to:
        # 1. Handle variable bag sizes (N can be different for each WSI)
        # 2. Return logits with shape [1, num_classes]
        # 3. Return attention weights with shape [N] (or None if not applicable)
        
        # Example 1: Mean pooling (simplest baseline)
        # M = H.mean(dim=0, keepdim=True)  # [1, in_dim]
        # logits = self.classifier(M)  # [1, num_classes]
        # return logits, None
        
        # Example 2: Max pooling
        # M = H.max(dim=0, keepdim=True)[0]  # [1, in_dim]
        # logits = self.classifier(M)  # [1, num_classes]
        # return logits, None
        
        # Example 3: Attention-based pooling (recommended)
        # A = self.attention(H)  # [N, 1]
        # A = torch.softmax(A, dim=0)  # [N, 1]
        # M = torch.sum(A * H, dim=0, keepdim=True)  # [1, in_dim]
        # logits = self.classifier(M)  # [1, num_classes]
        # return logits, A.squeeze(-1)
        
        # Example 4: Gated attention (ABMIL-style)
        # A_V = self.attention_V(H)  # [N, hidden_dim]
        # A_U = self.attention_U(H)  # [N, hidden_dim]
        # A = self.attention_weights(A_V * A_U)  # [N, 1]
        # A = torch.softmax(A, dim=0)  # [N, 1]
        # M = torch.sum(A * H, dim=0, keepdim=True)  # [1, in_dim]
        # logits = self.classifier(M)  # [1, num_classes]
        # return logits, A.squeeze(-1)
        
        raise NotImplementedError("Please implement the forward method")
    
    @classmethod
    def build(cls, in_dim: int, num_classes: int, **kwargs) -> TemplateAggregator:
        """
        Factory method to create an instance of this aggregator.
        
        This method is called by the registry when you use:
            get_aggregator("your_model_name", in_dim=2048, num_classes=3, **kwargs)
        
        Args:
            in_dim: Input feature dimension
            num_classes: Number of output classes
            **kwargs: Additional arguments to pass to __init__
        
        Returns:
            An instance of this aggregator
        
        Example:
            @classmethod
            def build(cls, in_dim: int, num_classes: int, **kwargs):
                return cls(
                    in_dim=in_dim,
                    num_classes=num_classes,
                    hidden_dim=kwargs.get('hidden_dim', 256),
                    num_heads=kwargs.get('num_heads', 8),
                    dropout=kwargs.get('dropout', 0.25)
                )
        """
        return cls(
            in_dim=in_dim,
            num_classes=num_classes,
            hidden_dim=kwargs.get('hidden_dim', 256),
            dropout=kwargs.get('dropout', 0.25),
            **kwargs
        )


# ==============================================================================
# CHECKLIST BEFORE REGISTERING
# ==============================================================================
# [ ] Renamed class from TemplateAggregator to YourAggregator
# [ ] Implemented __init__ to build model architecture
# [ ] Implemented forward() method
# [ ] Tested forward() returns (logits, attention) with correct shapes
# [ ] Verified logits shape is [1, num_classes] not [num_classes]
# [ ] Verified attention shape is [N] or None
# [ ] Implemented build() class method
# [ ] Added import in registry.py: from .your_file import YourAggregator
# [ ] Added to _AGGREGATOR_REGISTRY: "your_name": YourAggregator
# [ ] Tested with: get_aggregator("your_name", in_dim=2048, num_classes=3)

# ==============================================================================
# COMMON PITFALLS
# ==============================================================================
# 1. Returning wrong logits shape (e.g., [num_classes] instead of [1, num_classes])
#    Solution: Use keepdim=True or unsqueeze(0) to maintain batch dimension
#
# 2. Attention weights not summing to 1
#    Solution: Use torch.softmax(A, dim=0) to normalize attention scores
#
# 3. Not handling variable bag sizes
#    Solution: Avoid hardcoding N, use dynamic operations like .mean(), .sum()
#
# 4. Forgetting to return attention weights
#    Solution: Return (logits, attention) tuple, use None if no attention
#
# 5. Dimension mismatch between in_dim and feature extractor output
#    Solution: Check extractor.output_dim matches aggregator in_dim
#
# 6. Not using dropout for regularization
#    Solution: Add nn.Dropout layers, especially before classification head
#
# 7. Attention mechanism producing NaN values
#    Solution: Check for numerical stability, use torch.clamp or add epsilon

# ==============================================================================
# TESTING YOUR AGGREGATOR
# ==============================================================================
# Run this code to test your aggregator before registering:
#
# if __name__ == "__main__":
#     # Test with random data
#     in_dim = 2048
#     num_classes = 3
#     N = 1000  # Number of instances
#     
#     # Create aggregator
#     aggregator = TemplateAggregator(in_dim=in_dim, num_classes=num_classes)
#     aggregator.eval()
#     
#     # Create random instance features
#     H = torch.randn(N, in_dim)
#     
#     # Forward pass
#     logits, attention = aggregator(H)
#     
#     # Verify shapes
#     assert logits.shape == (1, num_classes), f"Expected [1, {num_classes}], got {logits.shape}"
#     if attention is not None:
#         assert attention.shape == (N,), f"Expected [{N}], got {attention.shape}"
#         assert torch.allclose(attention.sum(), torch.tensor(1.0), atol=1e-5), "Attention should sum to 1"
#     
#     print("✓ All tests passed!")
#     print(f"  Logits shape: {logits.shape}")
#     print(f"  Attention shape: {attention.shape if attention is not None else None}")

