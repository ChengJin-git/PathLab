"""
Feature Extractor Template
==========================

This is a template for creating new feature extractors.
Copy this file and rename it to your extractor name (e.g., uni.py, vit.py, conch.py).

Steps to add a new feature extractor:
1. Copy this file to a new file (e.g., uni.py)
2. Rename the class (e.g., UNIExtractor)
3. Implement the __init__ method to load your model
4. Set self._output_dim to your model's feature dimension
5. Implement the forward method for feature extraction
6. Register in registry.py: from .uni import UNIExtractor
7. Add to _EXTRACTOR_REGISTRY: "uni": UNIExtractor

Example usage after registration:
    from smartresearch.services.backend.ai.extractors import get_extractor
    extractor = get_extractor("your_model_name", pretrained=True)
    features = extractor(images)  # [B, 3, H, W] -> [B, output_dim]
"""
from __future__ import annotations
import torch
import torch.nn as nn
from .base import BaseExtractor


class TemplateExtractor(BaseExtractor):
    """
    Template Feature Extractor.
    
    Replace this docstring with your model description.
    Example: "ResNet50 feature extractor pretrained on ImageNet."
    """
    
    def __init__(self, pretrained: bool = True, **kwargs):
        """
        Initialize the feature extractor.
        
        Args:
            pretrained: Whether to load pretrained weights
            **kwargs: Additional model-specific arguments
                     (e.g., model_path, config_path, custom hyperparameters)
        
        Example:
            def __init__(self, pretrained: bool = True, model_path: str = None):
                super().__init__()
                if pretrained and model_path:
                    self.model = load_from_checkpoint(model_path)
                else:
                    self.model = create_model()
                self._output_dim = 2048
        """
        super().__init__()
        
        # TODO: Load your model here
        # Option 1: Load from torchvision
        # from torchvision.models import resnet50
        # self.model = resnet50(pretrained=pretrained)
        
        # Option 2: Load from timm
        # import timm
        # self.model = timm.create_model('vit_base_patch16_224', pretrained=pretrained)
        
        # Option 3: Load from custom checkpoint
        # if pretrained:
        #     checkpoint = torch.load(kwargs.get('model_path', 'path/to/checkpoint.pth'))
        #     self.model.load_state_dict(checkpoint['state_dict'])
        
        # Option 4: Load from Hugging Face
        # from transformers import AutoModel
        # self.model = AutoModel.from_pretrained('model_name')
        
        self.model = None  # TODO: Replace with your model
        
        # TODO: Set the output feature dimension
        # This should match the dimension of features returned by forward()
        # Common values: 512 (ResNet18), 2048 (ResNet50), 768 (ViT-B), 1024 (UNI)
        self._output_dim = 2048  # TODO: Replace with your model's feature dimension
    
    @property
    def output_dim(self) -> int:
        """
        Return the output feature dimension.
        
        This property is used by the training pipeline to determine
        the input dimension for the aggregator model.
        
        Returns:
            int: Feature dimension (e.g., 2048 for ResNet50)
        """
        return self._output_dim
    
    @torch.inference_mode()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.
        
        This method should:
        1. Take a batch of images as input
        2. Pass them through your feature extraction model
        3. Return a batch of feature vectors
        
        Args:
            x: Input images, shape [B, 3, H, W]
               - B: batch size
               - 3: RGB channels
               - H, W: image height and width (typically 224 or 512)
        
        Returns:
            features: Extracted features, shape [B, output_dim]
                     - B: batch size (same as input)
                     - output_dim: feature dimension (e.g., 2048)
        
        Example implementation:
            features = self.model(x)  # [B, output_dim, 1, 1] or [B, output_dim]
            features = features.flatten(1)  # Ensure [B, output_dim]
            return features
        """
        # TODO: Implement feature extraction
        # Make sure to:
        # 1. Handle different input sizes if needed
        # 2. Remove classification head if present
        # 3. Flatten spatial dimensions to get [B, output_dim]
        # 4. Return features in the correct shape
        
        # Example for CNN-based models (ResNet, EfficientNet, etc.):
        # features = self.model(x)  # May return [B, C, H, W]
        # features = torch.flatten(features, 1)  # Flatten to [B, C*H*W]
        # return features
        
        # Example for Transformer-based models (ViT, etc.):
        # outputs = self.model(x)
        # features = outputs.last_hidden_state[:, 0]  # CLS token
        # return features
        
        raise NotImplementedError("Please implement the forward method")
    
    @classmethod
    def build(cls, pretrained: bool = True, **kwargs) -> TemplateExtractor:
        """
        Factory method to create an instance of this extractor.
        
        This method is called by the registry when you use:
            get_extractor("your_model_name", pretrained=True, **kwargs)
        
        Args:
            pretrained: Whether to load pretrained weights
            **kwargs: Additional arguments to pass to __init__
        
        Returns:
            An instance of this extractor
        
        Example:
            @classmethod
            def build(cls, pretrained: bool = True, **kwargs):
                return cls(
                    pretrained=pretrained,
                    model_path=kwargs.get('model_path', None),
                    custom_arg=kwargs.get('custom_arg', 'default_value')
                )
        """
        return cls(pretrained=pretrained, **kwargs)


# ==============================================================================
# CHECKLIST BEFORE REGISTERING
# ==============================================================================
# [ ] Renamed class from TemplateExtractor to YourExtractor
# [ ] Implemented __init__ to load your model
# [ ] Set self._output_dim to correct value
# [ ] Implemented forward() method
# [ ] Tested forward() returns shape [B, output_dim]
# [ ] Added import in registry.py: from .your_file import YourExtractor
# [ ] Added to _EXTRACTOR_REGISTRY: "your_name": YourExtractor
# [ ] Tested with: get_extractor("your_name", pretrained=True)

# ==============================================================================
# COMMON PITFALLS
# ==============================================================================
# 1. Forgetting to remove classification head from pretrained models
#    Solution: Use num_classes=0 or manually remove the last layer
#
# 2. Returning wrong shape (e.g., [B, C, H, W] instead of [B, output_dim])
#    Solution: Use torch.flatten(features, 1) or features.view(B, -1)
#
# 3. Not using @torch.inference_mode() decorator
#    Solution: Add @torch.inference_mode() before forward() for efficiency
#
# 4. Incorrect output_dim value
#    Solution: Print features.shape in forward() to verify the dimension
#
# 5. Model not in eval mode during inference
#    Solution: Call .eval() in __init__ or ensure it's called before forward()

