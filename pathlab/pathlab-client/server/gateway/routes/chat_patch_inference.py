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
from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image
from fastapi import HTTPException

Config = import_module("backend.common.config").Config
safe_session = import_module("backend.database").safe_session
_repositories = import_module("backend.database.repositories")
TrainedModelRepository = _repositories.TrainedModelRepository
TrainingTaskRepository = _repositories.TrainingTaskRepository
_patch_resize = import_module("backend.ai.utils.patch_resize")
DEFAULT_NON_FM_PATCH_RESIZE = _patch_resize.DEFAULT_NON_FM_PATCH_RESIZE
build_patch_classification_transform = (
    _patch_resize.build_patch_classification_transform
)
resolve_patch_resize_size = _patch_resize.resolve_patch_resize_size

from ..task_dispatch import (
    JsonPayload,
    build_task_descriptor,
    enqueue_task_descriptor,
    is_worker_healthy,
    publish_task_cancellation,
)

_redis_client = import_module("backend.common.redis_client")
get_redis = _redis_client.get_redis
make_key = _redis_client.make_key

_SNAPSHOT_TTL_SECONDS = 3600


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
    snapshot = await _get_task_snapshot(task_id)
    async with _TASK_LOCK:
        local_task = _TASKS.get(task_id)

    if snapshot is None:
        return local_task

    snapshot_task = _task_from_snapshot(snapshot)
    if local_task is not None and not _is_snapshot_newer(
        snapshot_task.updated_at, local_task.updated_at
    ):
        return local_task

    async with _TASK_LOCK:
        _TASKS[task_id] = snapshot_task
        _CONVERSATION_INDEX.setdefault(snapshot_task.conversation_id, set()).add(task_id)
    return snapshot_task


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
    if not await is_worker_healthy():
        raise HTTPException(status_code=503, detail="Task worker unavailable")

    task_id = f"chat_patch_{uuid.uuid4().hex}"
    task_dir = (
        Config.get_uploads_dir() / "chat_patch_inference" / conversation_id / task_id
    )
    image_path = await asyncio.to_thread(
        _persist_image_data_url, image_data_url, task_dir
    )

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
    await _set_task_snapshot(task_id, _task_to_snapshot(task))

    descriptor_payload = _build_chat_patch_descriptor_payload(task)
    descriptor = build_task_descriptor(
        job_id=task_id,
        job_kind="chat",
        handler="chat.patch_inference",
        payload=descriptor_payload,
    )
    try:
        await enqueue_task_descriptor(descriptor)
    except Exception:
        await _update_task(
            task_id,
            status="failed",
            progress=100,
            error="Failed to enqueue chat patch inference task",
        )
        await asyncio.to_thread(_cleanup_task_files, task)
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue chat patch inference task",
        )

    return task.to_public_dict()


async def cleanup_conversation_chat_patch_tasks(conversation_id: str) -> None:
    async with _TASK_LOCK:
        task_ids = list(_CONVERSATION_INDEX.get(conversation_id, set()))

    for task_id in task_ids:
        await publish_task_cancellation(task_id)

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
    async with _TASK_LOCK:
        task_ids = [
            task_id
            for task_id in _CONVERSATION_INDEX.get(conversation_id, set())
            if (task := _TASKS.get(task_id)) and task.message_id >= message_id
        ]

    for task_id in task_ids:
        await publish_task_cancellation(task_id)

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
        await publish_task_cancellation(task_id)

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


async def _run_chat_patch_task(
    task_id: str, assigned_device: Optional[str] = None
) -> None:
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

        await _update_task(
            task_id, status="completed", progress=100, result=result, error=None
        )
    except asyncio.CancelledError:
        await _update_task(task_id, status="cancelled", error="Task cancelled")
        raise
    except Exception as exc:
        await _update_task(task_id, status="failed", progress=100, error=str(exc))


async def _update_task(task_id: str, **changes: Any) -> None:
    snapshot: dict[str, Any]
    async with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if not task:
            return
        for key, value in changes.items():
            setattr(task, key, value)
        task.updated_at = _utcnow_iso()
        snapshot = _task_to_snapshot(task)
    await _set_task_snapshot(task_id, snapshot)


def _task_to_snapshot(task: ChatPatchTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "conversation_id": task.conversation_id,
        "message_id": task.message_id,
        "user_id": task.user_id,
        "inference_type": task.inference_type,
        "model_id": task.model_id,
        "model_name": task.model_name,
        "image_path": task.image_path,
        "source": task.source,
        "status": task.status,
        "progress": task.progress,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _task_from_snapshot(snapshot: Dict[str, Any]) -> ChatPatchTask:
    return ChatPatchTask(
        task_id=str(snapshot["task_id"]),
        conversation_id=str(snapshot["conversation_id"]),
        message_id=int(snapshot["message_id"]),
        user_id=str(snapshot["user_id"]),
        inference_type=str(snapshot["inference_type"]),
        model_id=str(snapshot["model_id"]),
        model_name=str(snapshot["model_name"]),
        image_path=str(snapshot["image_path"]),
        source=snapshot.get("source"),
        status=str(snapshot.get("status") or "queued"),
        progress=int(snapshot.get("progress") or 0),
        result=snapshot.get("result"),
        error=snapshot.get("error"),
        created_at=str(snapshot.get("created_at") or _utcnow_iso()),
        updated_at=str(snapshot.get("updated_at") or _utcnow_iso()),
    )


def _is_snapshot_newer(snapshot_updated_at: str, local_updated_at: str) -> bool:
    return _parse_task_timestamp(snapshot_updated_at) > _parse_task_timestamp(
        local_updated_at
    )


def _parse_task_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _build_chat_patch_descriptor_payload(task: ChatPatchTask) -> JsonPayload:
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "conversation_id": task.conversation_id,
        "message_id": task.message_id,
        "user_id": task.user_id,
        "inference_type": task.inference_type,
        "model_id": task.model_id,
        "model_name": task.model_name,
        "image_path": task.image_path,
        "source": task.source,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "runner_module": "gateway.routes.chat_patch_inference",
        "runner_name": "_run_chat_patch_task",
        "runner_kwargs": {"task_id": task.task_id},
    }
    return payload


async def _set_task_snapshot(task_id: str, snapshot: dict[str, Any]) -> None:
    try:
        r = get_redis()
        key = make_key("chat_patch_task", task_id)
        await r.set(key, json.dumps(snapshot), ex=_SNAPSHOT_TTL_SECONDS)
    except Exception:
        pass


async def _get_task_snapshot(task_id: str) -> Optional[dict[str, Any]]:
    try:
        r = get_redis()
        key = make_key("chat_patch_task", task_id)
        raw = await r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


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
    chat_patch_root = Config.get_uploads_dir() / "chat_patch_inference"
    try:
        task_root.resolve().relative_to(chat_patch_root.resolve())
    except ValueError:
        return
    if task_root.exists():
        shutil.rmtree(task_root, ignore_errors=True)


async def _run_patch_classification(
    task: ChatPatchTask, assigned_device: Optional[str]
) -> Dict[str, Any]:
    import numpy as np
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    get_extractor = import_module("backend.ai.extractors").get_extractor

    device = assigned_device or ("cuda" if torch.cuda.is_available() else "cpu")

    async with safe_session() as db:
        trained_model = await TrainedModelRepository.get_by_id(db, task.model_id)
        if not trained_model:
            raise ValueError(f"Trained model not found: {task.model_id}")

    model_dir = Config.get_uploads_dir() / "models" / task.model_id
    config_path = model_dir / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    trained_classes = (
        trained_model.classes if isinstance(trained_model.classes, list) else []
    )
    config_classes = config.get("classes", [])
    classes = (
        list(trained_classes)
        if trained_classes
        else list(config_classes if isinstance(config_classes, list) else [])
    )
    if not classes:
        raise ValueError("Could not determine model classes")

    is_kfold = config.get("split_type") == "kfold"
    num_folds = int(config.get("num_folds", 5)) if is_kfold else 1

    def _load_models():
        extractor_name = str(
            config.get("extractor") or trained_model.feature_extractor or "resnet50"
        )
        linear_probes = []

        if is_kfold:
            for fold_idx in range(num_folds):
                ckpt_path = model_dir / f"fold_{fold_idx}" / "linear_probe.pth"
                checkpoint = torch.load(ckpt_path, map_location=device)
                feature_dim = checkpoint.get("feature_dim") or checkpoint.get(
                    "extractor_dim"
                )
                probe = nn.Linear(feature_dim, checkpoint["num_classes"]).to(device)
                probe.load_state_dict(checkpoint["state_dict"])
                probe.eval()
                linear_probes.append(probe)
        else:
            ckpt_path = model_dir / "linear_probe.pth"
            checkpoint = torch.load(ckpt_path, map_location=device)
            extractor_name = checkpoint.get("extractor_name", extractor_name)
            feature_dim = checkpoint.get("extractor_dim") or checkpoint.get(
                "feature_dim"
            )
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
        patch_image = Image.open(task.image_path).convert("RGB")
        image_tensor = (
            build_patch_classification_transform(extractor, resize_size)(patch_image)
            .unsqueeze(0)
            .to(device)
        )
        with torch.inference_mode():
            features = extractor(image_tensor)
            logits_list = [probe(features) for probe in linear_probes]
            logits = torch.mean(torch.stack(logits_list), dim=0)
            probs = F.softmax(logits, dim=-1).squeeze(0).detach().cpu().numpy()

        top_indices = np.argsort(probs)[::-1][: min(3, len(classes))]
        probabilities = {
            classes[idx]: round(float(probs[idx]), 4) for idx in range(len(classes))
        }
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


async def _run_patch_segmentation(
    task: ChatPatchTask, assigned_device: Optional[str]
) -> Dict[str, Any]:
    import torch
    from torchvision.transforms import v2

    Segmentor = import_module("backend.ai.segmentors").Segmentor

    device = assigned_device or ("cuda" if torch.cuda.is_available() else "cpu")

    async with safe_session() as db:
        trained_model = await TrainedModelRepository.get_by_id(db, task.model_id)
        if not trained_model:
            raise ValueError(f"Trained model not found: {task.model_id}")
        training_task = await TrainingTaskRepository.get_by_id(
            db, str(trained_model.task_id)
        )

    checkpoint_path = str(trained_model.model_path)

    def _load_model():
        is_fm_segmentation_backbone = import_module(
            "backend.ai.segmentors.specs"
        ).is_fm_segmentation_backbone

        checkpoint = torch.load(
            checkpoint_path, map_location=device, weights_only=False
        )
        checkpoint_config = checkpoint.get("config", {})
        if not isinstance(checkpoint_config, dict):
            checkpoint_config = {}
        task_model_cfg = (
            training_task.model_config
            if training_task and isinstance(training_task.model_config, dict)
            else {}
        )
        dataset_cfg = checkpoint_config.get("dataset", {})
        if not isinstance(dataset_cfg, dict):
            dataset_cfg = {}

        architecture = (
            checkpoint_config.get("architecture")
            or task_model_cfg.get("architecture")
            or "unet"
        )
        backbone = str(
            checkpoint_config.get("backbone")
            or task_model_cfg.get("backbone")
            or trained_model.feature_extractor
            or "resnet50"
        )
        in_channels = int(dataset_cfg.get("channels", 3))
        trained_model_classes = (
            trained_model.classes if isinstance(trained_model.classes, list) else []
        )
        num_classes = int(dataset_cfg.get("classes") or len(trained_model_classes) or 1)

        segmentor = Segmentor(
            architecture=architecture,
            encoder_name=backbone,
            in_channels=in_channels,
            classes=num_classes,
        )
        built_model = segmentor.build_model()
        if checkpoint.get("is_fm", False):
            built_model.load_decoder_state_dict(checkpoint["model_state_dict"])
        else:
            built_model.load_state_dict(checkpoint["model_state_dict"])
        model = built_model.to(device)
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

    model, norm_mean, norm_std, class_names, resize_size = await asyncio.to_thread(
        _load_model
    )
    await _update_task(task.task_id, progress=35)

    def _infer_single_image() -> Dict[str, Any]:
        import numpy as np

        image = Image.open(task.image_path).convert("RGB")
        image_tensor = v2.ToImage()(image)
        image_tensor = v2.ToDtype(torch.float32, scale=True)(image_tensor)
        image_tensor = v2.Resize((resize_size, resize_size), antialias=True)(
            image_tensor
        )
        image_tensor = v2.Normalize(
            mean=norm_mean or [0.485, 0.456, 0.406],
            std=norm_std or [0.229, 0.224, 0.225],
        )(image_tensor)
        image_tensor = image_tensor.unsqueeze(0).to(device)

        with torch.no_grad():
            logits = model(image_tensor)
            probabilities = torch.sigmoid(logits).squeeze(0).detach().cpu()
            binary_mask = (probabilities > 0.5).to(torch.uint8)

        coverage_ratios = [
            round(float(binary_mask[idx].float().mean().item()), 4)
            for idx in range(binary_mask.shape[0])
        ]
        has_positive_mask = any(float(ratio) > 0.0 for ratio in coverage_ratios)
        positive_classes: list[dict[str, object]] = [
            {"label": class_names[idx], "coverage_ratio": float(coverage_ratios[idx])}
            for idx in range(min(len(class_names), len(coverage_ratios)))
            if float(coverage_ratios[idx]) > 0.0
        ]

        # Build overlay image: original image resized to mask resolution, with
        # semi-transparent per-class colour blended on top.
        num_vis_classes = binary_mask.shape[0]
        _PALETTE = [
            (255, 100, 100),
            (100, 200, 255),
            (120, 255, 120),
            (255, 220, 80),
            (200, 100, 255),
            (255, 160, 50),
            (80, 255, 220),
            (255, 80, 200),
        ]
        mask_h, mask_w = int(binary_mask.shape[-2]), int(binary_mask.shape[-1])
        base_img = image.resize((mask_w, mask_h), Image.Resampling.LANCZOS)
        base_arr = np.array(base_img, dtype=np.float32)
        overlay = base_arr.copy()

        for idx in range(num_vis_classes):
            colour = _PALETTE[idx % len(_PALETTE)]
            m = binary_mask[idx].numpy().astype(bool)
            if not m.any():
                continue
            colour_layer = np.zeros_like(base_arr)
            colour_layer[m] = colour
            overlay[m] = base_arr[m] * 0.5 + colour_layer[m] * 0.5

        overlay_img = Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8))
        buf = BytesIO()
        overlay_img.save(buf, format="PNG", optimize=True)
        overlay_b64 = "data:image/png;base64," + base64.b64encode(
            buf.getvalue()
        ).decode("ascii")

        return {
            "class_names": class_names,
            "positive_classes": positive_classes,
            "coverage_by_class": [
                {
                    "label": class_names[idx],
                    "coverage_ratio": float(coverage_ratios[idx]),
                }
                for idx in range(min(len(class_names), len(coverage_ratios)))
            ],
            "has_positive_mask": has_positive_mask,
            "mask_shape": [mask_h, mask_w],
            "overlay_image_data_url": overlay_b64,
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
