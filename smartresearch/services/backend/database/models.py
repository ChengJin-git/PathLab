"""
SQLAlchemy Database Models

Following industry best practices from Cytomine and DSA platforms.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Index, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class WSISlide(Base):
    """
    WSI Slide metadata table.
    Stores metadata for whole slide images.
    """
    __tablename__ = "wsi_slides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wsi_id = Column(String(255), unique=True, nullable=False, index=True)
    case_id = Column(String(255), index=True)
    label = Column(String(100), index=True)
    wsi_path = Column(Text, nullable=False)

    # Patient metadata
    age = Column(Integer)  # Patient age
    gender = Column(String(20))  # Patient gender (e.g., Male, Female, Other)
    source = Column(String(100))  # Organ/tissue source (e.g., Cervix, Lung, Breast)

    # WSI properties
    mpp = Column(Float)  # Microns per pixel
    vendor = Column(String(100))
    width = Column(Integer)
    height = Column(Integer)
    magnification = Column(Integer)
    file_size = Column(Integer)  # File size in bytes

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    ai_tasks = relationship("AITask", back_populates="wsi_slide", cascade="all, delete-orphan")
    ai_results = relationship("AIResult", back_populates="wsi_slide", cascade="all, delete-orphan")
    training_task_associations = relationship("TrainingTaskWSI", back_populates="wsi_slide", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "wsi_id": self.wsi_id,
            "case_id": self.case_id,
            "label": self.label,
            "wsi_path": self.wsi_path,
            "age": self.age,
            "gender": self.gender,
            "source": self.source,
            "mpp": self.mpp,
            "vendor": self.vendor,
            "width": self.width,
            "height": self.height,
            "magnification": self.magnification,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AITask(Base):
    """
    AI Task table.
    Stores AI analysis task records and status.
    """
    __tablename__ = "ai_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, nullable=False, index=True)
    wsi_id = Column(String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True)
    task_type = Column(String(50), nullable=False)  # e.g., "wsi-classification"
    status = Column(String(20), nullable=False, index=True)  # pending, running, completed, failed
    progress = Column(Integer, default=0)  # 0-100

    # Task parameters (JSON)
    params = Column(JSON)

    # Error message if failed
    error_message = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
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
            "params": self.params,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class AIResult(Base):
    """
    AI Result table.
    Stores AI analysis results metadata (predictions, probabilities).
    Large data (attention weights) is stored in files.
    """
    __tablename__ = "ai_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wsi_id = Column(String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True)
    task_id = Column(String(255), ForeignKey("ai_tasks.task_id"), index=True)

    # Prediction results
    pred = Column(String(100))  # Predicted label
    probs = Column(JSON)  # Probability distribution {"HSIL": 0.85, "LSIL": 0.12, ...}

    # Additional metadata (file paths, model info, etc.)
    extra_metadata = Column(JSON)  # {"attention_path": "ai_results/wsi_001/task_123_attention.npy", ...}

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    wsi_slide = relationship("WSISlide", back_populates="ai_results")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "wsi_id": self.wsi_id,
            "task_id": self.task_id,
            "pred": self.pred,
            "probs": self.probs,
            "metadata": self.extra_metadata,  # Map back to 'metadata' for API compatibility
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        # Avoid lazy loading of messages - only include count if already loaded
        from sqlalchemy import inspect
        insp = inspect(self)
        message_count = len(self.messages) if 'messages' in insp.dict and self.messages else 0

        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "message_count": message_count,
        }


class ChatMessage(Base):
    """
    Chat Message table.
    Stores individual messages in conversations.
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(255), ForeignKey("chat_conversations.conversation_id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)

    # Optional metadata (e.g., model used, tokens, etc.)
    # Renamed from 'metadata' to avoid SQLAlchemy reserved word
    extra_metadata = Column(JSON)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    conversation = relationship("ChatConversation", back_populates="messages")

    # Index for efficient querying
    __table_args__ = (
        Index('idx_conversation_created', 'conversation_id', 'created_at'),
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.extra_metadata,  # Map back to 'metadata' for API compatibility
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
    task_type = Column(String(50), nullable=False)  # "classification" or "segmentation"
    data_level = Column(String(20), nullable=False, default='wsi')  # "wsi" or "patch"
    task_description = Column(Text)

    # Status tracking
    status = Column(String(20), nullable=False, index=True)  # pending, running, completed, failed
    progress = Column(Integer, default=0)  # 0-100
    error_message = Column(Text)

    # Training configuration (JSON)
    preprocessing_config = Column(JSON)  # {tile_size, stride, feature_extractor, feature_batch_size, use_gpu}
    model_config = Column(JSON)  # {aggregator, learning_rate, epochs, optimizer, batch_size}

    # Classes extracted from training data labels
    classes = Column(JSON)  # ["HSIL", "LSIL", "Normal", ...]

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    # Relationships
    wsi_associations = relationship("TrainingTaskWSI", back_populates="training_task", cascade="all, delete-orphan")
    trained_models = relationship("TrainedModel", back_populates="training_task", cascade="all, delete-orphan")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "preprocessing_config": self.preprocessing_config,
            "model_config": self.model_config,
            "classes": self.classes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class TrainingTaskWSI(Base):
    """
    Training Task WSI Association table.
    Many-to-many relationship between training tasks and WSI slides.
    """
    __tablename__ = "training_task_wsi"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True)
    wsi_id = Column(String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True)

    # Split assignment (train/val/test)
    split = Column(String(20))  # "train", "val", "test"

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    training_task = relationship("TrainingTask", back_populates="wsi_associations")
    wsi_slide = relationship("WSISlide", back_populates="training_task_associations")

    # Unique constraint: one WSI can only be in one split per task
    __table_args__ = (
        Index('idx_task_wsi', 'task_id', 'wsi_id', unique=True),
    )


class TrainedModel(Base):
    """
    Trained Model table.
    Stores information about trained models from training tasks.
    """
    __tablename__ = "trained_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(String(255), unique=True, nullable=False, index=True)
    task_id = Column(String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True)
    model_name = Column(String(500), nullable=False)

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
    is_default = Column(Boolean, default=False, nullable=False)  # Whether this is the default model for inference
    is_active = Column(Boolean, default=True, nullable=False)  # Whether this model is available for use

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    training_task = relationship("TrainingTask", back_populates="trained_models")

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "model_id": self.model_id,
            "task_id": self.task_id,
            "model_name": self.model_name,
            "model_path": self.model_path,
            "config_path": self.config_path,
            "classes": self.classes,
            "feature_extractor": self.feature_extractor,
            "aggregator": self.aggregator,
            "train_metrics": self.train_metrics,
            "val_metrics": self.val_metrics,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
    task_id = Column(String(255), ForeignKey("training_tasks.task_id"), nullable=False, index=True)

    # Log metadata
    level = Column(String(20), nullable=False, index=True)  # INFO, WARNING, ERROR, DEBUG
    message = Column(Text, nullable=False)
    sequence = Column(Integer, nullable=False)  # Sequence number within task for ordering

    # Optional structured data (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    extra_data = Column(JSON)  # {progress, epoch, batch, loss, etc.}

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Composite index for efficient querying
    __table_args__ = (
        Index('idx_task_logs', 'task_id', 'created_at', 'sequence'),
    )

    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "level": self.level,
            "message": self.message,
            "sequence": self.sequence,
            "metadata": self.extra_data,  # Map back to 'metadata' for API compatibility
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

