"""
Trained model management routes
Handles listing, retrieving, managing, and exporting trained models
"""

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from backend.database import get_db
from backend.database.repositories import TrainedModelRepository, TrainingTaskRepository
from backend.auth import current_active_user, User
from backend.auth.dependencies import require_pathologist_or_admin, check_data_ownership
from backend.common.chat_context_cache import invalidate_chat_context

router = APIRouter(prefix="/models", tags=["Trained Models"])
logger = logging.getLogger(__name__)


class ModelUpdateRequest(BaseModel):
    """Request body for updating model properties"""

    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


def _cleanup_temp_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(
            "Failed to remove temporary model export archive %s: %s", path, exc
        )


def _sanitize_export_config(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in {"image_dir", "annotations_path", "save_dir"}:
                continue
            if isinstance(item, str) and any(
                token in lowered for token in ("path", "dir", "root")
            ):
                continue
            sanitized[key] = _sanitize_export_config(item)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_export_config(item) for item in value]

    return value


def _resolve_model_artifact_dir(model) -> Path:
    candidates = []
    if model.config_path:
        candidates.append(Path(model.config_path).expanduser())
    if model.model_path:
        candidates.append(Path(model.model_path).expanduser())

    for candidate in candidates:
        if candidate.exists():
            return candidate.parent

    fallback = candidates[0].parent if candidates else None
    if fallback is None or not fallback.exists():
        raise FileNotFoundError("Model artifact directory not found")
    return fallback


def _resolve_export_root_dir(model) -> Path:
    if model.config_path:
        config_path = Path(model.config_path).expanduser()
        if config_path.exists():
            return config_path.parent

    if model.model_path:
        model_path = Path(model.model_path).expanduser()
        if model_path.exists():
            if model_path.parent.name.startswith("fold_"):
                return model_path.parent.parent
            return model_path.parent

    return _resolve_model_artifact_dir(model)


def _safe_relative_path(path: Path, base_dir: Path) -> Path:
    try:
        return path.relative_to(base_dir)
    except ValueError:
        return Path(path.name)


def _collect_export_files(model) -> list[tuple[Path, Path, bool]]:
    if not model.model_path:
        raise FileNotFoundError("Model file not found")

    model_path = Path(model.model_path).expanduser()
    if not model_path.exists() or not model_path.is_file():
        raise FileNotFoundError("Model file not found")

    export_root_dir = _resolve_export_root_dir(model)
    export_files: list[tuple[Path, Path, bool]] = [
        (model_path, _safe_relative_path(model_path, export_root_dir), False),
    ]

    if model.config_path:
        config_path = Path(model.config_path).expanduser()
        if config_path.exists() and config_path.is_file():
            export_files.append(
                (config_path, _safe_relative_path(config_path, export_root_dir), True)
            )

    metrics_path = export_root_dir / "metrics.json"
    if metrics_path.exists() and metrics_path.is_file():
        export_files.append(
            (metrics_path, _safe_relative_path(metrics_path, export_root_dir), False)
        )

    return export_files


def _build_model_export_archive(model, task) -> tuple[str, str]:
    export_root = Path(model.model_id)
    task_type = task.data_group.task_type if task and task.data_group else None
    export_files = _collect_export_files(model)

    manifest = {
        "model_id": model.model_id,
        "task_id": model.task_id,
        "model_name": model.model_name,
        "task_type": task_type,
        "feature_extractor": model.feature_extractor,
        "aggregator": model.aggregator,
        "classes": model.classes,
        "exported_files": [str(relative_path) for _, relative_path, _ in export_files],
    }
    readme = "\n".join(
        [
            "PathLab Model Export",
            "",
            f"Model ID: {model.model_id}",
            f"Training Task ID: {model.task_id}",
            f"Task Type: {task_type or 'unknown'}",
            f"Feature Extractor / Backbone: {model.feature_extractor or 'N/A'}",
            f"Aggregator / Architecture: {model.aggregator or 'N/A'}",
            f"Classes: {', '.join(model.classes or []) if model.classes else 'N/A'}",
            "",
            "This package contains the final model artifacts required for reuse.",
            "Intermediate training checkpoints are intentionally excluded from this export.",
            "Depending on the training pipeline, additional feature extractor or backbone assets may need to be provided separately during deployment.",
        ]
    )

    archive_fd, archive_path = tempfile.mkstemp(
        prefix=f"{model.model_id}_", suffix=".zip"
    )
    os.close(archive_fd)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for file_path, relative_path, should_sanitize in export_files:
            archive_member = export_root / relative_path
            if should_sanitize:
                try:
                    payload = json.loads(file_path.read_text(encoding="utf-8"))
                    sanitized_payload = _sanitize_export_config(payload)
                    archive.writestr(
                        str(archive_member),
                        json.dumps(sanitized_payload, ensure_ascii=False, indent=2),
                    )
                    continue
                except Exception as exc:
                    logger.warning(
                        "Failed to sanitize config for model export %s: %s",
                        model.model_id,
                        exc,
                    )

            archive.write(
                file_path, arcname=str(archive_member), compress_type=zipfile.ZIP_STORED
            )

        archive.writestr(
            str(export_root / "export_manifest.json"),
            json.dumps(manifest, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            str(export_root / "README.txt"),
            readme,
            compress_type=zipfile.ZIP_STORED,
        )

    return archive_path, f"{model.model_id}_export.zip"


@router.get("")
async def list_trained_models(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all trained models. Users see only their own models, admin sees all."""
    user_id_filter = None if user.is_admin() else str(user.id)
    models = await TrainedModelRepository.get_all(
        db, limit, skip, user_id=user_id_filter
    )
    total = await TrainedModelRepository.count(db, user_id=user_id_filter)
    return {"items": [model.to_dict() for model in models], "total": total}


@router.get("/{model_id}")
async def get_trained_model(
    model_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get trained model details. Users can only view their own models, admin can view all."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this model"
        )

    return model.to_dict()


@router.get("/{model_id}/export")
async def export_trained_model(
    model_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a trained model bundle.

    Admin users may export any model. Non-admin users may only export models
    that they trained themselves.
    """
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    if not check_data_ownership(model.user_id, user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to export this model"
        )

    task = await TrainingTaskRepository.get_by_id(db, model.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Training task not found")

    try:
        archive_path, archive_name = await asyncio.to_thread(
            _build_model_export_archive, model, task
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to export model %s for user %s", model_id, user.id)
        raise HTTPException(status_code=500, detail="Failed to export model") from exc

    logger.info(
        "User %s exported model %s from training task %s",
        user.id,
        model.model_id,
        model.task_id,
    )
    return FileResponse(
        archive_path,
        filename=archive_name,
        media_type="application/zip",
        background=BackgroundTask(_cleanup_temp_file, archive_path),
    )


@router.patch("/{model_id}")
async def update_trained_model(
    model_id: str,
    req: ModelUpdateRequest,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update trained model properties (set default, activate/deactivate).
    Requires pathologist or admin role. Users can only update their own models."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to update this model"
        )

    model_owner_id = str(model.user_id or user.id)

    if req.is_default is True:
        model = await TrainedModelRepository.set_default(db, model_id)
        await db.commit()
        await invalidate_chat_context(model_owner_id)
        return model.to_dict()

    if req.is_active is not None:
        model = await TrainedModelRepository.set_active(db, model_id, req.is_active)
        await db.commit()
        await invalidate_chat_context(model_owner_id)
        return model.to_dict()

    return model.to_dict()


@router.delete("/{model_id}")
async def delete_trained_model(
    model_id: str,
    user: User = Depends(require_pathologist_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a trained model. Requires pathologist or admin role.
    Users can only delete their own models, admin can delete any."""
    model = await TrainedModelRepository.get_by_id(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Trained model not found")

    # Check ownership
    if not check_data_ownership(model.user_id, user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to delete this model"
        )

    model_owner_id = str(model.user_id or user.id)
    deleted = await TrainedModelRepository.delete(db, model_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete model")

    await db.commit()
    await invalidate_chat_context(model_owner_id)
    return {"message": "Model deleted successfully", "model_id": model_id}
