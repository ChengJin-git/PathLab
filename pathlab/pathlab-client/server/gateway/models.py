"""
Pydantic models for Gateway API requests/responses
"""

from enum import Enum
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, List, Any, Literal
from backend.ai.task_taxonomy import (
    CANONICAL_TASK_IDS,
    get_task_metadata,
    is_canonical_task_type,
    normalize_task_type,
    validate_task_axes,
)
from backend.ai.segmentors.specs import is_fm_segmentation_backbone
from backend.auth.schemas import UserReadAdmin


def _normalize_task_type_for_dataset_axes(
    task_type: str,
    *,
    aggregation_level: Optional[str],
) -> str:
    normalized = task_type.strip().lower()
    if not is_canonical_task_type(normalized):
        raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {normalized}")
    metadata = get_task_metadata(normalized)
    validate_task_axes(
        task_type=normalized,
        data_type=metadata.data_type,
        aggregation_level=aggregation_level or "file",
    )
    return normalized


def _infer_batch_register_data_type(files: List["BatchRegisterFileInfo"]) -> Optional[str]:
    normalized_data_types = {
        file.data_type.strip().lower()
        for file in files
        if isinstance(file.data_type, str) and file.data_type.strip()
    }
    if not normalized_data_types:
        return None
    if len(normalized_data_types) > 1:
        raise ValueError("files contain mixed data_type values")
    inferred = next(iter(normalized_data_types))
    if inferred not in {"wsi", "patch"}:
        raise ValueError("files contain unsupported data_type values")
    return inferred


class DatasetUpdateVisibilityRequest(BaseModel):
    is_public: bool


class DatasetRenameRequest(BaseModel):
    """Request model for renaming a dataset"""

    dataset_id: str  # UUID of the dataset to rename
    new_name: str  # New display name


class DatasetUpdateTypeRequest(BaseModel):
    """Request model for updating dataset type (classification/survival/segmentation)"""

    task_type: str  # "wsi_classification", "wsi_survival", or "patch_segmentation"

    @model_validator(mode="after")
    def normalize_task_type_value(self):
        normalized = self.task_type.strip().lower()
        if not is_canonical_task_type(normalized):
            raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {normalized}")
        self.task_type = normalized
        return self


class DatasetUpdateDataLevelRequest(BaseModel):
    """Request model for updating dataset aggregation level (case/file)"""

    aggregation_level: str  # "case" or "file"


class DatasetUpdateSourceRequest(BaseModel):
    """Request model for updating dataset source organ/tissue."""

    source: Optional[str] = None


class DeletionMode(str, Enum):
    """Deletion mode for WSI and training task deletion"""

    STANDARD = "standard"  # Delete main files, keep training features
    COMPLETE = "complete"  # Delete all files including training features


class WSIClassifyRequest(BaseModel):
    """Request model for WSI classification"""

    wsi_id: str
    classes: Optional[List[str]] = (
        None  # Optional: classes for classification (auto-detected if not provided)
    )
    model_id: Optional[str] = None  # Optional: specific model to use
    params: Optional[Dict[str, Any]] = None


class IndependentInferenceRequest(BaseModel):
    """Request model for inference on selected uploaded, unlabeled images."""

    model_id: str
    wsi_ids: List[str] = Field(min_length=1)
    rerun_from_task_id: Optional[str] = None


class SplitConfig(BaseModel):
    """Configuration for data splitting strategy"""

    strategy: str = "random"  # random, k_fold, manual
    n_splits: int = Field(default=5, ge=2, le=20)  # for k_fold
    ratios: Dict[str, float] = {"train": 0.7, "val": 0.1, "test": 0.2}
    manual_splits: Optional[Dict[str, str]] = None  # map wsi_id -> split
    seed: int = 42
    stratified: bool = True


class TrainingTaskRequest(BaseModel):
    """Request model for creating a training task"""

    task_id: Optional[str] = (
        None  # Client-generated task_id for fire-and-forget submission
    )
    rerun_from_task_id: Optional[str] = (
        None  # Admin rerun only: preserve owner from source task
    )
    task_name: str
    task_type: str  # Canonical task id from CANONICAL_TASK_IDS.
    data_type: str  # "wsi" or "patch"
    task_description: Optional[str] = None
    dataset_id: Optional[str] = (
        None  # If provided, wsi_ids are resolved from this dataset on server
    )
    wsi_ids: List[str] = []  # Optional when dataset_id is provided
    preprocessing: Dict[
        str, Any
    ]  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model: Dict[str, Any]  # {aggregator, learning_rate, epochs, optimizer, batch_size}
    huggingface_token: Optional[str] = None  # HuggingFace token for gated models
    split_config: Optional[SplitConfig] = None

    @model_validator(mode="after")
    def validate_segmentation_mode(self):
        self.task_type = normalize_task_type(
            task_type=self.task_type,
            data_type=self.data_type,
            aggregation_level="file",
        )
        self.data_type = self.data_type.strip().lower()

        if self.task_type != "patch_segmentation":
            return self

        if self.data_type != "patch":
            raise ValueError("Segmentation tasks must use data_type='patch'.")

        model = self.model or {}
        architecture = str(model.get("architecture") or "").strip()
        backbone = str(model.get("backbone") or "").strip()

        if not architecture or not backbone:
            raise ValueError(
                "Segmentation tasks must provide model.architecture and model.backbone."
            )

        if "encoder" in model:
            raise ValueError(
                "Segmentation tasks must use model.backbone instead of model.encoder."
            )

        FM_DECODER_ARCHITECTURES = {
            "linear_decoder",
            "conv_decoder",
            "dpt_decoder",
            "unetr_decoder",
        }

        is_fm_backbone = is_fm_segmentation_backbone(backbone)
        if is_fm_backbone and architecture not in FM_DECODER_ARCHITECTURES:
            raise ValueError(
                f"Segmentation FM backbone '{backbone}' requires model.architecture to be one of "
                f"{sorted(FM_DECODER_ARCHITECTURES)}, got '{architecture}'."
            )

        if architecture in FM_DECODER_ARCHITECTURES and not is_fm_backbone:
            raise ValueError(
                f"Segmentation architecture '{architecture}' requires an FM backbone, got '{backbone}'."
            )

        return self


class TrainingTaskUpdateRequest(BaseModel):
    """Request model for updating a training task"""

    task_name: str  # New task name


class BaseDatasetRequest(BaseModel):
    dataset_id: Optional[str] = None
    dataset_name: Optional[str] = None
    source_organ: Optional[str] = None
    aggregation_level: Optional[str] = None
    task_type: Optional[str] = "wsi_classification"
    is_public: bool = False
    default_label: Optional[str] = None
    default_event_time: Optional[float] = None
    default_event_status: Optional[int] = None

    @model_validator(mode="after")
    def normalize_task_type_value(self):
        task_type = self.task_type or "wsi_classification"
        self.task_type = _normalize_task_type_for_dataset_axes(
            task_type,
            aggregation_level=self.aggregation_level,
        )
        return self


class BaseWSIMetadataFields(BaseModel):
    label: Optional[str] = None
    case_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    event_time: Optional[float] = None
    event_status: Optional[int] = None


class UploadByPathRequest(BaseDatasetRequest):
    wsi_path: str
    wsi_id: Optional[str] = None
    label: Optional[str] = None
    case_id: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    event_time: Optional[float] = None
    event_status: Optional[int] = None


class WSIMetadataUpdateRequest(BaseWSIMetadataFields):
    pass


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

    conversation_id: Optional[str] = None
    messages: List[Dict[str, Any]]
    regenerate_message_id: Optional[int] = None


class CreateConversationRequest(BaseModel):
    """Request model for creating a conversation"""

    user_id: Optional[str] = "default_user"
    title: Optional[str] = None
    source_conversation_id: Optional[str] = None


class UpdateConversationRequest(BaseModel):
    """Request model for updating a conversation's title"""

    title: str


class UpdateMessageRequest(BaseModel):
    """Request model for updating a message's content"""

    content: str
    metadata: Optional[Dict[str, Any]] = None


class AddMessageRequest(BaseModel):
    """Request model for adding a message to a conversation"""

    role: str  # "user" or "assistant"
    content: str


class ChatPatchInferenceRequest(BaseModel):
    """Request model for temporary chat-only patch inference."""

    conversation_id: str
    message_id: int
    inference_type: Literal["classification", "segmentation"]
    model_id: str
    image_data_url: str
    source: Optional[str] = None


class ChatPatchInferenceExitRequest(BaseModel):
    """Request model for cancelling chat image inference during page exit/logout."""

    conversation_id: str
    message_id: int
    cancel_message: str = Field(min_length=1, max_length=4000)


class MessageFeedbackRequest(BaseModel):
    """Request model for submitting feedback on a message"""

    feedback_type: Optional[str] = None  # "thumbs_up", "thumbs_down", or None
    task_helpfulness: Optional[str] = None  # "helpful", "not_helpful", or None
    related_task_id: Optional[str] = None  # Task ID for task helpfulness feedback
    time_to_action_seconds: Optional[float] = (
        None  # Time from last user message to task submission
    )
    # Preserved message content (for thumbs up/down feedback)
    message_content: Optional[str] = None  # The rated message content
    context_messages: Optional[List[dict[str, Any]]] = (
        None  # Previous message(s) for context
    )
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
    scan_id: Optional[str] = None
    task_type: Optional[str] = None
    page: int = 1
    page_size: int = 100


class StartScanDirectoryTaskRequest(BaseModel):
    """Request model for starting an asynchronous directory scan"""

    directory_path: str
    task_type: Optional[str] = None
    page_size: int = 100


class BatchRegisterFileInfo(BaseModel):
    """File info for batch registration, including associated files for special formats"""

    path: str  # Main file path
    format_type: str = "standard"  # "standard", "mrxs", or "tmap"
    associated_data: Optional[Any] = (
        None  # str for mrxs (data folder), list[str] for tmap (DT files)
    )
    data_type: Optional[str] = None  # Cached scan classification when available


class BatchRegisterRequest(BaseModel):
    """Request model for batch registering WSI files"""

    files: List[BatchRegisterFileInfo]  # List of file info objects to register
    dataset_id: Optional[str] = None  # Existing dataset UUID
    dataset_name: Optional[str] = None  # New dataset name (if creating new)
    source_organ: Optional[str] = None  # Source organ/tissue for new dataset
    scan_root: Optional[str] = (
        None  # Directory used during external scan (for segmentation annotation matching)
    )
    task_type: str = "wsi_classification"  # Canonical task id from CANONICAL_TASK_IDS.
    is_public: bool = False
    # Classification fields
    default_label: Optional[str] = None  # Default label for classification files
    # Survival analysis fields (required when task_type is "survival")
    default_event_time: Optional[float] = None  # Time to event
    default_event_status: Optional[int] = None  # 1 = event occurred, 0 = censored

    @model_validator(mode="after")
    def normalize_task_type_value(self):
        inferred_data_type = _infer_batch_register_data_type(self.files)
        if inferred_data_type is not None:
            self.task_type = normalize_task_type(
                task_type=self.task_type,
                data_type=inferred_data_type,
                aggregation_level="file",
            )
            return self
        normalized = self.task_type.strip().lower()
        if not is_canonical_task_type(normalized):
            raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {normalized}")
        self.task_type = normalized
        return self


class CheckExternalFilesRequest(BaseModel):
    """Request model for checking external (batch imported) files availability"""

    dataset_id: Optional[str] = None  # If provided, only check files in this dataset


class DeleteUnavailableFilesRequest(BaseModel):
    """Request model for deleting unavailable file records"""

    wsi_ids: List[str]  # List of WSI IDs to delete


class StartBatchImportRequest(BaseDatasetRequest):
    files: Optional[List[BatchRegisterFileInfo]] = None
    scan_root: Optional[str] = None
    scan_id: Optional[str] = None
    select_all_valid: bool = False
    selected_paths: List[str] = Field(default_factory=list)
    excluded_paths: List[str] = Field(default_factory=list)
    aggregation_level: Optional[str] = "file"
    task_type: Optional[str] = "wsi_classification"

    @model_validator(mode="after")
    def normalize_task_type_value(self):
        task_type = self.task_type or "wsi_classification"
        aggregation_level = self.aggregation_level or "file"

        inferred_data_type = _infer_batch_register_data_type(self.files or [])
        if inferred_data_type is not None:
            self.task_type = normalize_task_type(
                task_type=task_type,
                data_type=inferred_data_type,
                aggregation_level=aggregation_level,
            )
            return self
        self.task_type = _normalize_task_type_for_dataset_axes(
            task_type,
            aggregation_level=aggregation_level,
        )
        self.aggregation_level = aggregation_level
        return self


class StartDeleteExternalRequest(BaseModel):
    """Request model for starting a delete external files background task"""

    wsi_ids: List[str]  # List of WSI IDs to delete


class StartDeleteWSIsRequest(BaseModel):
    """Request model for starting owner-safe WSI batch deletion."""

    wsi_ids: List[str] = Field(min_length=1)
    mode: DeletionMode = DeletionMode.STANDARD


class StartDeleteDatasetRequest(BaseModel):
    """Request model for starting a dataset deletion background task."""

    dataset_id: str
    mode: DeletionMode = DeletionMode.STANDARD


class StartBatchUpdateMetadataRequest(BaseWSIMetadataFields):
    wsi_ids: List[str]


# ── Annotation ──────────────────────────────────────────────────────────────


class AnnotationSaveRequest(BaseModel):
    """Request model for creating/updating a personal segmentation annotation."""

    annotation_id: str
    source_dataset_id: Optional[str] = None
    # { wsi_id: [{ type, x, y, width, height, points, label, color }, ...] }
    annotations: Dict[str, Any]


class AnnotationExtractRequest(BaseModel):
    annotation_id: Optional[str] = None
    annotations: Optional[Dict[str, Any]] = None
    dataset_name: str
    task_type: str = "patch_segmentation"
    source_dataset_id: Optional[str] = None
    dataset_scope: bool = False
    source_organ: Optional[str] = None
    annotation_mode: Literal["personal", "shared"] = "personal"

    @model_validator(mode="after")
    def normalize_task_type_value(self):
        normalized = self.task_type.strip().lower()
        if not is_canonical_task_type(normalized):
            raise ValueError(f"task_type must be one of {CANONICAL_TASK_IDS}, got: {normalized}")
        if not normalized.startswith("patch_"):
            raise ValueError("Annotation extraction creates patch datasets; task_type must be patch_classification or patch_segmentation")
        self.task_type = normalized
        return self


class AnnotationDeleteByLabelsRequest(BaseModel):
    labels: List[str]


class SharedAnnotationSaveRequest(BaseModel):
    annotations: Dict[str, Any]
    version: int


class SharedAnnotationFinalizeRequest(BaseModel):
    force: bool = False


class BulkDeleteRegionsByCreatorRequest(BaseModel):
    user_id: str


class AddCollaboratorRequest(BaseModel):
    user_id: str


class PublicSettingsResponse(BaseModel):
    captcha_provider: Optional[str] = None
    captcha_site_key: str = ""


class GlobalSettingsResponse(BaseModel):
    openrouter_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    huggingface_token: str
    dashscope_api_key: str
    exa_api_key: str
    local_vllm_enabled: bool
    local_vllm_base_url: str
    local_vllm_model: str
    local_vllm_api_key: str
    local_asr_enabled: bool
    local_asr_base_url: str
    local_asr_model: str
    local_asr_api_key: str
    turnstile_enabled: bool
    turnstile_site_key: str
    turnstile_secret_key: str
    tencent_captcha_enabled: bool
    tencent_captcha_app_id: str
    tencent_captcha_secret_key: str
    resend_enabled: bool
    resend_api_key: str
    admin_notify_email: str
    email_templates: dict


class GlobalSettingsUpdateRequest(BaseModel):
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: Optional[str] = None
    openrouter_model: Optional[str] = None
    huggingface_token: Optional[str] = None
    dashscope_api_key: Optional[str] = None
    exa_api_key: Optional[str] = None
    local_vllm_enabled: Optional[bool] = None
    local_vllm_base_url: Optional[str] = None
    local_vllm_model: Optional[str] = None
    local_vllm_api_key: Optional[str] = None
    local_asr_enabled: Optional[bool] = None
    local_asr_base_url: Optional[str] = None
    local_asr_model: Optional[str] = None
    local_asr_api_key: Optional[str] = None
    turnstile_enabled: Optional[bool] = None
    turnstile_site_key: Optional[str] = None
    turnstile_secret_key: Optional[str] = None
    tencent_captcha_enabled: Optional[bool] = None
    tencent_captcha_app_id: Optional[str] = None
    tencent_captcha_secret_key: Optional[str] = None
    resend_enabled: Optional[bool] = None
    resend_api_key: Optional[str] = None
    admin_notify_email: Optional[str] = None
    email_templates: Optional[dict] = None


class VllmCheckRequest(BaseModel):
    base_url: str
    api_key: Optional[str] = None


class VllmCheckResponse(BaseModel):
    online: bool
    model: Optional[str] = None
    error: Optional[str] = None


class AsrCheckRequest(BaseModel):
    base_url: str
    model: Optional[str] = None
    api_key: Optional[str] = None


class AsrCheckResponse(BaseModel):
    online: bool
    model: Optional[str] = None
    error: Optional[str] = None


class QueueConfigRequest(BaseModel):
    max_concurrent: Optional[int] = Field(
        None, ge=1, le=10, description="Maximum concurrent GPU tasks (1-10)"
    )
    task_timeout: Optional[int] = Field(
        None, ge=60, le=259200, description="Task timeout in seconds (60-259200)"
    )


class GPUInfo(BaseModel):
    index: int
    name: str
    total_mb: float
    allocated_mb: float
    free_mb: float
    utilization_percent: float
    is_optimal: bool = False
    is_healthy: bool = True


class GPUStatusResponse(BaseModel):
    available: bool
    error: Optional[str] = None
    gpu_count: int = 0
    bad_gpu_count: int = 0
    gpus: List[GPUInfo] = []
    optimal_device: Optional[str] = None
    optimal_device_index: Optional[int] = None
    cuda_version: Optional[str] = None


class BatchGrantDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)
    expires_in_hours: Optional[int] = None
    can_read: Optional[bool] = True
    can_collaborate: Optional[bool] = False
    can_use_gpu: Optional[bool] = False


class BatchRevokeDatasetGrantRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)


class ModelUpdateRequest(BaseModel):
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class AccessRequest(BaseModel):
    username: str = Field(description="Desired login username")
    password: str = Field(description="Account password")
    registration_email: str = Field(
        description="Educational email for identity verification"
    )
    nickname: Optional[str] = Field(default=None, description="Display name")
    turnstile_token: Optional[str] = Field(
        default=None, description="Cloudflare Turnstile token"
    )
    tencent_captcha_token: Optional[str] = Field(
        default=None, description="Tencent Captcha ticket"
    )
    tencent_captcha_randstr: Optional[str] = Field(
        default=None, description="Tencent Captcha randstr"
    )


class SecureLoginRequest(BaseModel):
    username: str
    hashed_password: str
    timestamp: int
    turnstile_token: Optional[str] = None
    tencent_captcha_token: Optional[str] = None
    tencent_captcha_randstr: Optional[str] = None


class PaginatedUserListResponse(BaseModel):
    items: List[UserReadAdmin]
    total: int
    page: int
    page_size: int


class AcceptAgreementRequest(BaseModel):
    ip: Optional[str] = Field(
        default=None, description="Client IP address when accepting the agreement"
    )


class BatchUserIdsRequest(BaseModel):
    user_ids: List[str]


class MaintenanceModeRequest(BaseModel):
    enabled: bool


class MaintenanceNoticeRequest(BaseModel):
    message: Optional[str] = Field(
        default=None, description="Notice message. Empty or null to clear."
    )


class ChangePasswordRequest(BaseModel):
    current_password_sha256: str
    new_password_sha256: str


class AnalysisRequest(BaseModel):
    metrics: List[str] = [
        "accuracy",
        "precision",
        "recall",
        "specificity",
        "f1",
        "auc",
        "weighted_kappa",
    ]
    charts: List[str] = ["roc_curve", "confusion_matrix", "loss_curve"]
    description: Optional[str] = None
    bootstrap_ci_metrics: List[str] = []
    compute_bootstrap_ci: bool = False


class ExternalValidationRequest(BaseModel):
    model_id: str
    dataset_id: str
    rerun_from_task_id: Optional[str] = None
    metrics: Optional[List[str]] = None
    charts: Optional[List[str]] = None
    compute_bootstrap_ci: Optional[bool] = False


class BatchInferenceRequest(BaseModel):
    model_task_id: str
    model_id: Optional[str] = None
    dataset_id: str
    rerun_from_task_id: Optional[str] = None


class QuickAnalysisRequest(BaseModel):
    metrics: Optional[List[str]] = None
    charts: Optional[List[str]] = None
    run_if_missing: bool = True
