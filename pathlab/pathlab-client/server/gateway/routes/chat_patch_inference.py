"""Temporary chat-only patch inference helpers."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from backend.common.config import Config
from backend.database import safe_session
from backend.database.repositories import TrainedModelRepository, TrainingTaskRepository
from backend.ai.utils.patch_resize import (
    DEFAULT_NON_FM_PATCH_RESIZE,
    build_patch_classification_transform,
    resolve_patch_resize_size,
)

from ..task_queue import TaskType, get_task_queue


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatPatchTask:
    task_id: str
    conversation_id: str
    message_id: int
    user_id: str
    inference_type: str
    model_id: str
    model_name: str
    image_path: str
    source: Optional[str] = None
    status: str = "queued"
    progress: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "inference_type": self.inference_type,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "source": self.source,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_TASKS: dict[str, ChatPatchTask] = {}
_CONVERSATION_INDEX: dict[str, set[str]] = {}
_TASK_LOCK = asyncio.Lock()


async def get_chat_patch_task(task_id: str) -> Optional[ChatPatchTask]:
    async with _TASK_LOCK:
        return _TASKS.get(task_id)


async def create_chat_patch_task(
    *,
    conversation_id: str,
    message_id: int,
    user_id: str,
    inference_type: str,
    model_id: str,
    model_name: str,
    image_data_url: str,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    task_queue = get_task_queue()
    if not task_queue:
        raise RuntimeError("Task queue is not initialized")

    task_id = f"chat_patch_{uuid.uuid4().hex}"
    task_dir = Config.get_uploads_dir() / "chat_patch_inference" / conversation_id / task_id
    image_path = await asyncio.to_thread(_persist_image_data_url, image_data_url, task_dir)

    task = ChatPatchTask(
        task_id=task_id,
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=user_id,
        inference_type=inference_type,
        model_id=model_id,
        model_name=model_name,
        image_path=str(image_path),
        source=source,
    )

    async with _TASK_LOCK:
        _TASKS[task_id] = task
        _CONVERSATION_INDEX.setdefault(conversation_id, set()).add(task_id)

    await task_queue.submit(task_id, TaskType.ANALYSIS, _run_chat_patch_task)
    return task.to_public_dict()


async def cleanup_conversation_chat_patch_tasks(conversation_id: str) -> None:
    task_queue = get_task_queue()
    async with _TASK_LOCK:
        task_ids = list(_CONVERSATION_INDEX.get(conversation_id, set()))

    for task_id in task_ids:
        if task_queue and task_queue.is_task_in_queue(task_id):
            await task_queue.cancel_task(task_id)

    async with _TASK_LOCK:
        for task_id in task_ids:
            task = _TASKS.pop(task_id, None)
            if task:
                await asyncio.to_thread(_cleanup_task_files, task)
        _CONVERSATION_INDEX.pop(conversation_id, None)


async def cleanup_chat_patch_tasks_from_message(
    conversation_id: str,
    message_id: int,
) -> None:
    task_queue = get_task_queue()
    async with _TASK_LOCK:
        task_ids = [
            task_id
            for task_id in _CONVERSATION_INDEX.get(conversation_id, set())
            if (task := _TASKS.get(task_id)) and task.message_id >= message_id
        ]

    for task_id in task_ids:
        if task_queue and task_queue.is_task_in_queue(task_id):
            await task_queue.cancel_task(task_id)

    async with _TASK_LOCK:
        for task_id in task_ids:
            task = _TASKS.pop(task_id, None)
            if task:
                await asyncio.to_thread(_cleanup_task_files, task)
        remaining = _CONVERSATION_INDEX.get(conversation_id)
        if remaining is not None:
            remaining.difference_update(task_ids)
            if not remaining:
                _CONVERSATION_INDEX.pop(conversation_id, None)


async def cancel_chat_patch_tasks_for_message(
    conversation_id: str,
    message_id: int,
) -> list[Dict[str, Any]]:
    """Cancel active chat patch tasks for one assistant message and return final task snapshots."""
    task_queue = get_task_queue()
    async with _TASK_LOCK:
        task_ids = [
            task_id
            for task_id in _CONVERSATION_INDEX.get(conversation_id, set())
            if (task := _TASKS.get(task_id)) and task.message_id == message_id
        ]
        snapshots: list[Dict[str, Any]] = []
        for task_id in task_ids:
            task = _TASKS.get(task_id)
            if not task:
                continue
            snapshot = task.to_public_dict()
            if snapshot["status"] not in {"completed", "failed", "cancelled"}:
                snapshot["status"] = "cancelled"
                snapshot["progress"] = 100
                snapshot["error"] = "Task cancelled"
                snapshot["updated_at"] = _utcnow_iso()
            snapshots.append(snapshot)

    for task_id in task_ids:
        if task_queue and task_queue.is_task_in_queue(task_id):
            await task_queue.cancel_task(task_id)

    async with _TASK_LOCK:
        for task_id in task_ids:
            task = _TASKS.pop(task_id, None)
            if task:
                if task.status not in {"completed", "failed", "cancelled"}:
                    task.status = "cancelled"
                    task.progress = 100
                    task.error = "Task cancelled"
                    task.updated_at = _utcnow_iso()
                await asyncio.to_thread(_cleanup_task_files, task)
        remaining = _CONVERSATION_INDEX.get(conversation_id)
        if remaining is not None:
            remaining.difference_update(task_ids)
            if not remaining:
                _CONVERSATION_INDEX.pop(conversation_id, None)

    return snapshots


async def _run_chat_patch_task(task_id: str, assigned_device: Optional[str] = None) -> None:
    await _update_task(task_id, status="running", progress=5, error=None)
    try:
        task = await get_chat_patch_task(task_id)
        if not task:
            return

        if task.inference_type == "classification":
            result = await _run_patch_classification(task, assigned_device)
        elif task.inference_type == "segmentation":
            result = await _run_patch_segmentation(task, assigned_device)
        else:
            raise ValueError(f"Unsupported inference type: {task.inference_type}")

        await _update_task(task_id, status="completed", progress=100, result=result, error=None)
    except asyncio.CancelledError:
        await _update_task(task_id, status="cancelled", error="Task cancelled")
        raise
    except Exception as exc:
        await _update_task(task_id, status="failed", progress=100, error=str(exc))


async def _update_task(task_id: str, **changes: Any) -> None:
    async with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        for key, value in changes.items():
            setattr(task, key, value)
        task.updated_at = _utcnow_iso()


def _persist_image_data_url(image_data_url: str, task_dir: Path) -> Path:
    if not image_data_url.startswith("data:image/"):
        raise ValueError("Only image data URLs are supported")
    try:
        _, payload = image_data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Invalid image data URL") from exc

    try:
        raw = base64.b64decode(payload)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Failed to decode image payload") from exc

    task_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(BytesIO(raw)).convert("RGB")
    image_path = task_dir / "input.png"
    image.save(image_path)
    return image_path


def _cleanup_task_files(task: ChatPatchTask) -> None:
    task_root = Path(task.image_path).parent
    if task_root.exists():
        shutil.rmtree(task_root, ignore_errors=True)


async def _run_patch_classification(task: ChatPatchTask, assigned_device: Optional[str]) -> Dict[str, Any]:
    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from backend.ai.extractors import get_extractor

    device = assigned_device or ("cuda" if torch.cuda.is_available() else "cpu")

    async with safe_session() as db:
        trained_model = await TrainedModelRepository.get_by_id(db, task.model_id)
        if not trained_model:
            raise ValueError(f"Trained model not found: {task.model_id}")

    model_dir = Config.get_uploads_dir() / "models" / task.model_id
    config_path = model_dir / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    classes = trained_model.classes or config.get("classes", [])
    if not classes:
        raise ValueError("Could not determine model classes")

    is_kfold = config.get("split_type") == "kfold"
    num_folds = int(config.get("num_folds", 5)) if is_kfold else 1

    def _load_models():
        extractor_name = config.get("extractor") or trained_model.feature_extractor or "resnet50"
        linear_probes = []

        if is_kfold:
            for fold_idx in range(num_folds):
                ckpt_path = model_dir / f"fold_{fold_idx}" / "linear_probe.pth"
                checkpoint = torch.load(ckpt_path, map_location=device)
                feature_dim = checkpoint.get("feature_dim") or checkpoint.get("extractor_dim")
                probe = nn.Linear(feature_dim, checkpoint["num_classes"]).to(device)
                probe.load_state_dict(checkpoint["state_dict"])
                probe.eval()
                linear_probes.append(probe)
        else:
            ckpt_path = model_dir / "linear_probe.pth"
            checkpoint = torch.load(ckpt_path, map_location=device)
            extractor_name = checkpoint.get("extractor_name", extractor_name)
            feature_dim = checkpoint.get("extractor_dim") or checkpoint.get("feature_dim")
            probe = nn.Linear(feature_dim, checkpoint["num_classes"]).to(device)
            probe.load_state_dict(checkpoint["state_dict"])
            probe.eval()
            linear_probes.append(probe)

        extractor = get_extractor(extractor_name, pretrained=True).to(device)
        extractor.eval()
        resize_size = resolve_patch_resize_size(extractor_name)
        return extractor, linear_probes, resize_size

    extractor, linear_probes, resize_size = await asyncio.to_thread(_load_models)
    await _update_task(task.task_id, progress=35)

    def _infer_single_image() -> Dict[str, Any]:
        image = Image.open(task.image_path).convert("RGB")
        image_tensor = build_patch_classification_transform(extractor, resize_size)(image).unsqueeze(0).to(device)
        with torch.inference_mode():
            features = extractor(image_tensor)
            logits_list = [probe(features) for probe in linear_probes]
            logits = torch.mean(torch.stack(logits_list), dim=0)
            probs = F.softmax(logits, dim=-1).squeeze(0).detach().cpu().numpy()

        top_indices = np.argsort(probs)[::-1][: min(3, len(classes))]
        probabilities = {classes[idx]: round(float(probs[idx]), 4) for idx in range(len(classes))}
        return {
            "predicted_label": classes[int(np.argmax(probs))],
            "probabilities": probabilities,
            "top_predictions": [
                {"label": classes[int(idx)], "score": round(float(probs[int(idx)]), 4)}
                for idx in top_indices
            ],
            "classes": classes,
        }

    result = await asyncio.to_thread(_infer_single_image)
    await _update_task(task.task_id, progress=90)
    return result


async def _run_patch_segmentation(task: ChatPatchTask, assigned_device: Optional[str]) -> Dict[str, Any]:
    import torch
    from torchvision.transforms import v2
    from backend.ai.segmentors import Segmentor

    device = assigned_device or ("cuda" if torch.cuda.is_available() else "cpu")

    async with safe_session() as db:
        trained_model = await TrainedModelRepository.get_by_id(db, task.model_id)
        if not trained_model:
            raise ValueError(f"Trained model not found: {task.model_id}")
        training_task = await TrainingTaskRepository.get_by_id(db, trained_model.task_id)

    checkpoint_path = trained_model.model_path

    def _load_model():
        from backend.ai.segmentors.specs import is_fm_segmentation_backbone

        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        checkpoint_config = checkpoint.get("config", {})
        task_model_cfg = (training_task.model_config or {}) if training_task else {}
        dataset_cfg = checkpoint_config.get("dataset", {})

        architecture = checkpoint_config.get("architecture") or task_model_cfg.get("architecture") or "unet"
        backbone = checkpoint_config.get("backbone") or task_model_cfg.get("backbone") or trained_model.feature_extractor or "resnet50"
        in_channels = int(dataset_cfg.get("channels", 3))
        num_classes = int(dataset_cfg.get("classes") or len(trained_model.classes or []) or 1)

        segmentor = Segmentor(
            architecture=architecture,
            encoder_name=backbone,
            in_channels=in_channels,
            classes=num_classes,
        )
        model = segmentor.build_model()
        if checkpoint.get("is_fm", False):
            model.load_decoder_state_dict(checkpoint["model_state_dict"])
        else:
            model.load_state_dict(checkpoint["model_state_dict"])
        model = model.to(device)
        model.eval()
        norm_mean, norm_std = segmentor.get_normalization_params()
        resize_size = resolve_patch_resize_size(backbone, is_segmentation_backbone=True)

        class_names = _normalize_labels(
            (training_task.classes if training_task else None)
            or trained_model.classes
            or dataset_cfg.get("class_names")
            or []
        )
        if not class_names:
            class_names = [f"Class {idx + 1}" for idx in range(num_classes)]
        return model, norm_mean, norm_std, class_names, resize_size

    model, norm_mean, norm_std, class_names, resize_size = await asyncio.to_thread(_load_model)
    await _update_task(task.task_id, progress=35)

    def _infer_single_image() -> Dict[str, Any]:
        image = Image.open(task.image_path).convert("RGB")
        image_tensor = v2.ToImage()(image)
        image_tensor = v2.ToDtype(torch.float32, scale=True)(image_tensor)
        image_tensor = v2.Resize((resize_size, resize_size), antialias=True)(image_tensor)
        image_tensor = v2.Normalize(
            mean=norm_mean or [0.485, 0.456, 0.406],
            std=norm_std or [0.229, 0.224, 0.225],
        )(image_tensor)
        image_tensor = image_tensor.unsqueeze(0).to(device)

        with torch.no_grad():
            logits = model(image_tensor)
            probabilities = torch.sigmoid(logits).squeeze(0).detach().cpu()
            binary_mask = (probabilities > 0.5).to(torch.uint8)

        coverage_ratios = [round(float(binary_mask[idx].float().mean().item()), 4) for idx in range(binary_mask.shape[0])]
        positive_classes = [
            {"label": class_names[idx], "coverage_ratio": coverage_ratios[idx]}
            for idx in range(min(len(class_names), len(coverage_ratios)))
            if coverage_ratios[idx] > 0
        ]

        return {
            "class_names": class_names,
            "positive_classes": positive_classes,
            "coverage_by_class": [
                {"label": class_names[idx], "coverage_ratio": coverage_ratios[idx]}
                for idx in range(min(len(class_names), len(coverage_ratios)))
            ],
            "has_positive_mask": any(item["coverage_ratio"] > 0 for item in positive_classes),
            "mask_shape": [int(binary_mask.shape[-2]), int(binary_mask.shape[-1])],
        }

    result = await asyncio.to_thread(_infer_single_image)
    await _update_task(task.task_id, progress=90)
    return result


def _normalize_labels(labels: Any) -> list[str]:
    normalized = []
    seen = set()
    for label in labels or []:
        value = str(label).strip()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized