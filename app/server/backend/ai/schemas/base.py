"""
Base types and enums for AI Service schemas.
"""
from enum import Enum


class TaskType(str, Enum):
    """AI task types"""
    WSI_CLASSIFICATION = "wsi_classification"
    PATCH_CLASSIFICATION = "patch_classification"
    WSI_SURVIVAL = "wsi_survival"
    PATCH_SEGMENTATION = "patch_segmentation"
    PATCH_DETECTION = "patch_detection"


class DataLevel(str, Enum):
    """Data levels"""
    WSI = "wsi"
    PATCH = "patch"


class TaskStatus(str, Enum):
    """Task statuses"""
    PENDING = "pending"
    QUEUED = "queued"
    PATCHING = "patching"
    RESUMING = "resuming"
    EXTRACTING = "extracting"
    TRAINING = "training"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
