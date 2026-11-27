"""Dataset visibility: owners and admins manage a dataset; public datasets are readable by everyone."""

from sqlalchemy import or_, select

from backend.database.models import Dataset


def accessible_dataset_ids(user, *, write=False):
    query = select(Dataset.dataset_id)
    if user.is_admin():
        return query
    uid = str(user.id)
    if write:
        return query.where(Dataset.user_id == uid)
    return query.where(or_(Dataset.user_id == uid, Dataset.is_public.is_(True)))


async def can_manage_dataset(db, user, dataset):
    return user.is_admin() or dataset.user_id == str(user.id)

