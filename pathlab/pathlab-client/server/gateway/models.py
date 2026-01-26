"""
Pydantic models for Gateway API requests/responses
"""
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Dict, List



class DatasetRenameRequest(BaseModel):
    """Request model for renaming a dataset"""
    dataset_id: str  # UUID of the dataset to rename
    new_name: str  # New display name


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
    task_name: str
    task_type: str  # "classification" or "survival_prediction"
    data_level: str  # "wsi" or "patch"
    task_description: Optional[str] = None
    wsi_ids: List[str]
    preprocessing: Dict  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model: Dict  # {aggregator, learning_rate, epochs, optimizer, batch_size}
    huggingface_token: Optional[str] = None  # HuggingFace token for gated models
    split_config: Optional[SplitConfig] = None


class UploadByPathRequest(BaseModel):
    """Request model for uploading WSI by file path"""
    wsi_path: str
    dataset_id: Optional[str] = None  # Dataset UUID (existing dataset) or None for new
    dataset_name: Optional[str] = None  # Dataset display name (for creating new dataset)
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


class OrphanedCleanupRequest(BaseModel):
    """Request model for orphaned files cleanup"""
    categories: Optional[List[str]] = None  # If None, clean all categories


class MigrationRequest(BaseModel):
    """Request model for storage migration"""
    target_path: str
    delete_source: bool = False

