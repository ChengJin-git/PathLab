"""
Pydantic models for Gateway API requests/responses
"""
from pydantic import BaseModel
from typing import Optional, Dict, List


class WSIClassifyRequest(BaseModel):
    """Request model for WSI classification"""
    wsi_id: str
    classes: Optional[List[str]] = None  # Optional: classes for classification (auto-detected if not provided)
    model_id: Optional[str] = None  # Optional: specific model to use
    params: Optional[Dict] = None


class TrainingTaskRequest(BaseModel):
    """Request model for creating a training task"""
    task_name: str
    task_type: str  # "classification" or "segmentation"
    data_level: str  # "wsi" or "patch"
    task_description: Optional[str] = None
    wsi_ids: List[str]
    preprocessing: Dict  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model: Dict  # {aggregator, learning_rate, epochs, optimizer, batch_size}


class UploadByPathRequest(BaseModel):
    """Request model for uploading WSI by file path"""
    wsi_path: str
    label: Optional[str] = None
    case_id: Optional[str] = None
    wsi_id: Optional[str] = None


class ChatRequest(BaseModel):
    """Request model for AI chat"""
    conversation_id: Optional[str] = None  # Optional conversation ID for persistence
    messages: List[Dict[str, str]]


class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation"""
    user_id: Optional[str] = "default_user"
    title: Optional[str] = None


class ParseTaskRequest(BaseModel):
    """Request model for task parsing"""
    description: str


class OrphanedCleanupRequest(BaseModel):
    """Request model for orphaned files cleanup"""
    categories: Optional[List[str]] = None  # If None, clean all categories

