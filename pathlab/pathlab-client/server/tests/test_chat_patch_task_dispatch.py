from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def _reset_chat_patch_state():
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])
    mod._TASKS.clear()
    mod._CONVERSATION_INDEX.clear()
    yield
    mod._TASKS.clear()
    mod._CONVERSATION_INDEX.clear()


@pytest.mark.asyncio
async def test_create_chat_patch_task_rejects_unhealthy_worker_before_persist(monkeypatch, tmp_path):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(mod.Config, "get_uploads_dir", lambda: uploads_dir)
    persist_mock = AsyncMock(side_effect=RuntimeError("must not persist image"))
    monkeypatch.setattr(mod.asyncio, "to_thread", persist_mock)
    monkeypatch.setattr(mod, "is_worker_healthy", AsyncMock(return_value=False))

    with pytest.raises(HTTPException, match="Task worker unavailable") as exc_info:
        await mod.create_chat_patch_task(
            conversation_id="conv_1",
            message_id=7,
            user_id="user_1",
            inference_type="classification",
            model_id="model_1",
            model_name="Model One",
            image_data_url="data:image/png;base64,AAA",
            source="llm",
        )

    assert exc_info.value.status_code == 503
    persist_mock.assert_not_awaited()
    assert not (uploads_dir / "chat_patch_inference").exists()
    assert mod._TASKS == {}


@pytest.mark.asyncio
async def test_create_chat_patch_task_enqueues_descriptor_and_registers_local_state(monkeypatch, tmp_path):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    uploads_dir = tmp_path / "uploads"
    image_path = uploads_dir / "chat_patch_inference" / "conv_1" / "task" / "input.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"img")

    monkeypatch.setattr(mod.Config, "get_uploads_dir", lambda: uploads_dir)
    monkeypatch.setattr(mod, "is_worker_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(mod.asyncio, "to_thread", AsyncMock(return_value=image_path))

    captured = {}

    async def _capture_enqueue(descriptor):
        captured["descriptor"] = descriptor

    mirror_mock = AsyncMock()
    monkeypatch.setattr(mod, "enqueue_task_descriptor", AsyncMock(side_effect=_capture_enqueue))
    monkeypatch.setattr(mod, "_set_task_snapshot", mirror_mock)

    result = await mod.create_chat_patch_task(
        conversation_id="conv_1",
        message_id=7,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_data_url="data:image/png;base64,AAA",
        source="llm",
    )

    task_id = result["task_id"]
    task = await mod.get_chat_patch_task(task_id)
    assert task is not None
    assert task.status == "queued"
    assert task.image_path == str(image_path)
    assert captured["descriptor"].handler == "chat.patch_inference"
    payload = captured["descriptor"].payload
    assert payload["task_id"] == task_id
    assert payload["conversation_id"] == "conv_1"
    assert payload["message_id"] == 7
    assert payload["user_id"] == "user_1"
    assert payload["inference_type"] == "classification"
    assert payload["model_id"] == "model_1"
    assert payload["model_name"] == "Model One"
    assert payload["image_path"] == str(image_path)
    assert payload["source"] == "llm"
    assert payload["runner_module"] == "gateway.routes.chat_patch_inference"
    assert payload["runner_name"] == "_run_chat_patch_task"
    assert payload["runner_kwargs"] == {"task_id": task_id}
    mirror_mock.assert_awaited()


@pytest.mark.asyncio
async def test_create_chat_patch_task_marks_failed_when_enqueue_fails(monkeypatch, tmp_path):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    uploads_dir = tmp_path / "uploads"
    image_path = uploads_dir / "chat_patch_inference" / "conv_1" / "task" / "input.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"img")

    monkeypatch.setattr(mod.Config, "get_uploads_dir", lambda: uploads_dir)
    monkeypatch.setattr(mod, "is_worker_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(mod.asyncio, "to_thread", AsyncMock(return_value=image_path))
    monkeypatch.setattr(mod, "enqueue_task_descriptor", AsyncMock(side_effect=RuntimeError("redis down")))
    mirror_mock = AsyncMock()
    monkeypatch.setattr(mod, "_set_task_snapshot", mirror_mock)

    with pytest.raises(HTTPException, match="Failed to enqueue chat patch inference task") as exc_info:
        await mod.create_chat_patch_task(
            conversation_id="conv_1",
            message_id=7,
            user_id="user_1",
            inference_type="classification",
            model_id="model_1",
            model_name="Model One",
            image_data_url="data:image/png;base64,AAA",
            source="llm",
        )

    assert exc_info.value.status_code == 503
    task_id = next(iter(mod._TASKS))
    task = await mod.get_chat_patch_task(task_id)
    assert task is not None
    assert task.status == "failed"
    assert task.progress == 100
    assert task.error == "Failed to enqueue chat patch inference task"
    mirror_mock.assert_awaited()


@pytest.mark.asyncio
async def test_create_chat_patch_task_enqueue_failure_cleans_up_task_directory(monkeypatch, tmp_path):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    uploads_dir = tmp_path / "uploads"
    task_dir = uploads_dir / "chat_patch_inference" / "conv_1" / "task"
    image_path = task_dir / "input.png"
    task_dir.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"img")

    monkeypatch.setattr(mod.Config, "get_uploads_dir", lambda: uploads_dir)
    monkeypatch.setattr(mod, "is_worker_healthy", AsyncMock(return_value=True))
    async def _fake_to_thread(fn, *args, **kwargs):
        if fn is mod._persist_image_data_url:
            return image_path
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(mod, "enqueue_task_descriptor", AsyncMock(side_effect=RuntimeError("redis down")))
    monkeypatch.setattr(mod, "_set_task_snapshot", AsyncMock())

    with pytest.raises(HTTPException, match="Failed to enqueue chat patch inference task"):
        await mod.create_chat_patch_task(
            conversation_id="conv_1",
            message_id=7,
            user_id="user_1",
            inference_type="classification",
            model_id="model_1",
            model_name="Model One",
            image_data_url="data:image/png;base64,AAA",
            source="llm",
        )

    assert not task_dir.exists()


def test_cleanup_task_files_ignores_paths_outside_chat_patch_upload_root(monkeypatch, tmp_path):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    uploads_dir = tmp_path / "uploads"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    image_path = outside_root / "input.png"
    image_path.write_bytes(b"img")

    monkeypatch.setattr(mod.Config, "get_uploads_dir", lambda: uploads_dir)

    task = mod.ChatPatchTask(
        task_id="chat_unsafe_cleanup",
        conversation_id="conv_1",
        message_id=7,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path=str(image_path),
    )

    mod._cleanup_task_files(task)

    assert outside_root.exists()
    assert image_path.exists()


@pytest.mark.asyncio
async def test_get_chat_patch_task_prefers_shared_snapshot(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    local_task = mod.ChatPatchTask(
        task_id="chat_patch_1",
        conversation_id="conv_1",
        message_id=7,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
        updated_at="2026-05-01T12:00:00+00:00",
    )
    mod._TASKS[local_task.task_id] = local_task

    monkeypatch.setattr(
        mod,
        "_get_task_snapshot",
        AsyncMock(
            return_value={
                "task_id": local_task.task_id,
                "conversation_id": local_task.conversation_id,
                "message_id": local_task.message_id,
                "user_id": local_task.user_id,
                "inference_type": local_task.inference_type,
                "model_id": local_task.model_id,
                "model_name": local_task.model_name,
                "image_path": local_task.image_path,
                "source": local_task.source,
                "status": "completed",
                "progress": 100,
                "result": {"pred": "tumor"},
                "error": None,
                "created_at": local_task.created_at,
                "updated_at": "2026-05-01T12:00:01+00:00",
            }
        ),
    )

    hydrated = await mod.get_chat_patch_task(local_task.task_id)
    assert hydrated is not None
    assert hydrated.status == "completed"
    assert hydrated.progress == 100
    assert hydrated.result == {"pred": "tumor"}


@pytest.mark.asyncio
async def test_get_chat_patch_task_restores_from_snapshot_when_local_state_is_empty(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    task_id = "chat_patch_redis_only"
    snapshot = {
        "task_id": task_id,
        "conversation_id": "conv_from_snapshot",
        "message_id": 11,
        "user_id": "user_1",
        "inference_type": "classification",
        "model_id": "model_1",
        "model_name": "Model One",
        "image_path": "/tmp/input.png",
        "source": "llm",
        "status": "running",
        "progress": 55,
        "result": None,
        "error": None,
        "created_at": "2026-05-01T12:00:00+00:00",
        "updated_at": "2026-05-01T12:00:01+00:00",
    }

    monkeypatch.setattr(mod, "_get_task_snapshot", AsyncMock(return_value=snapshot))

    restored = await mod.get_chat_patch_task(task_id)
    assert restored is not None
    assert restored.task_id == task_id
    assert restored.conversation_id == "conv_from_snapshot"
    assert restored.status == "running"
    assert restored.progress == 55
    assert task_id in mod._TASKS
    assert task_id in mod._CONVERSATION_INDEX["conv_from_snapshot"]


@pytest.mark.asyncio
async def test_get_chat_patch_task_keeps_fresher_local_state_when_snapshot_is_stale(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    local_task = mod.ChatPatchTask(
        task_id="chat_patch_1",
        conversation_id="conv_1",
        message_id=7,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
        status="running",
        progress=70,
        updated_at="2026-05-01T12:00:00+00:00",
    )
    mod._TASKS[local_task.task_id] = local_task

    monkeypatch.setattr(
        mod,
        "_get_task_snapshot",
        AsyncMock(
            return_value={
                "task_id": local_task.task_id,
                "conversation_id": local_task.conversation_id,
                "message_id": local_task.message_id,
                "user_id": local_task.user_id,
                "inference_type": local_task.inference_type,
                "model_id": local_task.model_id,
                "model_name": local_task.model_name,
                "image_path": local_task.image_path,
                "source": local_task.source,
                "status": "queued",
                "progress": 0,
                "result": None,
                "error": None,
                "created_at": local_task.created_at,
                "updated_at": "2026-05-01T11:59:59+00:00",
            }
        ),
    )

    resolved = await mod.get_chat_patch_task(local_task.task_id)
    assert resolved is not None
    assert resolved.status == "running"
    assert resolved.progress == 70
    assert resolved.updated_at == "2026-05-01T12:00:00+00:00"


@pytest.mark.asyncio
async def test_update_task_mirrors_snapshot(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])
    task = mod.ChatPatchTask(
        task_id="chat_patch_1",
        conversation_id="conv_1",
        message_id=7,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
    )
    mod._TASKS[task.task_id] = task
    mirror_mock = AsyncMock()
    monkeypatch.setattr(mod, "_set_task_snapshot", mirror_mock)

    await mod._update_task(task.task_id, status="running", progress=33)

    mirror_mock.assert_awaited_once()
    assert task.status == "running"
    assert task.progress == 33


@pytest.mark.asyncio
async def test_task_snapshot_helpers_degrade_when_redis_unavailable(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    class BrokenRedis:
        async def set(self, *args, **kwargs):
            raise RuntimeError("redis down")

        async def get(self, *args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(mod, "get_redis", lambda: BrokenRedis())

    await mod._set_task_snapshot("task_1", {"task_id": "task_1"})
    snapshot = await mod._get_task_snapshot("task_1")
    assert snapshot is None


@pytest.mark.asyncio
async def test_cleanup_conversation_chat_patch_tasks_publishes_cancellation_and_skips_local_queue(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    task = mod.ChatPatchTask(
        task_id="chat_1",
        conversation_id="conv_1",
        message_id=1,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
        status="queued",
    )
    mod._TASKS[task.task_id] = task
    mod._CONVERSATION_INDEX[task.conversation_id] = {task.task_id}

    publish_mock = AsyncMock()
    monkeypatch.setattr(mod, "publish_task_cancellation", publish_mock)

    await mod.cleanup_conversation_chat_patch_tasks("conv_1")

    publish_mock.assert_awaited_once_with("chat_1")
    assert task.task_id not in mod._TASKS
    assert "conv_1" not in mod._CONVERSATION_INDEX


@pytest.mark.asyncio
async def test_cleanup_chat_patch_tasks_from_message_publishes_cancellation_and_skips_local_queue(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    task = mod.ChatPatchTask(
        task_id="chat_2",
        conversation_id="conv_2",
        message_id=5,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
        status="queued",
    )
    mod._TASKS[task.task_id] = task
    mod._CONVERSATION_INDEX[task.conversation_id] = {task.task_id}

    publish_mock = AsyncMock()
    monkeypatch.setattr(mod, "publish_task_cancellation", publish_mock)

    await mod.cleanup_chat_patch_tasks_from_message("conv_2", 5)

    publish_mock.assert_awaited_once_with("chat_2")
    assert task.task_id not in mod._TASKS


@pytest.mark.asyncio
async def test_cancel_chat_patch_tasks_for_message_publishes_cancellation_and_skips_local_queue(monkeypatch):
    mod = __import__("gateway.routes.chat_patch_inference", fromlist=[""])

    task = mod.ChatPatchTask(
        task_id="chat_3",
        conversation_id="conv_3",
        message_id=3,
        user_id="user_1",
        inference_type="classification",
        model_id="model_1",
        model_name="Model One",
        image_path="/tmp/input.png",
        status="queued",
    )
    mod._TASKS[task.task_id] = task
    mod._CONVERSATION_INDEX[task.conversation_id] = {task.task_id}

    publish_mock = AsyncMock()
    monkeypatch.setattr(mod, "publish_task_cancellation", publish_mock)

    snapshots = await mod.cancel_chat_patch_tasks_for_message("conv_3", 3)

    publish_mock.assert_awaited_once_with("chat_3")
    assert task.task_id not in mod._TASKS
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "cancelled"
