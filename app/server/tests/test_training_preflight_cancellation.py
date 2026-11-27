from unittest.mock import AsyncMock, MagicMock

from gateway.routes import training


async def test_cancelled_during_preflight_never_enters_gpu_queue(monkeypatch):
    logger = MagicMock()
    logger.close = AsyncMock()
    queue = MagicMock()
    queue.submit = AsyncMock()
    update = AsyncMock()
    monkeypatch.setattr(training, "TrainingLogger", lambda _: logger)
    monkeypatch.setattr(training, "_check_file_accessibility", AsyncMock(return_value=[]))
    monkeypatch.setattr(training, "is_task_cancelled", AsyncMock(return_value=True))
    monkeypatch.setattr(training, "get_task_queue", lambda: queue)
    monkeypatch.setattr(training.TrainingTaskRepository, "update_status", update)
    await training._validate_files_and_enqueue("cancelled", [], "/uploads", {"data_type":"patch"})
    queue.submit.assert_not_awaited()
    update.assert_not_awaited()
    logger.close.assert_awaited_once()
