"""Registry for feature extractors.

Uses lazy imports so that a broken dependency in one extractor does not
prevent the rest of the system from loading.
"""
from __future__ import annotations

import importlib
import logging
from typing import Dict, Type, List, Callable, Tuple

from .base import BaseExtractor
from .transforms import get_default_transforms

logger = logging.getLogger(__name__)

# Lazy registry: maps extractor id -> (module_path_relative_to_package, class_name)
# The module is only imported when the extractor is actually requested.
_EXTRACTOR_LAZY_REGISTRY: Dict[str, Tuple[str, str]] = {
    "resnet50":       (".resnet50",             "ResNet50Extractor"),
    "vit_l_16":       (".vit_l_16",             "ViTL16Extractor"),
    "conch":          (".conch_model",           "CONCHExtractor"),
    "uni":            (".uni_model",             "UNIExtractor"),
    "uni2":           (".uni2_model",            "UNI2Extractor"),
    "virchow":        (".virchow_model",         "VirchowExtractor"),
    "virchow2":       (".virchow2_model",        "Virchow2Extractor"),
    "plip":           (".plip_model",             "PLIPExtractor"),
    "phikon":         (".phikon_model",           "PhikonExtractor"),
    "phikon2":        (".phikon2_model",          "Phikon2Extractor"),
    "patho_clip":     (".patho_clip_model",       "PathoCLIPExtractor"),
    "openmidnight":   (".openmidnight_model",     "OpenMidnightExtractor"),
    "conch15":        (".conch15_model",          "CONCH15Extractor"),
    "H-Optimus-1":    (".h_optimus_1_model",      "H_Optimus_1Extractor"),
    "H-Optimus-0":    (".h_optimus_0_model",      "H_Optimus_0Extractor"),
    "mSTAR":          (".mSTAR_model",            "mSTARExtractor"),
    "GPFM":           (".gpfm_model",             "GPFMExtractor"),
    "SmartCCS":       (".smartccs_model",          "SmartCCSExtractor"),
    "SmartCyto":      (".smartcyto_model",         "SmartCytoExtractor"),
}

# Cache for already-imported extractor classes
_EXTRACTOR_CLASS_CACHE: Dict[str, Type[BaseExtractor]] = {}

_EXTRACTOR_METADATA: Dict[str, Dict[str, str]] = {
    "resnet50": {"name": "ResNet50", "description": "ImageNet pretrained CNN, 2048-dim, general-purpose baseline"},
    "vit_l_16": {"name": "ViT-Large", "description": "ImageNet pretrained ViT-L/16, 1024-dim, general-purpose baseline"},
    "conch": {"name": "CONCH", "description": "CLIP ViT-B/16, 512-dim (Mahmood Lab)"},
    "uni": {"name": "UNI", "description": "DINOv2 ViT-L/16, 1024-dim (Mahmood Lab)"},
    "uni2": {"name": "UNI2", "description": "ViT-G/14, 1536-dim (Mahmood Lab)"},
    "virchow": {"name": "Virchow", "description": "DINOv2 ViT-H/14, 1280-dim (Paige AI)"},
    "virchow2": {"name": "Virchow2", "description": "DINOv2 ViT-H/14, 1280-dim (Paige AI)"},
    "plip": {"name": "PLIP", "description": "CLIP ViT-B/16, 512-dim (Zou Group)"},
    "phikon": {"name": "Phikon", "description": "iBOT ViT-L/16, 1024-dim (Owkin)"},
    "phikon2": {"name": "Phikon2", "description": "DINOv2 ViT-L/16, 1024-dim (Owkin)"},
    "patho_clip": {"name": "PathoCLIP", "description": "CLIP fine-tuned, 512-dim (Hong Bu Lab)"},
    "openmidnight": {"name": "OpenMidnight", "description": "ViT 1.1B, 1536-dim (SophontAI)"},
    "conch15": {"name": "CONCH 1.5", "description": "CLIP ViT-B/16, 512-dim (Mahmood Lab)"},
    "H-Optimus-1": {"name": "H-Optimus-1", "description": "ViT 1.1B, 1536-dim (Bioptimus)"},
    "H-Optimus-0": {"name": "H-Optimus-0", "description": "ViT 1.1B, 1536-dim (Bioptimus)"},
    "mSTAR": {"name": "mSTAR", "description": "ViT-L/16, 1024-dim (Smartlab)"},
    "GPFM": {"name": "GPFM", "description": "DINOv2 ViT-L/14, 1024-dim (Smartlab)"},
    "SmartCCS": {"name": "Smart-CCS", "description": "DINOv2 ViT-L/14, 1024-dim (Smartlab)"},
    "SmartCyto": {"name": "SmartCyto", "description": "DINOv3 ViT-B/16, 768-dim (Smartlab)"},
}


def _resolve_extractor_class(name: str) -> Type[BaseExtractor]:
    """Lazily import and return the extractor class for the given name."""
    if name in _EXTRACTOR_CLASS_CACHE:
        return _EXTRACTOR_CLASS_CACHE[name]

    if name not in _EXTRACTOR_LAZY_REGISTRY:
        raise ValueError(
            f"Unknown extractor: '{name}'. "
            f"Available extractors: {list(_EXTRACTOR_LAZY_REGISTRY.keys())}"
        )

    module_path, class_name = _EXTRACTOR_LAZY_REGISTRY[name]
    try:
        module = importlib.import_module(module_path, package=__package__)
        cls = getattr(module, class_name)
    except Exception as e:
        logger.error(f"Failed to import extractor '{name}' from {module_path}: {e}")
        raise ImportError(
            f"Could not load extractor '{name}' ({module_path}.{class_name}): {e}"
        ) from e

    _EXTRACTOR_CLASS_CACHE[name] = cls
    return cls


def register_extractor(name: str, extractor_class: Type[BaseExtractor]):
    """
    Register a new feature extractor.

    Args:
        name: Unique identifier for the extractor (e.g., "resnet50", "uni", "conch")
        extractor_class: Class inheriting from BaseExtractor
    """
    if name in _EXTRACTOR_LAZY_REGISTRY or name in _EXTRACTOR_CLASS_CACHE:
        raise ValueError(f"Extractor '{name}' is already registered")
    _EXTRACTOR_CLASS_CACHE[name] = extractor_class


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
    extractor_class = _resolve_extractor_class(name)
    return extractor_class.build(pretrained=pretrained, **kwargs)


def get_extractor_transforms(
    name: str,
    mode: str = "eval",
    pretrained: bool = True,
    **kwargs
) -> Callable:
    """
    Get preprocessing transforms for an extractor without loading the full model.

    Args:
        name: Extractor identifier (e.g., "resnet50")
        mode: "train" for training with augmentation, "eval" for inference
        pretrained: Whether to use pretrained model configuration
        **kwargs: Additional arguments

    Returns:
        Transform callable for preprocessing images
    """
    extractor = get_extractor(name, pretrained=pretrained, **kwargs)
    return extractor.get_transforms(mode=mode)


def list_extractors() -> List[str]:
    """Return list of all registered extractor names."""
    return list(_EXTRACTOR_LAZY_REGISTRY.keys())


def get_available_extractors() -> List[Dict[str, str]]:
    """Return detailed metadata for all registered extractors."""
    results = []
    for extractor_id in _EXTRACTOR_LAZY_REGISTRY.keys():
        metadata = _EXTRACTOR_METADATA.get(extractor_id, {
            "name": extractor_id.capitalize(),
            "description": f"Feature extractor: {extractor_id}"
        })
        results.append({
            "id": extractor_id,
            **metadata
        })
    return results

