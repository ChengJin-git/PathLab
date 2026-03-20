"""
SQLAlchemy Database Models

Following industry best practices from Cytomine and DSA platforms.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    Boolean,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from backend.database.utils.json_utils import sanitize_for_json

Base = declarative_base()


def utc_now() -> datetime:
    """Get current UTC time as naive datetime (UTC assumed).

    Returns timezone-naive datetime in UTC, compatible with PostgreSQL
    TIMESTAMP WITHOUT TIME ZONE columns via asyncpg.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DataGroup(Base):
    """
    DataGroup table.
    Defines valid combinations of data_type, aggregation_level, and task_type.
    Global table (not user-specific) - users create groups on demand, others reuse.

    Examples:
    - WSI + file-level + classification
    - WSI + case-level + classification
    - WSI + case-level + survival
    - Patch + file-level + classification
    """

    __tablename__ = "data_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        String(255), unique=True, nullable=False, index=True
    )  # UUID for API
    name = Column(
        String(255), nullable=False
    )  # Display name (e.g., "WSI Case-level Classification")
    description = Column(Text)  # Optional description

    # Core attributes that define the group
    data_type = Column(String(20), nullable=False)  # 'wsi' | 'patch'
    aggregation_level = Column(String(20), nullable=False)  # 'file' | 'case'
    task_type = Column(
        String(50), nullable=False
    )  # 'classification' | 'survival' | ... (extensible)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    datasets = relationship(
        "Dataset", back_populates="data_group", cascade="all, delete-orphan"
    )
    training_tasks = relationship(
        "TrainingTask", back_populates="data_group", cascade="all, delete-orphan"
    )

    # Unique constraint: only one group per combination
    __table_args__ = (
        Index(
            "idx_data_group_unique",
            "data_type",
            "aggregation_level",
            "task_type",
            unique=True,
        ),
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "data_type": self.data_type,
            "aggregation_level": self.aggregation_level,
            "task_type": self.task_type,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class Dataset(Base):
    """
    Dataset table.
    Stores dataset metadata with UUID for privacy (no plaintext names in API).
    """

    __tablename__ = "datasets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(
        String(255), unique=True, nullable=False, index=True
    )  # UUID for API
    name = Column(
        String(255), nullable=False
    )  # Display name (stored only, never sent in URL/params)
    description = Column(Text)  # Optional description

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Reference to DataGroup - defines data_type, aggregation_level, task_type
    group_id = Column(
        String(255), ForeignKey("data_groups.group_id"), nullable=False, index=True
    )

    source_organ = Column(String(100), nullable=True)

    # Visibility: True = all authenticated users can see/access this dataset
    #             False (default) = only owner + explicitly authorized users
    is_public = Column(Boolean, default=False, nullable=False, server_default="false")

    # Open collaboration: True = any authenticated user can write shared annotations
    # Only meaningful when is_public=True
    is_open_collaboration = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    parent_dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    data_group = relationship("DataGroup", back_populates="datasets")
    wsi_slides = relationship(
        "WSISlide", back_populates="dataset", cascade="all, delete-orphan"
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "user_id": self.user_id,
            "group_id": self.group_id,
            "source_organ": self.source_organ,
            "is_public": self.is_public,
            "is_open_collaboration": self.is_open_collaboration,
            "data_type": self.data_group.data_type if self.data_group else None,
            "aggregation_level": self.data_group.aggregation_level
            if self.data_group
            else None,
            "task_type": self.data_group.task_type if self.data_group else None,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class WSISlide(Base):
    """
    WSI Slide metadata table.
    Stores metadata for whole slide images.
    """

    __tablename__ = "wsi_slides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wsi_id = Column(String(255), unique=True, nullable=False, index=True)
    original_filename = Column(
        String(500)
    )  # Original filename for internal reference (not exposed to frontend)
    dataset_id = Column(
        String(255), ForeignKey("datasets.dataset_id"), index=True
    )  # FK to datasets table (UUID)
    case_id = Column(String(255), index=True)
    label = Column(String(100), index=True)
    wsi_path = Column(Text, nullable=False)

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Parent WSI - self-referential FK for ROI-extracted images
    parent_wsi_id = Column(
        String(255), ForeignKey("wsi_slides.wsi_id"), nullable=True, index=True
    )

    # Patient metadata
    age = Column(Integer)  # Patient age
    gender = Column(String(20))  # Patient gender (e.g., Male, Female, Other)
    source = Column(String(100))  # Organ/tissue source (e.g., Cervix, Lung, Breast)
    split = Column(String(20), nullable=True)  # train, val, test

    # Survival analysis fields
    event_time = Column(
        Float
    )  # Time to event (days/months), used for survival prediction
    event_status = Column(Integer)  # Event status: 1 = event occurred, 0 = censored

    # WSI properties
    mpp = Column(Float)  # Microns per pixel
    vendor = Column(String(100))
    width = Column(Integer)
    height = Column(Integer)
    magnification = Column(Integer)
    file_size = Column(BigInteger)  # File size in bytes (BigInteger for files > 2GB)

    # Associated files for special formats (MRXS, TMAP)
    # JSON format: {"format_type": "mrxs"|"tmap"|"standard", "data_folder": str, "dt_files": [str]}
    associated_files = Column(JSON, nullable=True)

    # Feature extraction status
    feature_extracted = Column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )

    # Denormalized file type hint – set at upload time for fast index filtering.
    # Eliminates per-query lower(wsi_path) LIKE scans on every paginated list.
    # Values: 'wsi' | 'patch' | NULL (legacy rows; backfilled at startup via init_db)
    data_type = Column(String(20), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    dataset = relationship("Dataset", back_populates="wsi_slides")
    ai_tasks = relationship(
        "AITask", back_populates="wsi_slide", cascade="all, delete-orphan"
    )
    ai_results = relationship(
        "AIResult", back_populates="wsi_slide", cascade="all, delete-orphan"
    )
    training_task_associations = relationship(
        "TrainingTaskWSI", back_populates="wsi_slide", cascade="all, delete-orphan"
    )
    # Self-referential relationship for ROI extraction origin
    parent_wsi = relationship(
        "WSISlide", remote_side=[wsi_id], foreign_keys=[parent_wsi_id]
    )

    __table_args__ = (
        Index("idx_wsi_user_dataset", "user_id", "dataset_id"),
        Index("idx_wsi_dataset_created", "dataset_id", "created_at"),
        Index("idx_wsi_user_type", "user_id", "data_type"),
        Index("idx_wsi_dataset_type", "dataset_id", "data_type"),
    )

    def _get_file_extension(self) -> str:
        """Extract file extension from wsi_path or original_filename."""
        import os

        if self.original_filename:
            return os.path.splitext(self.original_filename)[1].lower()
        if self.wsi_path:
            return os.path.splitext(self.wsi_path)[1].lower()
        return ""

    def to_dict(self):
        """Convert to dictionary for API responses.

        Note: wsi_path is NOT included to avoid exposing server filesystem paths.
        Use file_extension for file type determination on the frontend.
        """
        return {
            "wsi_id": self.wsi_id,
            "original_filename": self.original_filename,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset.name if self.dataset else None,
            "case_id": self.case_id,
            "label": self.label,
            "file_extension": self._get_file_extension(),
            "user_id": self.user_id,
            "age": self.age,
            "gender": self.gender,
            "source": self.source,
            "event_time": self.event_time,
            "event_status": self.event_status,
            "split": self.split,
            "mpp": self.mpp,
            "vendor": self.vendor,
            "width": self.width,
            "height": self.height,
            "magnification": self.magnification,
            "file_size": self.file_size,
            "associated_files": self.associated_files,
            "parent_wsi_id": self.parent_wsi_id,
            "parent_wsi_name": self.parent_wsi.original_filename
            if self.parent_wsi
            else None,
            "parent_dataset_name": (
                self.parent_wsi.dataset.name
                if self.parent_wsi and self.parent_wsi.dataset
                else None
            ),
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }

    def to_summary_dict(self):
        """Lightweight dict for list/pagination API responses.

        Excludes heavy or detail-only fields: user_id, mpp, vendor, width,
        height, magnification, associated_files, updated_at.
        """
        return {
            "wsi_id": self.wsi_id,
            "original_filename": self.original_filename,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset.name if self.dataset else None,
            "case_id": self.case_id,
            "label": self.label,
            "file_extension": self._get_file_extension(),
            "age": self.age,
            "gender": self.gender,
            "source": self.source,
            "event_time": self.event_time,
            "event_status": self.event_status,
            "split": self.split,
            "file_size": self.file_size,
            "parent_wsi_id": self.parent_wsi_id,
            "parent_wsi_name": self.parent_wsi.original_filename
            if self.parent_wsi
            else None,
            "parent_dataset_name": (
                self.parent_wsi.dataset.name
                if self.parent_wsi and self.parent_wsi.dataset
                else None
            ),
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class AITask(Base):
    """
    AI Task table.
    Stores AI analysis task records and status.
    """

    __tablename__ = "ai_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    wsi_id = Column(
        String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True
    )
    task_type = Column(String(50), nullable=False)  # e.g., "wsi_classification"
    status = Column(
        String(20), nullable=False, index=True
    )  # pending, running, completed, failed
    progress = Column(Integer, default=0)  # 0-100

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Task parameters (JSON)
    params = Column(JSON)

    # Error message if failed
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    # Relationships
    wsi_slide = relationship("WSISlide", back_populates="ai_tasks")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "task_id": self.task_id,
            "wsi_id": self.wsi_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "user_id": self.user_id,
            "params": self.params,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "started_at": self.started_at.isoformat() + "Z"
            if self.started_at
            else None,
            "finished_at": self.finished_at.isoformat() + "Z"
            if self.finished_at
            else None,
        }


class AIResult(Base):
    """
    AI Result table.
    Stores AI analysis results metadata (predictions, probabilities).
    Large data (attention weights) is stored in files.
    """

    __tablename__ = "ai_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wsi_id = Column(
        String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True
    )
    # NOTE: No ForeignKey constraint - task_id can reference either ai_tasks.task_id
    # (for inference tasks) or training_tasks.task_id (for training tasks).
    task_id = Column(String(255), index=True)

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Prediction results
    pred = Column(String(100))  # Predicted label
    probs = Column(JSON)  # Probability distribution {"HSIL": 0.85, "LSIL": 0.12, ...}

    # Additional metadata (file paths, model info, etc.)
    extra_metadata = Column(
        JSON
    )  # {"attention_path": "ai_results/wsi_001/task_123_attention.npy", ...}

    # Timestamp
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    wsi_slide = relationship("WSISlide", back_populates="ai_results")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "wsi_id": self.wsi_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "pred": self.pred,
            "probs": self.probs,
            "metadata": self.extra_metadata,  # Map back to 'metadata' for API compatibility
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class ChatConversation(Base):
    """
    Chat Conversation table.
    Stores conversation sessions with AI assistant.
    """

    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(String(255), index=True)  # For future multi-user support
    title = Column(String(500))  # Auto-generated from first message

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships (order_by ensures messages are always returned in chronological order)
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        # Avoid lazy loading of messages - only include count if already loaded
        from sqlalchemy import inspect

        insp = inspect(self)
        message_count = (
            len(self.messages) if "messages" in insp.dict and self.messages else 0
        )

        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
            "message_count": message_count,
        }


class ChatMessage(Base):
    """
    Chat Message table.
    Stores individual messages in conversations.
    """

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(255),
        ForeignKey("chat_conversations.conversation_id"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)

    # Optional metadata (e.g., model used, tokens, etc.)
    # Renamed from 'metadata' to avoid SQLAlchemy reserved word
    extra_metadata = Column(JSON)

    # Timestamp
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    conversation = relationship("ChatConversation", back_populates="messages")

    # Index for efficient querying
    __table_args__ = (
        Index("idx_conversation_created", "conversation_id", "created_at"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.extra_metadata,  # Map back to 'metadata' for API compatibility
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class MessageFeedback(Base):
    """
    Message Feedback table.
    Stores user feedback for chat messages (thumbs up/down) and task helpfulness ratings.
    Preserves original message content and task info even if conversation is deleted.
    """

    __tablename__ = "message_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(255), nullable=False, index=True)

    # Feedback type: 'thumbs_up', 'thumbs_down', or None for task helpfulness only
    feedback_type = Column(String(20), nullable=True)

    # Task helpfulness: 'helpful', 'not_helpful', or None for message rating only
    task_helpfulness = Column(String(20), nullable=True)

    # Optional: related task ID for task helpfulness feedback
    related_task_id = Column(String(255), nullable=True, index=True)

    # Time from last user message to task submission (in seconds)
    time_to_action_seconds = Column(Float, nullable=True)

    # Preserved message content (for thumbs up/down feedback)
    # Stores the message that was rated + previous message for context
    message_content = Column(Text, nullable=True)  # The rated message content
    context_messages = Column(JSON, nullable=True)  # Previous message(s) for context

    # Task info (for task helpfulness feedback)
    task_type = Column(String(50), nullable=True)  # 'training', 'inference', 'analysis'
    task_title = Column(String(500), nullable=True)  # Task name/title

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    message = relationship("ChatMessage", backref="feedbacks")

    # Unique constraint: one feedback per user per message
    __table_args__ = (
        Index("idx_feedback_message_user", "message_id", "user_id", unique=True),
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "message_id": self.message_id,
            "user_id": self.user_id,
            "feedback_type": self.feedback_type,
            "task_helpfulness": self.task_helpfulness,
            "related_task_id": self.related_task_id,
            "time_to_action_seconds": self.time_to_action_seconds,
            "message_content": self.message_content,
            "context_messages": self.context_messages,
            "task_type": self.task_type,
            "task_title": self.task_title,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class ExportTask(Base):
    """
    Export Task table.
    Tracks async export jobs for large data exports.
    """

    __tablename__ = "export_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)

    # Export type: 'feedbacks', 'training_data', etc.
    export_type = Column(String(50), nullable=False)

    # Status: 'pending', 'processing', 'completed', 'failed'
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text, nullable=True)

    # File info
    file_path = Column(String(1000), nullable=True)  # Path to generated file
    file_format = Column(String(20), nullable=True)  # 'json', 'csv'
    total_records = Column(Integer, nullable=True)

    # Filter parameters (stored as JSON)
    filter_params = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "export_type": self.export_type,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "file_format": self.file_format,
            "total_records": self.total_records,
            "filter_params": self.filter_params,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "started_at": self.started_at.isoformat() + "Z"
            if self.started_at
            else None,
            "completed_at": self.completed_at.isoformat() + "Z"
            if self.completed_at
            else None,
        }


class TrainingTask(Base):
    """
    Training Task table.
    Stores training task configuration and status for no-code training platform.
    """

    __tablename__ = "training_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    task_name = Column(String(500), nullable=False)
    task_description = Column(Text)

    # Reference to DataGroup - defines data_type, aggregation_level, task_type
    group_id = Column(
        String(255), ForeignKey("data_groups.group_id"), nullable=False, index=True
    )

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Status tracking
    status = Column(
        String(20), nullable=False, index=True
    )  # pending, running, completed, failed, cancelled
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text)

    # Training configuration (JSON)
    preprocessing_config = Column(
        JSON
    )  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model_config = Column(
        JSON
    )  # {aggregator, learning_rate, epochs, optimizer, batch_size}

    # Classes extracted from training data labels
    classes = Column(JSON)  # ["HSIL", "LSIL", "Normal", ...]

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    # Relationships
    data_group = relationship("DataGroup", back_populates="training_tasks")
    wsi_associations = relationship(
        "TrainingTaskWSI", back_populates="training_task", cascade="all, delete-orphan"
    )
    trained_models = relationship(
        "TrainedModel", back_populates="training_task", cascade="all, delete-orphan"
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_description": self.task_description,
            "group_id": self.group_id,
            # Include denormalized group info for convenience
            "data_type": self.data_group.data_type if self.data_group else None,
            "aggregation_level": self.data_group.aggregation_level
            if self.data_group
            else None,
            "task_type": self.data_group.task_type if self.data_group else None,
            "user_id": self.user_id,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "preprocessing_config": self.preprocessing_config,
            "model_config": self.model_config,
            "classes": self.classes,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
            "started_at": self.started_at.isoformat() + "Z"
            if self.started_at
            else None,
            "finished_at": self.finished_at.isoformat() + "Z"
            if self.finished_at
            else None,
        }


class TrainingTaskWSI(Base):
    """
    Training Task WSI Association table.
    Many-to-many relationship between training tasks and WSI slides.
    """

    __tablename__ = "training_task_wsi"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True
    )
    wsi_id = Column(
        String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True
    )

    # Split assignment (train/val/test)
    split = Column(String(20))  # "train", "val", "test"

    # Timestamp
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    training_task = relationship("TrainingTask", back_populates="wsi_associations")
    wsi_slide = relationship("WSISlide", back_populates="training_task_associations")

    # Unique constraint: one WSI can only be in one split per task
    __table_args__ = (Index("idx_task_wsi", "task_id", "wsi_id", unique=True),)


class TrainedModel(Base):
    """
    Trained Model table.
    Stores information about trained models from training tasks.
    """

    __tablename__ = "trained_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(255), unique=True, nullable=False, index=True)
    task_id = Column(
        String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True
    )
    model_name = Column(String(500), nullable=False)

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    # Model files
    model_path = Column(Text, nullable=False)  # Path to model weights (.pth)
    config_path = Column(Text)  # Path to model config file

    # Model metadata
    classes = Column(JSON, nullable=False)  # Classes this model can predict
    feature_extractor = Column(String(100))  # Feature extractor used
    aggregator = Column(String(100))  # Aggregator architecture

    # Training metrics
    train_metrics = Column(JSON)  # {accuracy, loss, auc, ...}
    val_metrics = Column(JSON)  # Validation metrics

    # Management fields
    is_default = Column(
        Boolean, default=False, nullable=False
    )  # Whether this is the default model for inference
    is_active = Column(
        Boolean, default=True, nullable=False
    )  # Whether this model is available for use

    # Timestamp
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    training_task = relationship("TrainingTask", back_populates="trained_models")

    def to_dict(self):
        """Convert to dictionary for API responses.

        Note: train_metrics and val_metrics are sanitized to ensure JSON compatibility,
        handling any nan/inf values that may be present in training loss history.
        """
        return {
            "model_id": self.model_id,
            "task_id": self.task_id,
            "model_name": self.model_name,
            "user_id": self.user_id,
            "model_path": self.model_path,
            "config_path": self.config_path,
            "classes": self.classes,
            "feature_extractor": self.feature_extractor,
            "aggregator": self.aggregator,
            # Sanitize metrics for JSON safety (handles nan/inf in loss history)
            "train_metrics": sanitize_for_json(self.train_metrics)
            if self.train_metrics
            else None,
            "val_metrics": sanitize_for_json(self.val_metrics)
            if self.val_metrics
            else None,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class TrainingLog(Base):
    """
    Training Log table.
    Stores log entries for training tasks with support for real-time streaming.

    Design considerations:
    - Indexed by task_id and timestamp for efficient querying
    - Log level for filtering (INFO, WARNING, ERROR, DEBUG)
    - Sequence number for ordering within same timestamp
    - Supports both real-time streaming and historical查询
    """

    __tablename__ = "training_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(
        String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True
    )

    # Log metadata
    level = Column(
        String(20), nullable=False, index=True
    )  # INFO, WARNING, ERROR, DEBUG
    message = Column(Text, nullable=False)
    sequence = Column(
        Integer, nullable=False
    )  # Sequence number within task for ordering

    # Optional structured data (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    extra_data = Column(JSON)  # {progress, epoch, batch, loss, etc.}

    # Timestamp
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    # Composite index for efficient querying
    __table_args__ = (Index("idx_task_logs", "task_id", "created_at", "sequence"),)

    def to_dict(self):
        """Convert to dictionary for API responses.

        Note: extra_data is sanitized to ensure JSON compatibility,
        handling any nan/inf values that may have been stored in historical data.
        """
        return {
            "id": self.id,
            "task_id": self.task_id,
            "level": self.level,
            "message": self.message,
            "sequence": self.sequence,
            # Sanitize extra_data for JSON safety (handles nan/inf in historical data)
            "metadata": sanitize_for_json(self.extra_data) if self.extra_data else None,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class StorageTask(Base):
    """
    Storage Task table.
    Tracks async storage operations like batch import and delete external files.
    """

    __tablename__ = "storage_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)

    # Task type: 'batch_import', 'delete_external'
    task_type = Column(String(50), nullable=False)

    # Status: 'pending', 'processing', 'completed', 'failed'
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text, nullable=True)

    # Task details
    total_items = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)

    # Task-specific parameters (stored as JSON)
    # For batch_import: {dataset_id, dataset_name, task_type, files: [...]}
    # For delete_external: {wsi_ids: [...]}
    params = Column(JSON, nullable=True)

    # Results (stored as JSON)
    # List of {path/wsi_id, status, message, wsi_id}
    results = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "params": self.params,
            "results": self.results,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "started_at": self.started_at.isoformat() + "Z"
            if self.started_at
            else None,
            "completed_at": self.completed_at.isoformat() + "Z"
            if self.completed_at
            else None,
        }


class SegmentationAnnotation(Base):
    """
    Segmentation Annotation table.
    Stores COCO-format annotations for segmentation tasks.
    Annotations can come from viewer drawing, file import, upload, or ROI extraction.

    Status values:
      "draft"        – personal draft (viewer auto-save, scoped to user_id)
      "shared_draft" – collaborative draft (one per dataset, annotation_id = "shared_{dataset_id}")
      "finalized"    – ground-truth, immutable once written

    For shared_draft records:
      user_id       = dataset owner's user_id (stable ownership marker)
      last_edited_by = user_id of whoever last saved this record
      version       = optimistic-lock counter, incremented on every write
    """

    __tablename__ = "segmentation_annotations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    annotation_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    source_dataset_id = Column(
        String(255), ForeignKey("datasets.dataset_id"), nullable=True, index=True
    )

    # Unified COCO format: { "images": [...], "annotations": [...], "categories": [...] }
    annotations = Column(JSON, nullable=False, default=dict)

    # Annotation lifecycle status: "draft" | "shared_draft" | "finalized"
    status = Column(String(20), nullable=False, default="draft")
    visibility_mode = Column(
        String(20), nullable=False, default="personal", server_default="personal"
    )
    # Provenance: "viewer" | "import" | "upload" | "extraction"
    source = Column(String(50), nullable=False, default="viewer")

    # Optimistic-lock version counter (used by shared_draft; always 0 for personal drafts / finalized)
    version = Column(Integer, nullable=False, default=0, server_default="0")

    # Last editor for shared_draft (None for personal drafts and finalized records)
    last_edited_by = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    source_dataset = relationship("Dataset")

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "annotation_id": self.annotation_id,
            "user_id": self.user_id,
            "source_dataset_id": self.source_dataset_id,
            "annotations": self.annotations,
            "status": self.status,
            "visibility_mode": self.visibility_mode,
            "source": self.source,
            "version": self.version,
            "last_edited_by": self.last_edited_by,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class AnnotationAuditLog(Base):
    __tablename__ = "annotation_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(255), nullable=True)
    event_type = Column(String(50), nullable=False)
    event_metadata = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    __table_args__ = (
        Index("idx_audit_log_dataset_created", "dataset_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "event_metadata": self.event_metadata,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class AnalysisRun(Base):
    """
    Analysis Run table.
    Tracks internal analysis runs (statistical analysis on training task results).
    External validation runs are tracked via TrainingTask (task_type='external_validation'
    in the linked DataGroup) and are NOT stored here to avoid double-counting.
    """

    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_id = Column(String(255), unique=True, nullable=False, index=True)
    # Training task whose results are being analyzed (no FK – avoids cross-table constraints)
    task_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    def to_dict(self):
        return {
            "analysis_id": self.analysis_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class DatasetStats(Base):
    __tablename__ = "dataset_stats"

    dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    file_count = Column(Integer, nullable=False, server_default="0")
    total_size = Column(BigInteger, nullable=False, server_default="0")
    split_train_count = Column(Integer, nullable=False, server_default="0")
    split_val_count = Column(Integer, nullable=False, server_default="0")
    split_test_count = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class DatasetGrant(Base):
    __tablename__ = "dataset_grants"

    id = Column(Integer, primary_key=True, autoincrement=True)

    dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(255), nullable=False, index=True)
    granted_by = Column(String(255), nullable=False)

    can_collaborate = Column(Boolean, default=False, nullable=False)
    can_use_gpu = Column(Boolean, default=False, nullable=False)

    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_dataset_grants_user_dataset", "user_id", "dataset_id", unique=True),
    )

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc).replace(tzinfo=None) > self.expires_at

    def is_valid(self) -> bool:
        return not self.is_expired()

    def to_dict(self):
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "user_id": self.user_id,
            "granted_by": self.granted_by,
            "can_collaborate": self.can_collaborate,
            "can_use_gpu": self.can_use_gpu,
            "expires_at": self.expires_at.isoformat() + "Z"
            if self.expires_at
            else None,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "is_expired": self.is_expired(),
            "is_valid": self.is_valid(),
        }


class PermissionAuditLog(Base):
    __tablename__ = "permission_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id = Column(String(255), nullable=False)
    target_user_id = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)
    extra_metadata = Column("metadata", JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    __table_args__ = (
        Index("idx_perm_audit_dataset_created", "dataset_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "actor_id": self.actor_id,
            "target_user_id": self.target_user_id,
            "action": self.action,
            "metadata": self.extra_metadata,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }
