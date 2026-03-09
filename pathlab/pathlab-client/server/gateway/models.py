"""
Pydantic models for Gateway API requests/responses
"""
from enum import Enum
from pydantic import BaseModel, model_validator
from typing import Optional, Dict, List, Any
from backend.ai.segmentors.specs import is_fm_segmentation_backbone



class DatasetRenameRequest(BaseModel):
    """Request model for renaming a dataset"""
    dataset_id: str  # UUID of the dataset to rename
    new_name: str  # New display name


class DatasetUpdateTypeRequest(BaseModel):
    """Request model for updating dataset type (classification/survival/segmentation)"""
    task_type: str  # "classification", "survival", or "segmentation"


class DatasetUpdateDataLevelRequest(BaseModel):
    """Request model for updating dataset aggregation level (case/file)"""
    aggregation_level: str  # "case" or "file"


class DeletionMode(str, Enum):
    """Deletion mode for WSI and training task deletion"""
    STANDARD = "standard"  # Delete main files, keep training features
    COMPLETE = "complete"  # Delete all files including training features


class WSIClassifyRequest(BaseModel):
    """Request model for WSI classification"""
    wsi_id: str
    classes: Optional[List[str]] = None  # Optional: classes for classification (auto-detected if not provided)
    model_id: Optional[str] = None  # Optional: specific model to use
    params: Optional[Dict] = None


class SplitConfig(BaseModel):
    """Configuration for data splitting strategy"""
    strategy: str = "random"  # random, k_fold, manual
    n_splits: int = 5  # for k_fold
    ratios: Dict[str, float] = {"train": 0.7, "val": 0.1, "test": 0.2}
    manual_splits: Optional[Dict[str, str]] = None  # map wsi_id -> split
    seed: int = 42


class TrainingTaskRequest(BaseModel):
    """Request model for creating a training task"""
    task_id: Optional[str] = None  # Client-generated task_id for fire-and-forget submission
    rerun_from_task_id: Optional[str] = None  # Admin rerun only: preserve owner from source task
    task_name: str
    task_type: str  # "classification", "survival", or "segmentation"
    data_type: str  # "wsi" or "patch"
    task_description: Optional[str] = None
    dataset_id: Optional[str] = None  # If provided, wsi_ids are resolved from this dataset on server
    wsi_ids: List[str] = []  # Optional when dataset_id is provided
    preprocessing: Dict  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model: Dict  # {aggregator, learning_rate, epochs, optimizer, batch_size}
    huggingface_token: Optional[str] = None  # HuggingFace token for gated models
    split_config: Optional[SplitConfig] = None

    @model_validator(mode="after")
    def validate_segmentation_mode(self):
        if self.task_type != "segmentation":
            return self

        if self.data_type != "patch":
            raise ValueError("Segmentation tasks must use data_type='patch'.")

        model = self.model or {}
        architecture = str(model.get("architecture") or "").strip()
        backbone = str(model.get("backbone") or "").strip()

        if not architecture or not backbone:
            raise ValueError("Segmentation tasks must provide model.architecture and model.backbone.")

        if "encoder" in model:
            raise ValueError("Segmentation tasks must use model.backbone instead of model.encoder.")

        is_fm_backbone = is_fm_segmentation_backbone(backbone)
        if is_fm_backbone and architecture != "conv_decoder":
            raise ValueError(
                f"Segmentation FM backbone '{backbone}' requires model.architecture='conv_decoder'."
            )

        if architecture == "conv_decoder" and not is_fm_backbone:
            raise ValueError(
                f"Segmentation architecture 'conv_decoder' requires an FM backbone, got '{backbone}'."
            )

        return self


class TrainingTaskUpdateRequest(BaseModel):
    """Request model for updating a training task"""
    task_name: str  # New task name


class UploadByPathRequest(BaseModel):
    """Request model for uploading WSI by file path"""
    wsi_path: str
    dataset_id: Optional[str] = None  # Dataset UUID (existing dataset) or None for new
    dataset_name: Optional[str] = None  # Dataset display name (for creating new dataset)
    aggregation_level: Optional[str] = None  # Aggregation level for new dataset: "case" or "file"
    task_type: Optional[str] = None  # classification | survival | segmentation
    label: Optional[str] = None
    case_id: Optional[str] = None
    wsi_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    source: Optional[str] = None
    # Survival analysis fields
    event_time: Optional[float] = None  # Time to event (days/months)
    event_status: Optional[int] = None  # 1 = event occurred, 0 = censored


class WSIMetadataUpdateRequest(BaseModel):
    """Request model for updating WSI metadata"""
    label: Optional[str] = None
    case_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    source: Optional[str] = None
    # Survival analysis fields
    event_time: Optional[float] = None  # Time to event (days/months)
    event_status: Optional[int] = None  # 1 = event occurred, 0 = censored


class StorageConfigRequest(BaseModel):
    """Request model for updating storage configuration"""
    uploads_dir: str


class ChatRequest(BaseModel):
    """Request model for AI chat

    Supports both text-only and multimodal messages:
    - Text only: {"role": "user", "content": "Hello"}
    - Multimodal: {"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
      ]}
    """
    conversation_id: Optional[str] = None  # Optional conversation ID for persistence
    messages: List[Dict]  # Changed from Dict[str, str] to Dict to support multimodal content


class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation"""
    user_id: Optional[str] = "default_user"
    title: Optional[str] = None


class UpdateMessageRequest(BaseModel):
    """Request model for updating a message's content"""
    content: str


class AddMessageRequest(BaseModel):
    """Request model for adding a message to a conversation"""
    role: str  # "user" or "assistant"
    content: str


class MessageFeedbackRequest(BaseModel):
    """Request model for submitting feedback on a message"""
    feedback_type: Optional[str] = None  # "thumbs_up", "thumbs_down", or None
    task_helpfulness: Optional[str] = None  # "helpful", "not_helpful", or None
    related_task_id: Optional[str] = None  # Task ID for task helpfulness feedback
    time_to_action_seconds: Optional[float] = None  # Time from last user message to task submission
    # Preserved message content (for thumbs up/down feedback)
    message_content: Optional[str] = None  # The rated message content
    context_messages: Optional[List[dict]] = None  # Previous message(s) for context
    # Task info (for task helpfulness feedback)
    task_type: Optional[str] = None  # 'training', 'inference', 'analysis'
    task_title: Optional[str] = None  # Task name/title


class OrphanedCleanupRequest(BaseModel):
    """Request model for orphaned files cleanup"""
    categories: Optional[List[str]] = None  # If None, clean all categories


class MigrationRequest(BaseModel):
    """Request model for storage migration"""
    target_path: str
    delete_source: bool = False


class ScanDirectoryRequest(BaseModel):
    """Request model for scanning a directory for WSI files"""
    directory_path: str


class BatchRegisterFileInfo(BaseModel):
    """File info for batch registration, including associated files for special formats"""
    path: str  # Main file path
    format_type: str = "standard"  # "standard", "mrxs", or "tmap"
    associated_data: Optional[Any] = None  # str for mrxs (data folder), list[str] for tmap (DT files)


class BatchRegisterRequest(BaseModel):
    """Request model for batch registering WSI files"""
    files: List[BatchRegisterFileInfo]  # List of file info objects to register
    dataset_id: Optional[str] = None  # Existing dataset UUID
    dataset_name: Optional[str] = None  # New dataset name (if creating new)
    scan_root: Optional[str] = None  # Directory used during external scan (for segmentation annotation matching)
    task_type: str = "classification"  # "classification", "survival", or "segmentation"
    # Classification fields
    default_label: Optional[str] = None  # Default label for classification files
    # Survival analysis fields (required when task_type is "survival")
    default_event_time: Optional[float] = None  # Time to event
    default_event_status: Optional[int] = None  # 1 = event occurred, 0 = censored


class CheckExternalFilesRequest(BaseModel):
    """Request model for checking external (batch imported) files availability"""
    dataset_id: Optional[str] = None  # If provided, only check files in this dataset


class DeleteUnavailableFilesRequest(BaseModel):
    """Request model for deleting unavailable file records"""
    wsi_ids: List[str]  # List of WSI IDs to delete


class StartBatchImportRequest(BaseModel):
    """Request model for starting a batch import background task"""
    files: List[BatchRegisterFileInfo]  # List of file info objects to register
    dataset_id: Optional[str] = None  # Existing dataset UUID
    dataset_name: Optional[str] = None  # New dataset name (if creating new)
    scan_root: Optional[str] = None  # Directory used during external scan (for segmentation annotation matching)
    aggregation_level: str = "file"  # "case" or "file" - aggregation level
    task_type: str = "classification"  # "classification", "survival", or "segmentation"
    # Classification fields
    default_label: Optional[str] = None  # Default label for classification files
    # Survival analysis fields (required when task_type is "survival")
    default_event_time: Optional[float] = None  # Time to event
    default_event_status: Optional[int] = None  # 1 = event occurred, 0 = censored


class StartDeleteExternalRequest(BaseModel):
    """Request model for starting a delete external files background task"""
    wsi_ids: List[str]  # List of WSI IDs to delete


class StartBatchUpdateMetadataRequest(BaseModel):
    """Request model for starting a batch update metadata background task"""
    wsi_ids: List[str]  # List of WSI IDs to update
    # Metadata fields to update (None means keep existing value)
    label: Optional[str] = None
    case_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    source: Optional[str] = None
    # Survival analysis fields
    event_time: Optional[float] = None
    event_status: Optional[int] = None


# ── Annotation ──────────────────────────────────────────────────────────────

class AnnotationSaveRequest(BaseModel):
    """Request model for creating/updating a segmentation annotation (auto-save)"""
    annotation_id: str
    source_dataset_id: Optional[str] = None
    # { wsi_id: [{ type, x, y, width, height, points, label, color }, ...] }
    annotations: Dict

class AnnotationExtractRequest(BaseModel):
    """Request model for extracting annotated ROIs into a new dataset"""
    annotation_id: Optional[str] = None    # Load annotations from saved annotation
    annotations: Optional[Dict] = None     # Or provide directly (overrides saved)
    dataset_name: str
    task_type: str = "classification"       # classification or segmentation
    source_dataset_id: Optional[str] = None  # For segmentation: reuse existing dataset
    dataset_scope: bool = False             # Build effective annotations from the whole dataset


class AnnotationDeleteByLabelsRequest(BaseModel):
    """Delete annotations by label across an effective dataset annotation view."""
    labels: List[str]
