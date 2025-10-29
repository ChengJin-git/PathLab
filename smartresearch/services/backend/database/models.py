"""
SQLAlchemy Database Models

Following industry best practices from Cytomine and DSA platforms.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON, Index
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
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    ai_tasks = relationship("AITask", back_populates="wsi_slide", cascade="all, delete-orphan")
    ai_results = relationship("AIResult", back_populates="wsi_slide", cascade="all, delete-orphan")

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
    Stores AI analysis results (predictions, probabilities, attention weights).
    """
    __tablename__ = "ai_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wsi_id = Column(String(255), ForeignKey("wsi_slides.wsi_id"), nullable=False, index=True)
    task_id = Column(String(255), ForeignKey("ai_tasks.task_id"), index=True)
    
    # Prediction results
    pred = Column(String(100))  # Predicted label
    probs = Column(JSON)  # Probability distribution {"HSIL": 0.85, "LSIL": 0.12, ...}
    
    # Attention weights (optional, can be large)
    attention_weights = Column(JSON)

    # Additional metadata (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    extra_metadata = Column(JSON)

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
            "attention_weights": self.attention_weights,
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
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "message_count": len(self.messages) if self.messages else 0,
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

