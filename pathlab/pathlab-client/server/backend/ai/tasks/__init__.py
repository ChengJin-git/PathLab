"""Task-specific trainers and inference modules."""
from .wsi_classification import WSIClassificationTrainer
from .patch_classification import PatchClassificationTrainer
from .patch_segmentation import SegmentationTrainer

__all__ = [
    "WSIClassificationTrainer",
    "PatchClassificationTrainer",
    "SegmentationTrainer",
]

