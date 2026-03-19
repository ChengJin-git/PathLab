"""
Repository Pattern - Data Access Layer

Individual repository modules split for maintainability.
All classes are re-exported here for backward compatibility.
"""

from .data_group import DataGroupRepository
from .dataset import DatasetRepository
from .wsi import WSIRepository
from .ai_task import AITaskRepository
from .ai_result import AIResultRepository
from .chat import ChatRepository
from .feedback import FeedbackRepository
from .export import ExportTaskRepository
from .training import TrainingTaskRepository
from .trained_model import TrainedModelRepository
from .training_log import TrainingLogRepository
from .permissions import DatasetPermissionRepository
from .storage_task import StorageTaskRepository
from .orphaned import OrphanedRecordsRepository
from .annotation import SegmentationAnnotationRepository, VersionConflictError
from .annotation_collaborator import AnnotationCollaboratorRepository
from .annotation_audit import AnnotationAuditLogRepository
from .dataset_stats import DatasetStatsRepository

__all__ = [
    "DataGroupRepository",
    "DatasetRepository",
    "WSIRepository",
    "AITaskRepository",
    "AIResultRepository",
    "ChatRepository",
    "FeedbackRepository",
    "ExportTaskRepository",
    "TrainingTaskRepository",
    "TrainedModelRepository",
    "TrainingLogRepository",
    "DatasetPermissionRepository",
    "StorageTaskRepository",
    "OrphanedRecordsRepository",
    "SegmentationAnnotationRepository",
    "VersionConflictError",
    "AnnotationCollaboratorRepository",
    "AnnotationAuditLogRepository",
    "DatasetStatsRepository",
]
