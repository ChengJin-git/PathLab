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
6. (Optional) Override preprocessing properties/methods if needed
7. Register in registry.py: from .uni import UNIExtractor
8. Add to _EXTRACTOR_REGISTRY: "uni": UNIExtractor

Example usage after registration:
    from pathhub.services.backend.ai.extractors import get_extractor
    extractor = get_extractor("your_model_name", pretrained=True)

    # Get model-specific preprocessing transforms
    transform = extractor.get_transforms(mode="eval")

    # Extract features
    features = extractor(images)  # [B, 3, H, W] -> [B, output_dim]
"""
from __future__ import annotations
from typing import Tuple, Callable

import torch
import torch.nn as nn

from .base import BaseExtractor
from .transforms import (
    get_default_transforms,
    IMAGENET_MEAN,
    IMAGENET_STD,
    OPENAI_CLIP_MEAN,
    OPENAI_CLIP_STD,
)


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

    # =========================================================================
    # PREPROCESSING CONFIGURATION (Optional Overrides)
    # =========================================================================
    # The following properties and methods control how images are preprocessed
    # before being fed to the model. Override these if your model requires
    # different preprocessing than the default ImageNet transforms.

    @property
    def default_image_size(self) -> int:
        """
        Return the expected input image size.

        Override if your model expects a different size than 224x224.
        Common sizes: 224 (ResNet, ViT-B), 384 (ViT-L/14), 512 (some pathology models)
        """
        return 224  # TODO: Change if your model needs different size

    @property
    def normalization_mean(self) -> Tuple[float, float, float]:
        """
        Return the normalization mean for preprocessing.

        Override for models using non-ImageNet normalization.
        Examples:
        - ImageNet: (0.485, 0.456, 0.406)  <- default
        - CLIP: (0.48145466, 0.4578275, 0.40821073)
        """
        return IMAGENET_MEAN  # TODO: Change if your model uses different normalization

    @property
    def normalization_std(self) -> Tuple[float, float, float]:
        """
        Return the normalization std for preprocessing.

        Override for models using non-ImageNet normalization.
        Examples:
        - ImageNet: (0.229, 0.224, 0.225)  <- default
        - CLIP: (0.26862954, 0.26130258, 0.27577711)
        """
        return IMAGENET_STD  # TODO: Change if your model uses different normalization

    def get_transforms(self, mode: str = "eval") -> Callable:
        """
        Get preprocessing transforms for this model.

        Override this method if your model requires completely custom
        preprocessing (e.g., special augmentations, stain normalization).

        Args:
            mode: "train" for training with augmentation,
                  "eval" for inference without augmentation

        Returns:
            Callable transform that converts PIL Image to normalized Tensor

        Example for CLIP-based model:
            def get_transforms(self, mode: str = "eval") -> Callable:
                return get_default_transforms(
                    image_size=self.default_image_size,
                    mode=mode,
                    mean=OPENAI_CLIP_MEAN,
                    std=OPENAI_CLIP_STD,
                )

        Example for model with special preprocessing:
            def get_transforms(self, mode: str = "eval") -> Callable:
                # Use model's built-in preprocessing
                return self.model.get_preprocess_transform()
        """
        # Default: use base class implementation which calls get_default_transforms
        # with self.normalization_mean/std and self.default_image_size
        return get_default_transforms(
            image_size=self.default_image_size,
            mode=mode,
            mean=self.normalization_mean,
            std=self.normalization_std,
        )
    
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
# [ ] (If needed) Override default_image_size, normalization_mean/std, or get_transforms()
# [ ] Added import in registry.py: from .your_file import YourExtractor
# [ ] Added to _EXTRACTOR_REGISTRY: "your_name": YourExtractor
# [ ] Tested with: get_extractor("your_name", pretrained=True)
# [ ] Tested transforms: extractor.get_transforms("eval")

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
#
# 6. Using wrong normalization for CLIP-based models (UNI, CONCH, etc.)
#    Solution: Override normalization_mean/std or get_transforms() method
#
# 7. Forgetting to set default_image_size for models expecting non-224 input
#    Solution: Override default_image_size property

