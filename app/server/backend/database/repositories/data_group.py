"""
DataGroupRepository - Data Access Layer
"""

import logging
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from ..models import (
    DataGroup,
    TrainingTask,
    TrainingTaskWSI,
    TrainedModel,
    TrainingLog,
)
from ...ai.task_taxonomy import get_task_metadata, normalize_task_type, validate_task_axes
from .base import BaseRepository


class DataGroupRepository(BaseRepository[DataGroup]):
    """Repository for DataGroup operations"""

    model: type[DataGroup] = DataGroup
    pk_field: str = "group_id"

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        **kwargs,
    ) -> DataGroup:
        """Create a new data group record"""
        group_id = kwargs["group_id"]
        name = kwargs["name"]
        data_type = kwargs["data_type"]
        aggregation_level = kwargs["aggregation_level"]
        task_type = kwargs["task_type"]
        description = kwargs.get("description")

        canonical_task_type = normalize_task_type(
            task_type=task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )
        validate_task_axes(
            task_type=canonical_task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )

        payload = {
            "group_id": group_id,
            "name": name,
            "data_type": data_type,
            "aggregation_level": aggregation_level,
            "task_type": canonical_task_type,
            "description": description,
        }
        data_group = cls.model(**payload)
        db.add(data_group)
        await db.flush()
        await db.refresh(data_group)
        return data_group

    @staticmethod
    async def get_by_combination(
        db: AsyncSession, data_type: str, aggregation_level: str, task_type: str
    ) -> Optional[DataGroup]:
        """Get data group by unique combination of data_type, aggregation_level, task_type"""
        canonical_task_type = normalize_task_type(
            task_type=task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )
        validate_task_axes(
            task_type=canonical_task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )

        result = await db.execute(
            select(DataGroup).where(
                DataGroup.data_type == data_type,
                DataGroup.aggregation_level == aggregation_level,
                DataGroup.task_type == canonical_task_type,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(
        db: AsyncSession,
        data_type: str,
        aggregation_level: str,
        task_type: str,
        name: str | None = None,
        description: str | None = None,
    ) -> DataGroup:
        """Get existing data group by combination or create new one with UUID.

        Race-condition safe under PostgreSQL READ COMMITTED:
        Uses SAVEPOINT + IntegrityError catch to handle concurrent inserts
        that both pass the existence check (UNIQUE constraint on data_type+aggregation_level+task_type).
        """
        import uuid

        canonical_task_type = normalize_task_type(
            task_type=task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )
        validate_task_axes(
            task_type=canonical_task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )

        existing = await DataGroupRepository.get_by_combination(
            db, data_type, aggregation_level, canonical_task_type
        )
        if existing:
            return existing

        # Auto-generate name if not provided
        if name is None:
            canonical_label = get_task_metadata(canonical_task_type).label
            name = f"{data_type.upper()} {aggregation_level.capitalize()}-level {canonical_label}"

        group_id = str(uuid.uuid4())
        try:
            async with db.begin_nested():
                return await DataGroupRepository.create(
                    db,
                    group_id=group_id,
                    name=name,
                    data_type=data_type,
                    aggregation_level=aggregation_level,
                    task_type=canonical_task_type,
                    description=description,
                )
        except IntegrityError:
            # Another concurrent request created the same combination — re-query
            logger.debug(
                f"DataGroup concurrent insert detected for ({data_type}, {aggregation_level}, {canonical_task_type}), re-querying"
            )
            existing = await DataGroupRepository.get_by_combination(
                db, data_type, aggregation_level, canonical_task_type
            )
            if existing:
                return existing
            raise  # Should not happen — re-raise if still not found

    @staticmethod
    async def get_all(db: AsyncSession) -> list[DataGroup]:
        """Get all data groups"""
        result = await db.execute(select(DataGroup).order_by(DataGroup.name))
        return list(result.scalars().all())

    @staticmethod
    async def delete(db: AsyncSession, group_id: str) -> bool:
        """Delete a training contract and its training records, children first."""
        # Get all training_task_ids in this group
        tt_query = await db.execute(
            select(TrainingTask.task_id).where(TrainingTask.group_id == group_id)
        )
        task_ids = [row[0] for row in tt_query.fetchall()]

        if task_ids:
            # Delete training task children
            await db.execute(
                delete(TrainingTaskWSI).where(TrainingTaskWSI.task_id.in_(task_ids))
            )
            await db.execute(
                delete(TrainedModel).where(TrainedModel.task_id.in_(task_ids))
            )
            await db.execute(
                delete(TrainingLog).where(TrainingLog.task_id.in_(task_ids))
            )
            # Delete training tasks
            await db.execute(
                delete(TrainingTask).where(TrainingTask.group_id == group_id)
            )

        # Delete the data group itself
        result = await db.execute(
            delete(DataGroup).where(DataGroup.group_id == group_id)
        )
        await db.flush()
        return result.rowcount > 0
