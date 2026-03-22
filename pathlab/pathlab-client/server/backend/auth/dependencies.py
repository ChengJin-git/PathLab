import uuid
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Query, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

from .users import current_active_user, JWT_SECRET
from .models import User
from backend.database.database import get_db


async def require_admin(user: User = Depends(current_active_user)) -> User:
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user


async def require_pathologist_or_admin(
    user: User = Depends(current_active_user),
) -> User:
    if user.role not in {User.ROLE_ADMIN, User.ROLE_PATHOLOGIST}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pathologist or admin access required",
        )
    return user


async def require_can_use_gpu(user: User = Depends(current_active_user)) -> User:
    if not user.can_use_gpu():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GPU operations not available for guest users. Please contact admin for access.",
        )
    return user


async def get_current_user_id(user: User = Depends(current_active_user)) -> str:
    return str(user.id)


async def get_user_id_filter(
    user: User = Depends(current_active_user),
) -> Optional[str]:
    return None if user.is_admin() else str(user.id)


async def get_permitted_dataset_ids(
    user: User, db: AsyncSession
) -> Optional[list[str]]:
    if user.is_admin():
        return None

    from backend.database.repositories import (
        DatasetGrantRepository,
        DatasetRepository,
    )

    public_ids = await DatasetRepository.get_public_dataset_ids(db)
    read_ids = await DatasetGrantRepository.list_read_dataset_ids_for_user(
        db, str(user.id)
    )
    collab_ids = await DatasetGrantRepository.list_collaborate_dataset_ids_for_user(
        db, str(user.id)
    )
    child_ids = await DatasetRepository.get_child_dataset_ids(db, collab_ids)
    return list(set(public_ids + read_ids + collab_ids + child_ids))


def check_data_ownership(resource_user_id: Optional[str], current_user: User) -> bool:
    if current_user.is_admin():
        return True
    if resource_user_id is None:
        return False
    return resource_user_id == str(current_user.id)


async def check_wsi_access_permission(
    user: User,
    wsi_dataset_id: Optional[str],
    wsi_user_id: Optional[str],
    db: AsyncSession,
    *,
    dataset_is_public: bool = False,
    parent_dataset_id: Optional[str] = None,
) -> bool:
    if user.is_admin():
        return True

    if dataset_is_public:
        return True

    if wsi_user_id == str(user.id):
        return True

    if wsi_dataset_id:
        from backend.database.repositories import (
            DatasetGrantRepository,
            DatasetRepository,
        )

        if await DatasetGrantRepository.has_valid_read_access(
            db, wsi_dataset_id, str(user.id)
        ):
            return True

        if parent_dataset_id:
            ancestor_ids = await DatasetRepository.get_ancestor_dataset_ids(
                db, wsi_dataset_id
            )
            for ancestor_id in ancestor_ids:
                if await DatasetGrantRepository.has_valid_collaborate(
                    db, ancestor_id, str(user.id)
                ):
                    return True

    return False


async def check_dataset_access_permission(
    user: User,
    dataset_id: str,
    dataset_user_id: Optional[str],
    db: AsyncSession,
    *,
    is_public: bool = False,
    parent_dataset_id: Optional[str] = None,
) -> bool:
    if user.is_admin():
        return True

    if is_public:
        return True

    if check_data_ownership(dataset_user_id, user):
        return True

    from backend.database.repositories import DatasetGrantRepository, DatasetRepository

    if await DatasetGrantRepository.has_valid_read_access(db, dataset_id, str(user.id)):
        return True

    if parent_dataset_id:
        ancestor_ids = await DatasetRepository.get_ancestor_dataset_ids(db, dataset_id)
        for ancestor_id in ancestor_ids:
            if await DatasetGrantRepository.has_valid_collaborate(
                db, ancestor_id, str(user.id)
            ):
                return True

    return False


async def check_dataset_write_permission(
    user: User,
    dataset_id: str,
    dataset_user_id: Optional[str],
    db: AsyncSession,
    *,
    parent_dataset_id: Optional[str] = None,
) -> bool:
    if user.is_admin():
        return True

    if check_data_ownership(dataset_user_id, user):
        return True

    from backend.database.repositories import DatasetGrantRepository, DatasetRepository

    if await DatasetGrantRepository.has_valid_collaborate(db, dataset_id, str(user.id)):
        return True

    if parent_dataset_id:
        ancestor_ids = await DatasetRepository.get_ancestor_dataset_ids(db, dataset_id)
        for ancestor_id in ancestor_ids:
            if await DatasetGrantRepository.has_valid_collaborate(
                db, ancestor_id, str(user.id)
            ):
                return True

    return False


async def get_dataset_with_access(
    dataset_id: str,
    user: User,
    db: AsyncSession,
    *,
    require_owner: bool = False,
    not_found_detail: str = "Dataset not found",
    forbidden_detail: str = "You don't have permission to access this dataset",
):
    from backend.database.repositories import DatasetRepository

    dataset = await DatasetRepository.get_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if require_owner:
        has_access = check_data_ownership(dataset.user_id, user)
    else:
        has_access = await check_dataset_access_permission(
            user,
            dataset_id,
            dataset.user_id,
            db,
            is_public=dataset.is_public,
            parent_dataset_id=dataset.parent_dataset_id,
        )

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )

    return dataset


async def get_wsi_with_access(
    wsi_id: str,
    user: User,
    db: AsyncSession,
    *,
    require_owner: bool = False,
    with_dataset: bool = False,
    not_found_detail: str = "WSI not found",
    forbidden_detail: str = "You don't have permission to access this WSI",
):
    from backend.database.repositories import WSIRepository

    if with_dataset:
        wsi = await WSIRepository.get_by_id_with_dataset(db, wsi_id)
    else:
        wsi = await WSIRepository.get_by_id(db, wsi_id)

    if not wsi:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if require_owner:
        has_access = check_data_ownership(wsi.user_id, user)
    else:
        dataset_is_public = bool(
            wsi.dataset and getattr(wsi.dataset, "is_public", False)
        )
        parent_dataset_id = (
            wsi.dataset.parent_dataset_id
            if wsi.dataset and getattr(wsi.dataset, "parent_dataset_id", None)
            else None
        )
        has_access = await check_wsi_access_permission(
            user,
            wsi.dataset_id,
            wsi.user_id,
            db,
            dataset_is_public=dataset_is_public,
            parent_dataset_id=parent_dataset_id,
        )

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=forbidden_detail,
        )

    return wsi


async def check_task_access_permission(
    user: User,
    task_user_id: Optional[str],
    task_dataset_id: Optional[str],
    db: AsyncSession,
) -> bool:
    if user.is_admin():
        return True
    return task_user_id == str(user.id)


async def check_dataset_gpu_permission(
    user: User, dataset_id: str, db: AsyncSession
) -> bool:
    if user.can_use_gpu():
        return True

    from backend.database.repositories import DatasetGrantRepository

    return await DatasetGrantRepository.has_valid_gpu(db, dataset_id, str(user.id))


async def require_dataset_gpu_permission(
    user: User, dataset_id: str, db: AsyncSession
) -> None:
    has_permission = await check_dataset_gpu_permission(user, dataset_id, db)
    if not has_permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="GPU operations not available. You need pathologist access or temporary elevated permission for this dataset.",
        )


async def _get_user_from_jwt(token: str, db: AsyncSession) -> User:
    try:
        # Decode JWT token
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=["HS256"], audience="fastapi-users:auth"
        )
        user_id = payload.get("sub")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no user ID",
            )

        # Get user from database
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive"
            )

        # Single-device login enforcement: check session_nonce
        jwt_nonce = payload.get("sn")
        if not jwt_nonce:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please login again.",
            )
        db_nonce = getattr(user, "session_nonce", None)
        if jwt_nonce != db_nonce:
            logger.info(
                f"[Auth] Rejected stale token for user {user.id}: session nonce mismatch"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please login again.",
            )

        return user

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid user ID format: {str(e)}",
        )


async def get_user_from_token_param(
    token: Optional[str] = Query(None, description="JWT token for SSE authentication"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return await _get_user_from_jwt(token, db)


async def get_user_from_header_or_param(
    token: Optional[str] = Query(
        None, alias="token", description="JWT token for image authentication"
    ),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    jwt_token = None
    if authorization and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]  # Remove "Bearer " prefix
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    return await _get_user_from_jwt(jwt_token, db)
