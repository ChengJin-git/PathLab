"""Registry for feature extractors."""
from __future__ import annotations

from typing import Dict, Type, List, Callable

from .base import BaseExtractor
from .resnet50 import ResNet50Extractor
from .vit_l_16 import ViTL16Extractor
from .conch_model import CONCHExtractor
from .uni_model import UNIExtractor
from .uni2_model import UNI2Extractor
from .virchow_model import VirchowExtractor
from .virchow2_model import Virchow2Extractor
from .plip_model import PLIPExtractor
from .phikon_model import PhikonExtractor
from .phikon2_model import Phikon2Extractor
from .patho_clip_model import PathoCLIPExtractor
from .openmidnight_model import OpenMidnightExtractor
from .conch15_model import CONCH15Extractor
from .h_optimus_0_model import H_Optimus_0Extractor
from .h_optimus_1_model import H_Optimus_1Extractor
from .mSTAR_model import mSTARExtractor
from .gpfm_model import GPFMExtractor
from .transforms import get_default_transforms


# Global registry mapping extractor names to classes
_EXTRACTOR_REGISTRY: Dict[str, Type[BaseExtractor]] = {
    "resnet50": ResNet50Extractor,
    "vit_l_16": ViTL16Extractor,
    "conch": CONCHExtractor,
    "uni": UNIExtractor,
    "uni2": UNI2Extractor,
    'virchow': VirchowExtractor,
    'virchow2': Virchow2Extractor,
    'plip': PLIPExtractor,
    'phikon': PhikonExtractor,
    'phikon2': Phikon2Extractor,
    'patho_clip': PathoCLIPExtractor,
    'openmidnight': OpenMidnightExtractor,
    'conch15': CONCH15Extractor,
    'H-Optimus-1': H_Optimus_1Extractor,
    'H-Optimus-0': H_Optimus_0Extractor,
    'mSTAR': mSTARExtractor,
    'GPFM': GPFMExtractor,
}

_EXTRACTOR_METADATA: Dict[str, Dict[str, str]] = {
    "resnet50": {"name": "ResNet50", "description": "ImageNet pretrained, general-purpose"},
    "vit_l_16": {"name": "ViT-Large", "description": "Vision Transformer (Large), general-purpose"},
    "conch": {"name": "CONCH", "description": "Pathology foundation model (Mahmood Lab)"},
    "uni": {"name": "UNI", "description": "Universal pathology foundation model (Mahmood Lab)"},
    "uni2": {"name": "UNI2", "description": "Universal pathology foundation model v2 (Mahmood Lab)"},
    "virchow": {"name": "Virchow", "description": "Pathology foundation model (Paige AI)"},
    "virchow2": {"name": "Virchow2", "description": "Pathology foundation model v2 (Paige AI)"},
    "plip": {"name": "PLIP", "description": "Pathology Language-Image Pretraining"},
    "phikon": {"name": "Phikon", "description": "Pathology DINOv2 foundation model"},
    "phikon2": {"name": "Phikon2", "description": "Pathology DINOv2 foundation model v2"},
    "patho_clip": {"name": "PathoCLIP", "description": "Pathology-specific CLIP model"},
    "openmidnight": {"name": "OpenMidnight", "description": "Pathology foundation model"},
    "conch15": {"name": "CONCH 1.5", "description": "Pathology foundation model v1.5"},
    "H-Optimus-1": {"name": "H-Optimus-1", "description": "Pathology foundation model (H-Optimus)"},
    "H-Optimus-0": {"name": "H-Optimus-0", "description": "Pathology foundation model (H-Optimus)"},
    "mSTAR": {"name": "mSTAR", "description": "Pathology foundation model"},
    "GPFM": {"name": "GPFM", "description": "General Pathology Foundation Model"},
}


def register_extractor(name: str, extractor_class: Type[BaseExtractor]):
    """
    Register a new feature extractor.

    Args:
        name: Unique identifier for the extractor (e.g., "resnet50", "uni", "conch")
        extractor_class: Class inheriting from BaseExtractor
    """
    if name in _EXTRACTOR_REGISTRY:
        raise ValueError(f"Extractor '{name}' is already registered")
    _EXTRACTOR_REGISTRY[name] = extractor_class


def get_extractor(name: str, pretrained: bool = True, **kwargs) -> BaseExtractor:
    """
    Get an extractor instance by name.

    Args:
        name: Extractor identifier (e.g., "resnet50")
        pretrained: Whether to load pretrained weights
        **kwargs: Additional arguments passed to the extractor's build() method

    Returns:
        Initialized extractor instance

    Raises:
        ValueError: If extractor name is not registered
    """
    if name not in _EXTRACTOR_REGISTRY:
        raise ValueError(
            f"Unknown extractor: '{name}'. Available extractors: {list(_EXTRACTOR_REGISTRY.keys())}"
        )
    extractor_class = _EXTRACTOR_REGISTRY[name]
    return extractor_class.build(pretrained=pretrained, **kwargs)


def get_extractor_transforms(
    name: str,
    mode: str = "eval",
    pretrained: bool = True,
    **kwargs
) -> Callable:
    """
    Get preprocessing transforms for an extractor without loading the full model.

    This is useful when you need the transforms but want to avoid loading
    model weights (e.g., for data preprocessing before training).

    Args:
        name: Extractor identifier (e.g., "resnet50")
        mode: "train" for training with augmentation, "eval" for inference
        pretrained: Whether to use pretrained model configuration
        **kwargs: Additional arguments

    Returns:
        Transform callable for preprocessing images

    Example:
        transform = get_extractor_transforms("resnet50", mode="eval")
        processed_image = transform(pil_image)
    """
    # Build extractor to get its transforms
    # Note: This does load the model, but for most extractors the transforms
    # are defined based on class properties, so this is acceptable.
    # For heavy models, consider caching or using class-level transform methods.
    extractor = get_extractor(name, pretrained=pretrained, **kwargs)
    return extractor.get_transforms(mode=mode)


def list_extractors() -> List[str]:
    """Return list of all registered extractor names."""
    return list(_EXTRACTOR_REGISTRY.keys())


def get_available_extractors() -> List[Dict[str, str]]:
    """Return detailed metadata for all registered extractors."""
    results = []
    for extractor_id in _EXTRACTOR_REGISTRY.keys():
        metadata = _EXTRACTOR_METADATA.get(extractor_id, {
            "name": extractor_id.capitalize(),
            "description": f"Feature extractor: {extractor_id}"
        })
        results.append({
            "id": extractor_id,
            **metadata
        })
    return results

