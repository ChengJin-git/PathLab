from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.models import User
from backend.database.models import Dataset
from backend.database.repositories import DatasetGrantRepository


async def can_access_shared(user: User, dataset: Dataset, db: AsyncSession) -> bool:
    if user.is_admin() or dataset.user_id == str(user.id):
        return True
    if not dataset.is_open_collaboration:
        return False
    return await DatasetGrantRepository.has_valid_collaborate(
        db, dataset.dataset_id, str(user.id)
    )


def can_finalize(user: User, dataset: Dataset) -> bool:
    return user.is_admin() or dataset.user_id == str(user.id)


def is_annotation_owner(user: User, dataset: Dataset) -> bool:
    return user.is_admin() or dataset.user_id == str(user.id)
