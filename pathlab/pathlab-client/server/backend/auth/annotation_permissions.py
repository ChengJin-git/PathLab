from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.models import User
from backend.database.models import Dataset
from backend.database.repositories import AnnotationCollaboratorRepository


async def can_access_shared(user: User, dataset: Dataset, db: AsyncSession) -> bool:
    if user.is_admin() or dataset.user_id == str(user.id):
        return True
    if dataset.is_public:
        return True
    return await AnnotationCollaboratorRepository.exists(
        db, dataset.dataset_id, str(user.id)
    )


async def can_write_shared(user: User, dataset: Dataset, db: AsyncSession) -> bool:
    if user.is_admin() or dataset.user_id == str(user.id):
        return True
    return await AnnotationCollaboratorRepository.exists(
        db, dataset.dataset_id, str(user.id)
    )


def can_finalize(user: User, dataset: Dataset) -> bool:
    return user.is_admin() or dataset.user_id == str(user.id)


def is_annotation_owner(user: User, dataset: Dataset) -> bool:
    return user.is_admin() or dataset.user_id == str(user.id)
