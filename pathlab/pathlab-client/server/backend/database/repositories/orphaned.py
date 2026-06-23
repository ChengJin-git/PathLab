"""
OrphanedRecordsRepository - Data Access Layer
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class OrphanedRecordsRepository:
    """
    Repository for detecting and cleaning up orphaned database records.

    Orphaned records are database entries whose referenced entities no longer exist.
    This is the inverse of orphaned files (files without database records).
    """

    @staticmethod
    async def detect_orphaned_records(db: AsyncSession) -> Dict[str, Any]:
        """
        Detect orphaned records in the database.

        Returns:
            {
                "orphaned_ai_tasks": [{"task_id": str, "wsi_id": str}, ...],
                "orphaned_ai_results": [{"id": int, "wsi_id": str, "task_id": str}, ...],
                "orphaned_training_task_wsi": [{"id": int, "task_id": str, "wsi_id": str}, ...],
                "orphaned_training_logs": [{"id": int, "task_id": str}, ...],
                "orphaned_trained_models": [{"model_id": str, "task_id": str}, ...],
                "orphaned_message_feedbacks": [{"id": int, "message_id": int}, ...],
                "orphaned_dataset_grants": [{"id": int, "dataset_id": str}, ...],
                "total_orphaned_count": int,
                "summary": {category: count, ...}
            }
        """
        from ..models import (
            AITask,
            AIResult,
            TrainingTaskWSI,
            TrainingLog,
            TrainedModel,
            MessageFeedback,
            DatasetGrant,
            WSISlide,
            TrainingTask,
            ChatMessage,
            Dataset,
        )

        result = {
            "orphaned_ai_tasks": [],
            "orphaned_ai_results": [],
            "orphaned_training_task_wsi": [],
            "orphaned_training_logs": [],
            "orphaned_trained_models": [],
            "orphaned_message_feedbacks": [],
            "orphaned_dataset_grants": [],
            "total_orphaned_count": 0,
            "summary": {},
        }

        # 1. AI Tasks with non-existent WSI
        # Use LEFT JOIN to find ai_tasks where wsi_slide is NULL
        from sqlalchemy import text

        orphaned_ai_tasks_query = await db.execute(
            select(AITask)
            .outerjoin(WSISlide, AITask.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_ai_tasks = orphaned_ai_tasks_query.scalars().all()
        result["orphaned_ai_tasks"] = [
            {"task_id": t.task_id, "wsi_id": t.wsi_id, "status": t.status}
            for t in orphaned_ai_tasks
        ]

        # 2. AI Results with non-existent WSI
        orphaned_ai_results_query = await db.execute(
            select(AIResult)
            .outerjoin(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_ai_results = orphaned_ai_results_query.scalars().all()
        result["orphaned_ai_results"] = [
            {"id": r.id, "wsi_id": r.wsi_id, "task_id": r.task_id}
            for r in orphaned_ai_results
        ]

        # 3. TrainingTaskWSI with non-existent task or WSI
        # Check for missing training task
        orphaned_task_wsi_by_task = await db.execute(
            select(TrainingTaskWSI)
            .outerjoin(TrainingTask, TrainingTaskWSI.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_by_task = orphaned_task_wsi_by_task.scalars().all()

        # Check for missing WSI
        orphaned_task_wsi_by_wsi = await db.execute(
            select(TrainingTaskWSI)
            .outerjoin(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
            .where(WSISlide.wsi_id == None)
        )
        orphaned_by_wsi = orphaned_task_wsi_by_wsi.scalars().all()

        # Combine and deduplicate
        seen_ids = set()
        orphaned_training_task_wsi = []
        for item in orphaned_by_task + orphaned_by_wsi:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                orphaned_training_task_wsi.append(
                    {"id": item.id, "task_id": item.task_id, "wsi_id": item.wsi_id}
                )
        result["orphaned_training_task_wsi"] = orphaned_training_task_wsi

        # 4. Training Logs with non-existent training task
        orphaned_logs_query = await db.execute(
            select(TrainingLog)
            .outerjoin(TrainingTask, TrainingLog.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_logs = orphaned_logs_query.scalars().all()
        result["orphaned_training_logs"] = [
            {"id": l.id, "task_id": l.task_id, "level": l.level} for l in orphaned_logs
        ]

        # 5. Trained Models with non-existent training task
        orphaned_models_query = await db.execute(
            select(TrainedModel)
            .outerjoin(TrainingTask, TrainedModel.task_id == TrainingTask.task_id)
            .where(TrainingTask.task_id == None)
        )
        orphaned_models = orphaned_models_query.scalars().all()
        result["orphaned_trained_models"] = [
            {"model_id": m.model_id, "task_id": m.task_id, "model_name": m.model_name}
            for m in orphaned_models
        ]

        # 6. Message Feedbacks with non-existent message
        orphaned_feedbacks_query = await db.execute(
            select(MessageFeedback)
            .outerjoin(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .where(ChatMessage.id == None)
        )
        orphaned_feedbacks = orphaned_feedbacks_query.scalars().all()
        result["orphaned_message_feedbacks"] = [
            {"id": f.id, "message_id": f.message_id, "feedback_type": f.feedback_type}
            for f in orphaned_feedbacks
        ]

        orphaned_permissions_query = await db.execute(
            select(DatasetGrant)
            .outerjoin(Dataset, DatasetGrant.dataset_id == Dataset.dataset_id)
            .where(Dataset.dataset_id == None)
        )
        orphaned_permissions = orphaned_permissions_query.scalars().all()
        result["orphaned_dataset_grants"] = [
            {"id": p.id, "dataset_id": p.dataset_id, "user_id": p.user_id}
            for p in orphaned_permissions
        ]

        # Calculate totals
        result["summary"] = {
            "ai_tasks": len(result["orphaned_ai_tasks"]),
            "ai_results": len(result["orphaned_ai_results"]),
            "training_task_wsi": len(result["orphaned_training_task_wsi"]),
            "training_logs": len(result["orphaned_training_logs"]),
            "trained_models": len(result["orphaned_trained_models"]),
            "message_feedbacks": len(result["orphaned_message_feedbacks"]),
            "dataset_grants": len(result["orphaned_dataset_grants"]),
        }
        result["total_orphaned_count"] = sum(result["summary"].values())

        return result

    @staticmethod
    async def cleanup_orphaned_records(
        db: AsyncSession, categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Clean up orphaned records from the database.

        Args:
            db: Database session
            categories: Optional list of categories to clean up.
                       If None, clean up all categories.
                       Options: ["ai_tasks", "ai_results", "training_task_wsi",
                                "training_logs", "trained_models",
                                "message_feedbacks", "dataset_grants"]

        Returns:
            {
                "deleted_counts": {category: count, ...},
                "total_deleted": int,
                "summary": str
            }
        """
        from ..models import (
            AITask,
            AIResult,
            TrainingTaskWSI,
            TrainingLog,
            TrainedModel,
            MessageFeedback,
            DatasetGrant,
            WSISlide,
            TrainingTask,
            ChatMessage,
            Dataset,
        )

        if categories is None:
            categories = [
                "ai_tasks",
                "ai_results",
                "training_task_wsi",
                "training_logs",
                "trained_models",
                "message_feedbacks",
                "dataset_grants",
            ]

        deleted_counts = {}

        # 1. Delete orphaned AI Results FIRST (before AI Tasks, due to FK: ai_results.task_id → ai_tasks.task_id)
        if "ai_results" in categories:
            orphaned_query = await db.execute(
                select(AIResult.id)
                .outerjoin(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(AIResult).where(AIResult.id.in_(orphaned_ids))
                )
                deleted_counts["ai_results"] = result.rowcount
            else:
                deleted_counts["ai_results"] = 0

        # 2. Delete orphaned AI Tasks (after AI Results are cleaned up)
        if "ai_tasks" in categories:
            # Get IDs of orphaned tasks first
            orphaned_query = await db.execute(
                select(AITask.task_id)
                .outerjoin(WSISlide, AITask.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(AITask).where(AITask.task_id.in_(orphaned_ids))
                )
                deleted_counts["ai_tasks"] = result.rowcount
            else:
                deleted_counts["ai_tasks"] = 0

        # 3. Delete orphaned TrainingTaskWSI
        if "training_task_wsi" in categories:
            # By missing task
            orphaned_by_task = await db.execute(
                select(TrainingTaskWSI.id)
                .outerjoin(
                    TrainingTask, TrainingTaskWSI.task_id == TrainingTask.task_id
                )
                .where(TrainingTask.task_id == None)
            )
            ids_by_task = [row[0] for row in orphaned_by_task.fetchall()]

            # By missing WSI
            orphaned_by_wsi = await db.execute(
                select(TrainingTaskWSI.id)
                .outerjoin(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(WSISlide.wsi_id == None)
            )
            ids_by_wsi = [row[0] for row in orphaned_by_wsi.fetchall()]

            orphaned_ids = list(set(ids_by_task + ids_by_wsi))
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainingTaskWSI).where(TrainingTaskWSI.id.in_(orphaned_ids))
                )
                deleted_counts["training_task_wsi"] = result.rowcount
            else:
                deleted_counts["training_task_wsi"] = 0

        # 4. Delete orphaned Training Logs
        if "training_logs" in categories:
            orphaned_query = await db.execute(
                select(TrainingLog.id)
                .outerjoin(TrainingTask, TrainingLog.task_id == TrainingTask.task_id)
                .where(TrainingTask.task_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainingLog).where(TrainingLog.id.in_(orphaned_ids))
                )
                deleted_counts["training_logs"] = result.rowcount
            else:
                deleted_counts["training_logs"] = 0

        # 5. Delete orphaned Trained Models
        if "trained_models" in categories:
            orphaned_query = await db.execute(
                select(TrainedModel.model_id)
                .outerjoin(TrainingTask, TrainedModel.task_id == TrainingTask.task_id)
                .where(TrainingTask.task_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(TrainedModel).where(TrainedModel.model_id.in_(orphaned_ids))
                )
                deleted_counts["trained_models"] = result.rowcount
            else:
                deleted_counts["trained_models"] = 0

        # 6. Delete orphaned Message Feedbacks
        if "message_feedbacks" in categories:
            orphaned_query = await db.execute(
                select(MessageFeedback.id)
                .outerjoin(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
                .where(ChatMessage.id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(MessageFeedback).where(MessageFeedback.id.in_(orphaned_ids))
                )
                deleted_counts["message_feedbacks"] = result.rowcount
            else:
                deleted_counts["message_feedbacks"] = 0

        if "dataset_grants" in categories:
            orphaned_query = await db.execute(
                select(DatasetGrant.id)
                .outerjoin(Dataset, DatasetGrant.dataset_id == Dataset.dataset_id)
                .where(Dataset.dataset_id == None)
            )
            orphaned_ids = [row[0] for row in orphaned_query.fetchall()]
            if orphaned_ids:
                result = await db.execute(
                    delete(DatasetGrant).where(DatasetGrant.id.in_(orphaned_ids))
                )
                deleted_counts["dataset_grants"] = result.rowcount
            else:
                deleted_counts["dataset_grants"] = 0

        total_deleted = sum(deleted_counts.values())

        # Build summary string
        parts = []
        for cat, count in deleted_counts.items():
            if count > 0:
                parts.append(f"{count} {cat.replace('_', ' ')}")

        summary = f"Deleted {total_deleted} orphaned records"
        if parts:
            summary += f": {', '.join(parts)}"

        return {
            "deleted_counts": deleted_counts,
            "total_deleted": total_deleted,
            "summary": summary,
        }
