"""Task kinds shared by API producers and the GPU queue, without runtime imports."""

from enum import Enum


class TaskType(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    EXTERNAL_VALIDATION = "external_validation"
    ANALYSIS = "analysis"
    BATCH_INFERENCE = "batch_inference"
    RESEARCH = "research"
