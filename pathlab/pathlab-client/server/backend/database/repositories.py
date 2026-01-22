"""
Data Access Layer (Repository Pattern)

Provides high-level database operations for all models.
"""

from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy import select, update, delete, func, desc, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import WSISlide, AITask, AIResult, ChatConversation, ChatMessage, TrainingTask, TrainingTaskWSI, TrainedModel, TrainingLog, UserProfile, utc_now
from backend.ai.utils.data_splitter import split_wsi_dataset


class WSIRepository:
    """Repository for WSI Slide operations"""

    @staticmethod
    async def rename_dataset(db: AsyncSession, old_name: str, new_name: str) -> int:
        """
        Rename a dataset by updating dataset_name for all associated slides.
        
        Args:
            db: Database session
            old_name: Current dataset name
            new_name: New dataset name
            
        Returns:
            Number of updated records
        """
        # Handle "Uncategorized" special case
        target_dataset_name = None if old_name == "Uncategorized" else old_name
        new_val = None if new_name == "Uncategorized" else new_name
        
        if target_dataset_name is None:
            # Rename from Uncategorized
            stmt = update(WSISlide).where(WSISlide.dataset_name.is_(None)).values(dataset_name=new_val)
        else:
            # Rename from normal name
            stmt = update(WSISlide).where(WSISlide.dataset_name == target_dataset_name).values(dataset_name=new_val)
            
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount

    @staticmethod
    async def create(db: AsyncSession, wsi_data: Dict) -> WSISlide:
        """Create a new WSI slide record"""
        wsi = WSISlide(**wsi_data)
        db.add(wsi)
        await db.flush()
        await db.refresh(wsi)
        return wsi

    @staticmethod
    async def get_by_id(db: AsyncSession, wsi_id: str) -> Optional[WSISlide]:
        """Get WSI by wsi_id"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, skip: int = 0, limit: int = 0) -> List[WSISlide]:
        """Get all WSI slides with pagination. If limit=0, return all records."""
        query = select(WSISlide).order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Get total count of WSI slides"""
        result = await db.execute(select(func.count(WSISlide.id)))
        return result.scalar_one()

    @staticmethod
    async def get_by_label(db: AsyncSession, label: str) -> List[WSISlide]:
        """Get all WSI slides with specific label"""
        result = await db.execute(
            select(WSISlide).where(WSISlide.label == label)
        )
        return result.scalars().all()

    @staticmethod
    async def update(db: AsyncSession, wsi_id: str, update_data: Dict) -> Optional[WSISlide]:
        """Update WSI slide"""
        update_data["updated_at"] = utc_now()
        await db.execute(
            update(WSISlide)
            .where(WSISlide.wsi_id == wsi_id)
            .values(**update_data)
        )
        await db.flush()
        return await WSIRepository.get_by_id(db, wsi_id)

    @staticmethod
    async def update_splits(db: AsyncSession, dataset_name: str, updates: List[tuple]) -> int:
        """
        Batch update split column for multiple WSIs.
        
        Args:
            db: Database session
            dataset_name: Dataset name for validation (optional but recommended)
            updates: List of (wsi_id, split_value) tuples
            
        Returns:
            Number of successfully updated records
        """
        count = 0
        for wsi_id, split_val in updates:
            # We can optimize this with a single update statement using a CASE/binding
            # but for SQLite simplicity relative to list size, individual updates are acceptable
            # or we could do `UPDATE wsi_slides SET split = :split WHERE wsi_id = :wsi_id` in a batch.
            
            # Simple check + update
            stmt = (
                update(WSISlide)
                .where(WSISlide.wsi_id == wsi_id)
                # .where(WSISlide.dataset_name == dataset_name) # Check dataset if needed
                .values(split=split_val, updated_at=utc_now())
            )
            result = await db.execute(stmt)
            count += result.rowcount
            
        await db.commit()
        return count


    @staticmethod
    async def delete(db: AsyncSession, wsi_id: str) -> bool:
        """Delete WSI slide"""
        result = await db.execute(
            delete(WSISlide).where(WSISlide.wsi_id == wsi_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total WSI slides"""
        result = await db.execute(select(func.count(WSISlide.id)))
        return result.scalar()

    @staticmethod
    async def get_label_distribution(db: AsyncSession) -> Dict[str, int]:
        """Get distribution of labels"""
        result = await db.execute(
            select(WSISlide.label, func.count(WSISlide.id))
            .group_by(WSISlide.label)
        )
        return {label: count for label, count in result.all() if label}

    @staticmethod
    async def get_existing_original_filenames(db: AsyncSession, filenames: List[str]) -> List[str]:
        """
        Check which original_filenames already exist in the database.

        Args:
            db: Database session
            filenames: List of original_filename values to check

        Returns:
            List of filenames that already exist in the database
        """
        if not filenames:
            return []
        result = await db.execute(
            select(WSISlide.original_filename)
            .where(WSISlide.original_filename.in_(filenames))
        )
        return [row[0] for row in result.all() if row[0]]

    # File type classification constants
    WSI_EXTENSIONS = ('.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif', '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.tmap', '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax')
    PATCH_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp')
    TIF_EXTENSIONS = ('.tif', '.tiff')
    SIZE_THRESHOLD = 100 * 1024 * 1024  # 100 MB threshold for .tif/.tiff files

    @staticmethod
    async def get_datasets(db: AsyncSession, data_level: Optional[str] = None) -> List[Dict]:
        """
        Get all unique dataset names with file count and total size.

        Args:
            db: Database session
            data_level: Optional filter - "wsi" for WSI files, "patch" for image files
                       If None, returns all datasets

        Returns:
            List of dicts: [{"dataset_name": str, "file_count": int, "total_size": int}, ...]
        """
        from sqlalchemy import or_, and_, case

        # Build file type filter based on data_level
        if data_level == "wsi":
            # WSI files: specific extensions OR .tif/.tiff >= 100MB
            wsi_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.WSI_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in WSIRepository.TIF_EXTENSIONS
                    ),
                    WSISlide.file_size >= WSIRepository.SIZE_THRESHOLD
                )
            ]
            file_filter = or_(*wsi_ext_conditions, *tif_conditions)
        elif data_level == "patch":
            # Patch files: image extensions OR .tif/.tiff < 100MB
            patch_ext_conditions = [func.lower(WSISlide.wsi_path).like(f'%{ext}') for ext in WSIRepository.PATCH_EXTENSIONS]
            tif_conditions = [
                and_(
                    or_(
                        func.lower(WSISlide.wsi_path).like('%' + ext)
                        for ext in WSIRepository.TIF_EXTENSIONS
                    ),
                    or_(
                        WSISlide.file_size < WSIRepository.SIZE_THRESHOLD,
                        WSISlide.file_size.is_(None)
                    )
                )
            ]
            file_filter = or_(*patch_ext_conditions, *tif_conditions)
        else:
            file_filter = None

        # Build query - include count of files with survival data to determine dataset_type
        # A dataset is "survival" if any file has event_time set
        survival_count = func.sum(
            case(
                (WSISlide.event_time.isnot(None), 1),
                else_=0
            )
        ).label("survival_count")

        query = select(
            WSISlide.dataset_name,
            func.count(WSISlide.id).label("file_count"),
            func.sum(WSISlide.file_size).label("total_size"),
            survival_count
        )

        if file_filter is not None:
            query = query.where(file_filter)

        query = query.group_by(WSISlide.dataset_name).order_by(WSISlide.dataset_name)

        result = await db.execute(query)
        datasets = []
        for row in result.all():
            # Determine dataset_type: "survival" if any file has event_time, else "classification"
            dataset_type = "survival" if (row.survival_count or 0) > 0 else "classification"
            datasets.append({
                "dataset_name": row.dataset_name or "Uncategorized",
                "file_count": row.file_count,
                "total_size": row.total_size or 0,
                "dataset_type": dataset_type
            })
        return datasets

    @staticmethod
    async def get_by_dataset(db: AsyncSession, dataset_name: str, skip: int = 0, limit: int = 0) -> List[WSISlide]:
        """
        Get all WSI slides in a specific dataset with pagination.

        Args:
            db: Database session
            dataset_name: Dataset name to filter by (use "Uncategorized" for NULL dataset_name)
            skip: Number of records to skip
            limit: Maximum number of records to return (0 = all)

        Returns:
            List of WSISlide objects
        """
        if dataset_name == "Uncategorized":
            query = select(WSISlide).where(WSISlide.dataset_name.is_(None))
        else:
            query = select(WSISlide).where(WSISlide.dataset_name == dataset_name)

        query = query.order_by(desc(WSISlide.created_at)).offset(skip)
        if limit > 0:
            query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def count_by_dataset(db: AsyncSession, dataset_name: str) -> int:
        """
        Count WSI slides in a specific dataset.

        Args:
            db: Database session
            dataset_name: Dataset name to filter by (use "Uncategorized" for NULL dataset_name)

        Returns:
            Number of WSI slides in the dataset
        """
        if dataset_name == "Uncategorized":
            query = select(func.count(WSISlide.id)).where(WSISlide.dataset_name.is_(None))
        else:
            query = select(func.count(WSISlide.id)).where(WSISlide.dataset_name == dataset_name)

        result = await db.execute(query)
        return result.scalar_one()


class AITaskRepository:
    """Repository for AI Task operations"""

    @staticmethod
    async def create(db: AsyncSession, task_data: Dict) -> AITask:
        """Create a new AI task"""
        task = AITask(**task_data)
        db.add(task)
        await db.flush()
        await db.refresh(task)
        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[AITask]:
        """Get task by task_id"""
        result = await db.execute(
            select(AITask).where(AITask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> List[AITask]:
        """Get all tasks for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_latest_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AITask]:
        """Get latest task for a WSI"""
        result = await db.execute(
            select(AITask)
            .where(AITask.wsi_id == wsi_id)
            .order_by(desc(AITask.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Optional[AITask]:
        """Update task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress

        if error_message is not None:
            update_data["error_message"] = error_message

        if status == "running" and not await AITaskRepository._has_started(db, task_id):
            update_data["started_at"] = utc_now()

        if status in ["completed", "failed"]:
            update_data["finished_at"] = utc_now()
            update_data["progress"] = 100 if status == "completed" else update_data.get("progress", 0)

        await db.execute(
            update(AITask)
            .where(AITask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await AITaskRepository.get_by_id(db, task_id)

    @staticmethod
    async def _has_started(db: AsyncSession, task_id: str) -> bool:
        """Check if task has started_at timestamp"""
        result = await db.execute(
            select(AITask.started_at).where(AITask.task_id == task_id)
        )
        started_at = result.scalar_one_or_none()
        return started_at is not None

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total tasks"""
        result = await db.execute(select(func.count(AITask.id)))
        return result.scalar()

    @staticmethod
    async def count_completed(db: AsyncSession) -> int:
        """Count completed tasks"""
        result = await db.execute(
            select(func.count(AITask.id)).where(AITask.status == "completed")
        )
        return result.scalar()


class AIResultRepository:
    """Repository for AI Result operations"""

    @staticmethod
    async def create(db: AsyncSession, result_data: Dict) -> AIResult:
        """Create a new AI result"""
        result = AIResult(**result_data)
        db.add(result)
        await db.flush()
        await db.refresh(result)
        return result

    @staticmethod
    async def get_by_wsi_id(db: AsyncSession, wsi_id: str) -> Optional[AIResult]:
        """Get latest result for a WSI"""
        result = await db.execute(
            select(AIResult)
            .where(AIResult.wsi_id == wsi_id)
            .order_by(desc(AIResult.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> Optional[AIResult]:
        """Get result by task_id"""
        result = await db.execute(
            select(AIResult).where(AIResult.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def count(db: AsyncSession) -> int:
        """Count total results"""
        result = await db.execute(select(func.count(AIResult.id)))
        return result.scalar()


class ChatRepository:
    """Repository for Chat Conversation and Message operations"""

    @staticmethod
    async def create_conversation(db: AsyncSession, conversation_data: Dict) -> ChatConversation:
        """Create a new conversation"""
        conversation = ChatConversation(**conversation_data)
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)
        return conversation

    @staticmethod
    async def get_conversation(db: AsyncSession, conversation_id: str) -> Optional[ChatConversation]:
        """Get conversation by ID with messages"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.conversation_id == conversation_id)
            .options(selectinload(ChatConversation.messages))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_conversations(
        db: AsyncSession,
        user_id: str,
        skip: int = 0,
        limit: int = 50
    ) -> List[ChatConversation]:
        """Get all conversations for a user"""
        result = await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(desc(ChatConversation.updated_at))
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def add_message(db: AsyncSession, message_data: Dict) -> ChatMessage:
        """Add a message to a conversation"""
        message = ChatMessage(**message_data)
        db.add(message)

        # Update conversation's updated_at timestamp
        await db.execute(
            update(ChatConversation)
            .where(ChatConversation.conversation_id == message_data["conversation_id"])
            .values(updated_at=utc_now())
        )

        await db.flush()
        await db.refresh(message)
        return message

    @staticmethod
    async def get_messages(
        db: AsyncSession,
        conversation_id: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[ChatMessage]:
        """Get messages for a conversation"""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def delete_conversation(db: AsyncSession, conversation_id: str) -> bool:
        """Delete a conversation and all its messages"""
        # First delete all messages (due to foreign key constraint)
        await db.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        )

        # Then delete the conversation
        result = await db.execute(
            delete(ChatConversation).where(ChatConversation.conversation_id == conversation_id)
        )
        await db.flush()
        return result.rowcount > 0




class TrainingTaskRepository:
    """Repository for Training Task operations"""

    @staticmethod
    async def create(
        db: AsyncSession,
        task_data: Dict,
        wsi_ids: List[str],
        split_config: Optional[Dict] = None
    ) -> TrainingTask:
        """
        Create a new training task with associated WSI slides.
        Automatically extracts classes from WSI labels.

        For large datasets (10k+ WSIs), uses bulk inserts to avoid SQLite issues.
        """
        # Extract unique classes from WSI labels
        # For large datasets, query in batches to avoid SQLite limitations
        wsis = []
        batch_size = 500  # SQLite variable limit is 999, stay well below
        for i in range(0, len(wsi_ids), batch_size):
            batch_ids = wsi_ids[i:i + batch_size]
            wsi_list = await db.execute(
                select(WSISlide).where(WSISlide.wsi_id.in_(batch_ids))
            )
            wsis.extend(wsi_list.scalars().all())

        # Get unique labels (classes)
        classes = sorted(list(set(wsi.label for wsi in wsis if wsi.label)))

        # Add split_config to preprocessing_config for persistence
        if split_config:
            preprocessing_config = task_data.get("preprocessing_config", {}) or {}
            preprocessing_config["split_config"] = split_config
            task_data["preprocessing_config"] = preprocessing_config

        # Create training task
        task = TrainingTask(
            **task_data,
            classes=classes,
            status="pending",
            progress=0
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)

        # Commit the task first to ensure it exists before associations
        await db.commit()

        # Calculate splits
        wsi_splits = {}
        if split_config:
            strategy = split_config.get("strategy", "random")

            if strategy == "manual":
                # For manual strategy, read splits directly from WSI records in database
                # This is more reliable than depending on frontend state which may be stale
                wsi_split_map = {wsi.wsi_id: wsi.split for wsi in wsis if wsi.split}
                wsi_splits = wsi_split_map
            else:
                # For other strategies (random, k_fold), use the splitter function
                wsi_splits = split_wsi_dataset(wsi_ids, **split_config)

        # Use bulk insert to avoid ORM identity map issues and improve performance
        # This is much faster and more reliable for large datasets
        insert_batch_size = 1000
        for i in range(0, len(wsi_ids), insert_batch_size):
            batch_wsi_ids = wsi_ids[i:i + insert_batch_size]

            # Build list of records to insert
            records = []
            for wsi_id in batch_wsi_ids:
                split = wsi_splits.get(wsi_id, "train")
                records.append({
                    "task_id": task.task_id,
                    "wsi_id": wsi_id,
                    "split": split,
                    "created_at": utc_now()
                })

            # Bulk insert using Core API (bypasses ORM identity map)
            if records:
                await db.execute(insert(TrainingTaskWSI), records)
                await db.commit()

        return task

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: str) -> Optional[TrainingTask]:
        """Get training task by task_id"""
        result = await db.execute(
            select(TrainingTask).where(TrainingTask.task_id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, limit: int = 100, offset: int = 0) -> List[TrainingTask]:
        """Get all training tasks"""
        result = await db.execute(
            select(TrainingTask)
            .order_by(desc(TrainingTask.created_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    @staticmethod
    async def get_wsi_ids(db: AsyncSession, task_id: str) -> List[str]:
        """Get all WSI IDs associated with a training task"""
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def get_wsi_with_labels(db: AsyncSession, task_id: str) -> List[Dict]:
        """
        Get all WSI slides associated with a training task, including their labels and splits.

        Returns:
            List of dicts with keys: wsi_id, wsi_path, label, split
        """
        result = await db.execute(
            select(
                WSISlide.wsi_id,
                WSISlide.wsi_path,
                WSISlide.label,
                TrainingTaskWSI.split
            )
            .join(TrainingTaskWSI, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
            .where(TrainingTaskWSI.task_id == task_id)
        )
        return [
            {
                "wsi_id": row[0],
                "wsi_path": row[1],
                "label": row[2],
                "split": row[3]
            }
            for row in result.all()
        ]

    @staticmethod
    async def get_wsi_ids_by_split(db: AsyncSession, task_id: str) -> Dict[str, List[str]]:
        """
        Get WSI IDs grouped by their split assignment.

        Returns:
            Dict with split names as keys and lists of wsi_ids as values.
            For regular splits: {'train': [...], 'val': [...], 'test': [...]}
            For k-fold: {'fold_0': [...], 'fold_1': [...], ...}
        """
        result = await db.execute(
            select(TrainingTaskWSI.wsi_id, TrainingTaskWSI.split)
            .where(TrainingTaskWSI.task_id == task_id)
        )

        splits_map: Dict[str, List[str]] = {}
        for row in result.all():
            wsi_id, split = row[0], row[1]
            if split not in splits_map:
                splits_map[split] = []
            splits_map[split].append(wsi_id)

        return splits_map

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task_id: str,
        status: str,
        progress: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Optional[TrainingTask]:
        """Update training task status"""
        update_data = {"status": status}

        if progress is not None:
            update_data["progress"] = progress

        if error_message is not None:
            update_data["error_message"] = error_message

        if status == "running":
            update_data["started_at"] = utc_now()

        if status in ["completed", "failed"]:
            update_data["finished_at"] = utc_now()
            update_data["progress"] = 100 if status == "completed" else update_data.get("progress", 0)

        await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .values(**update_data)
        )
        await db.flush()
        return await TrainingTaskRepository.get_by_id(db, task_id)

    # Status values that indicate a task was interrupted (not failed normally)
    INTERRUPTED_STATUSES = ['running', 'extracting', 'training']

    @staticmethod
    async def get_interrupted_tasks(db: AsyncSession) -> List[TrainingTask]:
        """
        Get all training tasks that were interrupted (e.g., by system shutdown).

        These are tasks with status 'running', 'extracting', or 'training' -
        states that indicate the task was in progress but never completed or failed.
        If the system restarts and a task has one of these statuses, it was interrupted.

        Note: 'failed' tasks are NOT considered interrupted - they failed normally.
        """
        result = await db.execute(
            select(TrainingTask)
            .where(TrainingTask.status.in_(TrainingTaskRepository.INTERRUPTED_STATUSES))
            .order_by(TrainingTask.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def try_claim_for_resume(db: AsyncSession, task_id: str) -> bool:
        """
        Atomically try to claim a task for resume using compare-and-swap.

        This method is safe for multi-instance deployments. Only one instance
        can successfully claim a task because:
        1. The UPDATE uses WHERE status IN (interrupted_statuses)
        2. Only rows matching the condition are updated
        3. If another instance already claimed it (changed status to 'pending'),
           this UPDATE will affect 0 rows

        The task is set to 'pending' status temporarily. The pipeline will
        update it to 'running' when it starts.

        Returns:
            True if this instance successfully claimed the task
            False if another instance already claimed it or task not found
        """
        result = await db.execute(
            update(TrainingTask)
            .where(TrainingTask.task_id == task_id)
            .where(TrainingTask.status.in_(TrainingTaskRepository.INTERRUPTED_STATUSES))
            .values(
                status='pending',  # Temporary until pipeline starts
                progress=0,
                error_message=None,  # Clear previous error if any
                updated_at=utc_now()
            )
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def delete(db: AsyncSession, task_id: str) -> bool:
        """Delete a training task and all associated records"""
        # First check if task exists
        task = await TrainingTaskRepository.get_by_id(db, task_id)
        if not task:
            return False

        # Delete associated WSI records (should cascade automatically, but being explicit)
        await db.execute(
            delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id == task_id)
        )

        # Delete associated trained models (should cascade automatically, but being explicit)
        await db.execute(
            delete(TrainedModel).where(TrainedModel.task_id == task_id)
        )

        # Delete the training task itself
        result = await db.execute(
            delete(TrainingTask).where(TrainingTask.task_id == task_id)
        )
        await db.flush()
        return result.rowcount > 0


class TrainedModelRepository:
    """Repository for Trained Model operations"""

    @staticmethod
    async def create(db: AsyncSession, model_data: Dict) -> TrainedModel:
        """Create a new trained model"""
        model = TrainedModel(**model_data)
        db.add(model)
        await db.flush()
        await db.refresh(model)
        return model

    @staticmethod
    async def get_by_id(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Get trained model by model_id"""
        result = await db.execute(
            select(TrainedModel).where(TrainedModel.model_id == model_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: str) -> List[TrainedModel]:
        """Get all models from a training task"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.task_id == task_id)
            .order_by(desc(TrainedModel.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def get_all(db: AsyncSession, limit: int = 100, offset: int = 0) -> List[TrainedModel]:
        """Get all trained models"""
        result = await db.execute(
            select(TrainedModel)
            .order_by(desc(TrainedModel.created_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    @staticmethod
    async def delete(db: AsyncSession, model_id: str) -> bool:
        """Delete a trained model"""
        result = await db.execute(
            delete(TrainedModel).where(TrainedModel.model_id == model_id)
        )
        await db.flush()
        return result.rowcount > 0

    @staticmethod
    async def get_default(db: AsyncSession) -> Optional[TrainedModel]:
        """Get the default model for inference"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.is_default == True)
            .where(TrainedModel.is_active == True)
            .order_by(desc(TrainedModel.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_models(db: AsyncSession) -> List[TrainedModel]:
        """Get all active models"""
        result = await db.execute(
            select(TrainedModel)
            .where(TrainedModel.is_active == True)
            .order_by(desc(TrainedModel.created_at))
        )
        return result.scalars().all()

    @staticmethod
    async def set_default(db: AsyncSession, model_id: str) -> Optional[TrainedModel]:
        """Set a model as default (unset all others)"""
        # First, unset all default flags
        await db.execute(
            update(TrainedModel).values(is_default=False)
        )

        # Then set the specified model as default
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_default=True, is_active=True)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)

    @staticmethod
    async def set_active(db: AsyncSession, model_id: str, is_active: bool) -> Optional[TrainedModel]:
        """Activate or deactivate a model"""
        await db.execute(
            update(TrainedModel)
            .where(TrainedModel.model_id == model_id)
            .values(is_active=is_active)
        )
        await db.flush()
        return await TrainedModelRepository.get_by_id(db, model_id)


class TrainingLogRepository:
    """Repository for Training Log operations"""

    @staticmethod
    async def create(db: AsyncSession, log_data: Dict) -> TrainingLog:
        """Create a new training log entry"""
        log = TrainingLog(**log_data)
        db.add(log)
        await db.flush()
        await db.refresh(log)
        return log

    @staticmethod
    async def get_by_task_id(
        db: AsyncSession,
        task_id: str,
        level: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[TrainingLog]:
        """
        Get logs for a training task with optional filtering.

        Args:
            db: Database session
            task_id: Training task ID
            level: Optional log level filter (INFO, WARNING, ERROR, DEBUG)
            limit: Maximum number of logs to return
            offset: Offset for pagination
        """
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)

        if level:
            query = query.where(TrainingLog.level == level)

        query = query.order_by(TrainingLog.created_at, TrainingLog.sequence)
        query = query.limit(limit).offset(offset)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def get_recent(
        db: AsyncSession,
        task_id: str,
        count: int = 100
    ) -> List[TrainingLog]:
        """
        Get the most recent N logs for a training task.

        Args:
            db: Database session
            task_id: Training task ID
            count: Number of recent logs to return
        """
        query = select(TrainingLog).where(TrainingLog.task_id == task_id)
        query = query.order_by(desc(TrainingLog.created_at), desc(TrainingLog.sequence))
        query = query.limit(count)

        result = await db.execute(query)
        logs = result.scalars().all()

        # Return in chronological order
        return list(reversed(logs))

    @staticmethod
    async def get_logs_after_sequence(
        db: AsyncSession,
        task_id: str,
        after_sequence: int,
        limit: int = 100
    ) -> List[TrainingLog]:
        """
        Get logs after a specific sequence number (for streaming/polling).

        Args:
            db: Database session
            task_id: Training task ID
            after_sequence: Get logs with sequence > this value
            limit: Maximum number of logs to return
        """
        query = select(TrainingLog).where(
            TrainingLog.task_id == task_id,
            TrainingLog.sequence > after_sequence
        )
        query = query.order_by(TrainingLog.created_at, TrainingLog.sequence)
        query = query.limit(limit)

        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def delete_by_task_id(db: AsyncSession, task_id: str) -> bool:
        """Delete all logs for a training task"""
        result = await db.execute(
            delete(TrainingLog).where(TrainingLog.task_id == task_id)
        )
        await db.flush()
        return result.rowcount > 0


class UserProfileRepository:
    """Repository for User Profile operations"""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> Optional[UserProfile]:
        """Get user profile by user_id"""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_current_user(db: AsyncSession) -> Optional[UserProfile]:
        """Get the current logged-in user"""
        result = await db.execute(
            select(UserProfile).where(UserProfile.is_current == True)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(db: AsyncSession, profile_data: Dict) -> UserProfile:
        """Create or update user profile"""
        user_id = profile_data.get("user_id")
        existing = await UserProfileRepository.get_by_id(db, user_id)

        if existing:
            # Update existing profile
            for key, value in profile_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = utc_now()
            await db.flush()
            return existing
        else:
            # Create new profile
            profile = UserProfile(**profile_data)
            db.add(profile)
            await db.flush()
            return profile

    @staticmethod
    async def update(db: AsyncSession, user_id: str, updates: Dict) -> Optional[UserProfile]:
        """Update user profile"""
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(**updates, updated_at=utc_now())
        )
        await db.flush()
        return await UserProfileRepository.get_by_id(db, user_id)

    @staticmethod
    async def set_current_user(db: AsyncSession, user_id: str) -> None:
        """Set a user as the current user (unsets all others)"""
        # Unset all current flags
        await db.execute(
            update(UserProfile).values(is_current=False)
        )
        # Set the specified user as current
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(is_current=True)
        )
        await db.flush()

    @staticmethod
    async def update_tokens(
        db: AsyncSession,
        user_id: str,
        access_token: str,
        refresh_token: Optional[str],
        expires_at: Optional[datetime]
    ) -> None:
        """Update user tokens"""
        updates = {
            "access_token_encrypted": access_token,
            "token_expires_at": expires_at,
            "updated_at": utc_now()
        }
        if refresh_token:
            updates["refresh_token_encrypted"] = refresh_token

        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .values(**updates)
        )
        await db.flush()

    @staticmethod
    async def delete(db: AsyncSession, user_id: str) -> bool:
        """Delete user profile"""
        result = await db.execute(
            delete(UserProfile).where(UserProfile.user_id == user_id)
        )
        await db.flush()
        return result.rowcount > 0
