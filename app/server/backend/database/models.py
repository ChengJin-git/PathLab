"""
SQLAlchemy Database Models

Following industry best practices from Cytomine and DSA platforms.
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    ARRAY,
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
    UniqueConstraint,
    CheckConstraint,
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


class TimestampMixin:
    """Mixin that adds id, created_at, updated_at to every ORM model."""

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class DataGroup(TimestampMixin, Base):
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

    group_id = Column(String(255), nullable=False)  # UUID for API
    name = Column(
        String(255), nullable=False
    )  # Display name (e.g., "WSI Case-level Classification")
    description = Column(Text)  # Optional description

    # Core attributes that define the group
    data_type = Column(String(20), nullable=False)  # 'wsi' | 'patch'
    aggregation_level = Column(String(20), nullable=False)  # 'file' | 'case'
    task_type = Column(
        String(50), nullable=False
    )  # 'wsi_classification' | 'patch_classification' | 'wsi_survival' | 'patch_segmentation'

    # Relationships
    training_tasks = relationship(
        "TrainingTask", back_populates="data_group", cascade="all, delete-orphan"
    )

    # Unique constraint: only one group per combination
    __table_args__ = (
        UniqueConstraint("group_id", name="uq_data_groups_group_id"),
        CheckConstraint("task_type IN ('wsi_classification','patch_classification','wsi_survival','patch_segmentation','patch_detection')",name='chk_data_groups_task_type_canonical'),
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


class Dataset(TimestampMixin, Base):
    """
    Dataset table.
    Stores dataset metadata with UUID for privacy (no plaintext names in API).
    """

    __tablename__ = "datasets"
    created_by = Column(String(255), nullable=True)

    dataset_id = Column(
        String(255), nullable=False, index=True
    )  # UUID for API
    name = Column(
        String(255), nullable=False
    )  # Display name (stored only, never sent in URL/params)
    description = Column(Text)  # Optional description

    # Owner - links to users table (UUID stored as string)
    user_id = Column(
        String(255), index=True, nullable=True
    )  # Nullable for migration of existing data

    data_type = Column(String(20), nullable=False)
    aggregation_level = Column(String(20), nullable=False, default="file")
    metadata_fields = Column(JSON, nullable=False, default=dict, server_default="{}")
    revision = Column(Integer, nullable=False, default=1, server_default="1")

    source_organ = Column(String(100), nullable=True)
    acquisition_metadata = Column(JSON, nullable=True)

    # Visibility: True = all authenticated users can see/access this dataset
    #             False (default) = only owner + explicitly authorized users
    is_public = Column(Boolean, default=False, nullable=False, server_default="false")

    parent_dataset_id = Column(
        String(255),
        ForeignKey("datasets.dataset_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Explicit UniqueConstraint so the constraint appears inline in CREATE TABLE DDL.
    # SQLAlchemy 2.0 emits column-level unique=True as a deferred CREATE UNIQUE INDEX,
    # which is emitted AFTER CREATE TABLE. Because parent_dataset_id has a
    # FK → dataset_id, PostgreSQL rejects CREATE TABLE if there is no inline
    # UNIQUE or PRIMARY KEY constraint on dataset_id at that moment.
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_datasets_dataset_id"),
    )

    # Relationships
    tasks = relationship("DatasetTask", cascade="all, delete-orphan", lazy="selectin", order_by="DatasetTask.task_type")
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
            "metadata": self.metadata_fields,
            "revision": self.revision,
            "source_organ": self.source_organ,
            "acquisition_metadata": self.acquisition_metadata,
            "parent_dataset_id": self.parent_dataset_id,
            "created_by": self.created_by,
            "task_descriptions": {task.task_type: task.description for task in self.tasks},
            "is_public": self.is_public,
            "data_type": self.data_type,
            "aggregation_level": self.aggregation_level,
            "task_types": [task.task_type for task in self.tasks],
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class DatasetTask(Base):
    """Tasks supported by a dataset; labels for different tasks coexist."""
    __tablename__ = "dataset_tasks"
    dataset_id = Column(String(255), ForeignKey("datasets.dataset_id", ondelete="CASCADE"), primary_key=True)
    task_type = Column(String(50), primary_key=True)
    description = Column(Text, nullable=False, default="", server_default="")
    labelled_count = Column(Integer, nullable=False, default=0, server_default="0")
    classes = Column(JSON, nullable=False, default=list, server_default="[]")
    __table_args__ = (
        CheckConstraint("task_type IN ('wsi_classification','patch_classification','wsi_survival','patch_segmentation','patch_detection')", name="chk_dataset_tasks_type"),
        Index("ix_dataset_tasks_type_dataset", "task_type", "dataset_id"),
    )


class WSISlide(TimestampMixin, Base):
    """
    WSI Slide metadata table.
    Stores metadata for whole slide images.
    """

    __tablename__ = "wsi_slides"

    wsi_id = Column(String(255), nullable=False, index=True)
    original_filename = Column(
        String(500)
    )  # Original filename for internal reference (not exposed to frontend)
    dataset_id = Column(
        String(255), ForeignKey("datasets.dataset_id"), index=True
    )  # FK to datasets table (UUID)
    case_id = Column(String(255), index=True)
    label = Column(String(100), index=True)
    metadata_fields = Column(JSON, nullable=False, default=dict, server_default="{}")
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

    # Explicit UniqueConstraint so the constraint appears inline in CREATE TABLE DDL.
    # SQLAlchemy 2.0 emits column-level unique=True as a deferred CREATE UNIQUE INDEX,
    # which is emitted AFTER CREATE TABLE. Because parent_wsi_id has a
    # FK → wsi_id, PostgreSQL rejects CREATE TABLE if there is no inline
    # UNIQUE or PRIMARY KEY constraint on wsi_id at that moment.
    __table_args__ = (
        UniqueConstraint("wsi_id", name="uq_wsi_slides_wsi_id"),
        Index("idx_wsi_user_dataset", "user_id", "dataset_id"),
        Index("idx_wsi_dataset_created", "dataset_id", "created_at"),
        Index("idx_wsi_user_type", "user_id", "data_type"),
        Index("idx_wsi_dataset_type", "dataset_id", "data_type"),
        Index("idx_wsi_dataset_case", "dataset_id", "case_id"),
        Index("idx_wsi_dataset_type_case", "dataset_id", "data_type", "case_id"),
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
            "metadata": self.metadata_fields,
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


class WSISlideUserSplit(TimestampMixin, Base):
    """Per-user split overrides for public datasets."""

    __tablename__ = "wsi_slide_user_splits"

    wsi_id = Column(
        String(255),
        ForeignKey("wsi_slides.wsi_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String(255), nullable=False)
    split = Column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("wsi_id", "user_id", name="uq_wsi_slide_user_splits_wsi_user"),
        Index("idx_wsi_slide_user_splits_user", "user_id"),
        Index("idx_wsi_slide_user_splits_wsi", "wsi_id"),
    )


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


class CapabilityEntry(Base):
    """Shared definitions; personal activation and credentials live separately."""
    __tablename__ = 'capability_entries'
    entry_id = Column(String(80), primary_key=True)
    kind = Column(String(16), nullable=False, index=True)
    owner_id = Column(String(255), nullable=True, index=True)
    builtin = Column(Boolean, nullable=False, default=False)
    name = Column(String(120), nullable=False)
    description = Column(String(1200), nullable=False, default='')
    translations = Column(JSON, nullable=False, default=dict)
    content = Column(Text, nullable=False, default='')
    config = Column(JSON, nullable=False, default=dict)
    visibility = Column(String(16), nullable=False, default='private', index=True)
    revision = Column(Integer, nullable=False, default=1)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
    __table_args__ = (Index('idx_capability_owner_kind', 'owner_id', 'kind', 'entry_id'), Index('idx_capability_visibility_kind', 'visibility', 'kind', 'entry_id'))


class CapabilityInstallation(Base):
    __tablename__ = 'capability_installations'
    user_id = Column(String(255), primary_key=True)
    entry_id = Column(String(80), ForeignKey('capability_entries.entry_id', ondelete='CASCADE'), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    credential = Column(Text, nullable=True)
    connected_revision = Column(Integer, nullable=True)
    tool_catalog = Column(JSON, nullable=False, default=list)
    checked_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class Workspace(TimestampMixin, Base):
    """A saved research scope; membership never grants access to its datasets."""

    __tablename__ = "workspaces"
    workspace_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    dataset_ids = Column(JSON, nullable=False, default=list)
    root_paths = Column(JSON, nullable=False, default=list)
    enabled_skills = Column(JSON, nullable=False, default=list)
    enabled_connectors = Column(JSON, nullable=False, default=list)
    execution_mode = Column(String(20), nullable=False, default="standard")
    version = Column(Integer, nullable=False, default=1)
    archived = Column(Boolean, nullable=False, default=False)


class ChatFolder(TimestampMixin, Base):
    __tablename__ = 'chat_folders'
    folder_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(120), nullable=False)


class ChatConversation(TimestampMixin, Base):
    """
    Chat Conversation table.
    Stores conversation sessions with AI assistant.
    """

    __tablename__ = "chat_conversations"
    __table_args__ = (
        # Explicit UniqueConstraint so the constraint appears inline in CREATE TABLE DDL.
        # Required for the self-referencing FK on parent_conversation_id to be valid
        # at table creation time (PostgreSQL rejects FK referencing non-UNIQUE col).
        UniqueConstraint("conversation_id", name="uq_chat_conversations_conversation_id"),
    )

    conversation_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), index=True)  # For future multi-user support
    title = Column(String(500))  # Auto-generated from first message
    parent_conversation_id = Column(
        String(255),
        ForeignKey("chat_conversations.conversation_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    branch_source_message_count = Column(Integer, nullable=True)
    workspace_id = Column(String(64), nullable=True, index=True)
    folder_id = Column(String(64), nullable=True, index=True)
    pinned = Column(Boolean, nullable=False, default=False)

    # Relationships (order_by ensures messages are always returned in chronological order)
    parent_conversation = relationship(
        "ChatConversation",
        remote_side="ChatConversation.conversation_id",
        foreign_keys="ChatConversation.parent_conversation_id",
        back_populates="child_conversations",
    )
    child_conversations = relationship(
        "ChatConversation",
        foreign_keys="ChatConversation.parent_conversation_id",
        back_populates="parent_conversation",
    )
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
        parent_conversation = insp.dict.get("parent_conversation")

        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "parent_conversation_id": self.parent_conversation_id,
            "parent_conversation_title": (
                parent_conversation.title if parent_conversation else None
            ),
            "branch_source_message_count": self.branch_source_message_count,
            "workspace_id": self.workspace_id,
            "folder_id": self.folder_id,
            "pinned": self.pinned,
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

    # Regeneration variant support: groups all AI responses to the same user message
    # variant_group_id: shared UUID across all variants; NULL for non-regenerated messages
    # is_active_variant: True for the currently displayed variant in each group
    variant_group_id = Column(String(36), nullable=True, index=True)
    is_active_variant = Column(
        Boolean, default=True, nullable=False, server_default="true"
    )

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
            "variant_group_id": self.variant_group_id,
            "is_active_variant": self.is_active_variant,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
        }


class MessageFeedback(TimestampMixin, Base):
    """
    Message Feedback table.
    Stores user feedback for chat messages (thumbs up/down) and task helpfulness ratings.
    Feedback is removed with its source conversation.
    """

    __tablename__ = "message_feedbacks"

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


class TrainingTask(TimestampMixin, Base):
    """
    Training Task table.
    Stores training task configuration and status for no-code training platform.
    """

    __tablename__ = "training_tasks"

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

    __table_args__ = (
        UniqueConstraint("task_id", name="uq_training_tasks_task_id"),
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


class SegmentationAnnotation(TimestampMixin, Base):
    """Published COCO reference labels; interactive objects live in ViewerRegion."""

    __tablename__ = "segmentation_annotations"
    task_type = Column(String(50), nullable=False, default="patch_segmentation", server_default="patch_segmentation", index=True)

    annotation_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    source_dataset_id = Column(
        String(255), ForeignKey("datasets.dataset_id"), nullable=True, index=True
    )

    # Unified COCO format: { "images": [...], "annotations": [...], "categories": [...] }
    annotations = Column(JSON, nullable=False, default=dict)

    status = Column(String(20), nullable=False, default="finalized")
    # Provenance: "viewer" | "import" | "upload" | "extraction"
    source = Column(String(50), nullable=False, default="viewer")

    # Relationships
    source_dataset = relationship("Dataset")

    def to_dict(self):
        """Convert to dictionary for API responses."""
        # Derive annotation_source to distinguish externally-imported GT masks
        # from user-drawn annotations that have been finalized as reference labels.
        if self.source in ("import", "upload"):
            annotation_source = "imported_gt"
        elif self.source == "viewer" and self.status == "finalized":
            annotation_source = "user_label"
        else:
            annotation_source = None

        return {
            "annotation_id": self.annotation_id,
            "user_id": self.user_id,
            "source_dataset_id": self.source_dataset_id,
            "annotations": self.annotations,
            "status": self.status,
            "source": self.source,
            "annotation_source": annotation_source,
            "created_at": self.created_at.isoformat() + "Z"
            if self.created_at
            else None,
            "updated_at": self.updated_at.isoformat() + "Z"
            if self.updated_at
            else None,
        }


class ViewerRegion(Base):
    """Independent, revisioned annotation objects in level-zero slide coordinates."""
    __tablename__ = 'viewer_regions'
    region_id = Column(String(64), primary_key=True)
    wsi_id = Column(String(255), ForeignKey('wsi_slides.wsi_id',ondelete='CASCADE'), nullable=False)
    dataset_id = Column(String(255), ForeignKey('datasets.dataset_id',ondelete='CASCADE'), nullable=True)
    layer = Column(String(20), nullable=False)
    user_id = Column(String(255), nullable=False)
    created_by = Column(String(255), nullable=False)
    edited_by = Column(String(255), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    geometry = Column(JSON, nullable=False)
    label = Column(String(100), nullable=False)
    color = Column(String(9), nullable=False, default='#6366f1')
    task_type = Column(String(50), nullable=False, default='patch_segmentation')
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    width = Column(Float, nullable=False)
    height = Column(Float, nullable=False)
    deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now)
    __table_args__ = (
        Index('ix_viewer_regions_slide_layer','wsi_id','layer','user_id','deleted','region_id'),
        Index('ix_viewer_regions_dataset','dataset_id','layer','deleted'),
    )


class ViewerOperation(Base):
    __tablename__ = 'viewer_operations'
    operation_id = Column(String(64), primary_key=True)
    user_id = Column(String(255),nullable=False)
    wsi_id = Column(String(255),nullable=False,index=True)
    fingerprint = Column(String(64),nullable=False)
    response = Column(JSON,nullable=False)
    created_at = Column(DateTime,default=utc_now,nullable=False)


class FeatureArtifact(Base):
    """Verified feature inventory shared by viewer retrieval and chat planning."""
    __tablename__='feature_artifacts'
    artifact_id=Column(String(64),primary_key=True)
    wsi_id=Column(String(255),ForeignKey('wsi_slides.wsi_id',ondelete='CASCADE'),nullable=False,index=True)
    model_id=Column(String(100),nullable=False)
    feature_path=Column(Text,nullable=False)
    coordinates_path=Column(Text,nullable=True)
    feature_revision=Column(String(100),nullable=False)
    coordinates_revision=Column(String(100),nullable=True)
    contract=Column(JSON,nullable=True)
    rows=Column(Integer,nullable=False)
    dimensions=Column(Integer,nullable=False)
    provenance=Column(JSON,nullable=False,default=dict)
    status=Column(String(30),nullable=False,default='ready')
    verified_at=Column(DateTime,nullable=False,default=utc_now)
    __table_args__=(Index('ix_feature_artifacts_model_image','model_id','wsi_id'),)

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
    External validation runs are tracked via TrainingTask (task_id prefix 'extval_')
    and are NOT stored here to avoid double-counting.
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


class ResultSource(Base):
    """Indexed analysis inputs. Listing never opens prediction or model files."""
    __tablename__ = "result_sources"
    source_id = Column(String(300), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    task_id = Column(String(255), ForeignKey("training_tasks.task_id", ondelete="CASCADE"), index=True)
    session_id = Column(String(255), ForeignKey("auto_research_sessions.session_id", ondelete="CASCADE"), index=True)
    kind = Column(String(30), nullable=False)
    title = Column(String(500), nullable=False)
    task_type = Column(String(80), nullable=False)
    revision = Column(String(80), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    __table_args__ = (Index("ix_result_source_recent", "user_id", "created_at", "source_id"),)


class ResultSourceDataset(Base):
    __tablename__ = "result_source_datasets"
    source_id = Column(String(300), ForeignKey("result_sources.source_id", ondelete="CASCADE"), primary_key=True)
    # Retain provenance when a dataset is deleted; a missing dataset fails access checks.
    dataset_id = Column(String(255), primary_key=True)


class ResultAnalysis(Base):
    """Immutable measured output and its exact configuration/input revisions."""
    __tablename__ = "result_analyses"
    analysis_id = Column(String(80), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    workspace_id = Column(String(64))
    title = Column(String(200), nullable=False)
    config = Column(JSON, nullable=False)
    sources = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    phase = Column(String(30), nullable=False, default="queued", server_default="queued")
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    finished_at = Column(DateTime)
    __table_args__ = (Index("ix_result_analysis_recent", "user_id", "created_at", "analysis_id"),)


class ResultRecipe(Base):
    __tablename__ = "result_recipes"
    recipe_id = Column(String(80), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    config = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class ResultConversation(Base):
    __tablename__ = "result_conversations"
    conversation_id = Column(String(80), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    workspace_id = Column(String(64))
    messages = Column(JSON, nullable=False, default=list)
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


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

class Manuscript(Base):
    """Editable, versioned report with an immutable snapshot of its source evidence."""
    __tablename__ = "manuscripts"

    report_id = Column(String(32), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    source_id = Column(String(255), nullable=False, index=True)
    template = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    evidence = Column(JSON, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_manuscripts_recent", created_at.desc(), report_id.desc()),
        Index("idx_manuscripts_owner_recent", user_id, created_at.desc(), report_id.desc()),
    )


class ManuscriptGeneration(Base):
    """Durable, resumable LLM writing job; progress is separate from source evidence."""
    __tablename__ = "manuscript_generations"

    report_id = Column(String(32), ForeignKey("manuscripts.report_id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    stage = Column(String(40), nullable=False, default="evidence")
    options = Column(JSON, nullable=False, default=dict)
    progress = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class AutoResearchSession(Base):
    """Tracks an automated research session from question to final report."""
    __tablename__ = "auto_research_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False, index=True)
    research_question = Column(Text, nullable=False)
    phase = Column(String(50), nullable=False, default="literature")
    status = Column(String(20), nullable=False, default="running")
    conversation_id = Column(String(255), nullable=True, index=True)
    # Business Chat identity is distinct from the native agent conversation_id.
    chat_conversation_id = Column(String(255), nullable=True, index=True)
    chat_request_id = Column(String(64), nullable=True, unique=True, index=True)
    workspace_path = Column(Text, nullable=True)
    recovery_metadata = Column(JSON, nullable=True)
    # Last event sequence. Kept out of recovery_metadata so appending an event does not
    # rewrite the session's (often large) metadata document.
    event_sequence = Column(Integer, nullable=False, default=0, server_default="0")
    experiment_plan = Column(JSON, nullable=True)
    final_report = Column(Text, nullable=True)
    current_iteration = Column(Integer, default=0)
    max_iterations = Column(Integer, default=3)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    experiments = relationship("AutoResearchExperiment", back_populates="session",
                               cascade="all, delete-orphan")
    events = relationship("AutoResearchEvent", back_populates="session",
                           cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_auto_research_sessions_session_id"),
        Index("idx_ar_session_user_status", "user_id", "status"),
    )

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "research_question": self.research_question,
            "phase": self.phase,
            "status": self.status,
            "conversation_id": self.conversation_id,
            "workspace_path": self.workspace_path,
            "recovery_metadata": self.recovery_metadata,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "updated_at": self.updated_at.isoformat() + "Z" if self.updated_at else None,
        }


class AutoResearchExperiment(Base):
    """Tracks individual experiments within a research session."""
    __tablename__ = "auto_research_experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(255), ForeignKey("auto_research_sessions.session_id",
                        ondelete="CASCADE"), nullable=False, index=True)
    experiment_name = Column(String(500))
    training_task_id = Column(String(255), index=True)
    dataset_id = Column(String(255))
    feature_extractor = Column(String(100))
    aggregator = Column(String(100))
    hyperparams = Column(JSON, nullable=True)
    status = Column(String(20), default="pending")
    metrics = Column(JSON, nullable=True)
    analysis_id = Column(String(255), nullable=True)
    iteration = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    session = relationship("AutoResearchSession", back_populates="experiments")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "experiment_name": self.experiment_name,
            "training_task_id": self.training_task_id,
            "feature_extractor": self.feature_extractor,
            "aggregator": self.aggregator,
            "status": self.status,
            "metrics": self.metrics,
            "iteration": self.iteration,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }


class ResearchJob(Base):
    """Durable background acquisition and sandbox experiment jobs."""
    __tablename__ = "auto_research_jobs"

    job_id = Column(String(128), primary_key=True)
    session_id = Column(String(255), ForeignKey("auto_research_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    payload = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class WorkbenchFile(Base):
    """Searchable metadata; file bytes and directory trees stay off the wire."""
    __tablename__ = "workbench_files"
    file_id = Column(String(64), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    workspace_id = Column(String(64), nullable=True, index=True)
    session_id = Column(String(255), nullable=True, index=True)
    conversation_id = Column(String(255), nullable=True, index=True)
    name = Column(String(500), nullable=False)
    path = Column(Text, nullable=False)
    parent = Column(Text, nullable=False, default="")
    kind = Column(String(20), nullable=False, default="file")
    size = Column(BigInteger, nullable=False, default=0)
    revision = Column(String(100), nullable=False, default="")
    storage_path = Column(Text, nullable=True)
    source_revision = Column(String(100), nullable=True)
    folder_id = Column(String(64), nullable=True, index=True)
    origin = Column(String(20), nullable=False, default='upload')
    source_title = Column(String(500), nullable=True)
    deleted = Column(Boolean, nullable=False, default=False)
    index_status = Column(String(20), nullable=False, default='none')
    indexed_revision = Column(String(100), nullable=True)
    index_progress = Column(Integer, nullable=False, default=0)
    index_error = Column(Text, nullable=True)
    index_lease = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utc_now, nullable=False)
    __table_args__ = (Index("idx_workbench_file_parent", "session_id", "parent", "name", "file_id"),)


class FileLibraryFolder(Base):
    __tablename__ = 'file_library_folders'
    folder_id = Column(String(64), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(120), nullable=False)


class AutoResearchEvent(Base):
    """SSE events for auto-research sessions with cursor-based replay."""
    __tablename__ = "auto_research_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(255), ForeignKey("auto_research_sessions.session_id",
                        ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSON, nullable=False)
    sequence = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    session = relationship("AutoResearchSession", back_populates="events")

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_auto_research_events_session_seq"),
        Index("idx_ar_events_session_seq", "session_id", "sequence"),
    )


# =============================================================================
# Know-How Experience Store (Phase 2.2)
# =============================================================================

class KnowhowEntry(Base):
    """
    Structured domain knowledge entry for experiment planning.

    Three sources:
    - curated:    expert-curated best practices (bootstrapped at startup)
    - experiment: auto-ingested from completed auto-research experiments
    - literature: auto-extracted from literature review findings
    """
    __tablename__ = "knowhow_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # What task
    task_type = Column(String(50), index=True)           # classification / survival / segmentation
    organ = Column(String(100), index=True)              # colorectal / breast / lung / ...
    keywords = Column(ARRAY(String), default=[])         # ['MSI', 'microsatellite'] for overlap query

    # What method
    feature_extractor = Column(String(100))
    aggregator = Column(String(100))
    hyperparams = Column(JSON, default={})

    # What result
    metric_name = Column(String(50))                     # auc / c_index
    metric_value = Column(Float)
    all_metrics = Column(JSON, default={})

    # Where it came from
    source_type = Column(String(20), index=True)         # curated / experiment / literature
    source_ref = Column(String(500))                     # session_id or paper URL
    evidence = Column(Text)                              # recommendation rationale or paper summary

    # Optional dataset info
    dataset_id = Column(String(255), nullable=True)
    dataset_name = Column(String(255), nullable=True)

    # Ranking
    confidence = Column(Float, default=0.5)              # curated=1.0, experiment=metric, literature=0.6
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_knowhow_task_organ", "task_type", "organ"),
        Index("idx_knowhow_source", "source_type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "organ": self.organ,
            "keywords": self.keywords or [],
            "feature_extractor": self.feature_extractor,
            "aggregator": self.aggregator,
            "hyperparams": self.hyperparams or {},
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "all_metrics": self.all_metrics or {},
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }
