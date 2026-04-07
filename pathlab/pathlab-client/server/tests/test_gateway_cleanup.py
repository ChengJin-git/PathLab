from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_cleanup_old_tasks_commits_when_records_deleted():
    db_mock = AsyncMock()
    db_mock.commit = AsyncMock()

    training_repo = MagicMock()
    training_repo.cleanup_old_finished_tasks = AsyncMock(return_value=2)
    export_repo = MagicMock()
    export_repo.cleanup_old_tasks = AsyncMock(return_value=1)
    storage_repo = MagicMock()
    storage_repo.cleanup_old_tasks = AsyncMock(return_value=0)

    async def _db_gen():
        yield db_mock

    with (
        patch("gateway.startup.get_db", return_value=_db_gen()),
        patch("gateway.startup.TrainingTaskRepository", training_repo),
        patch("gateway.startup.ExportTaskRepository", export_repo),
        patch("gateway.startup.StorageTaskRepository", storage_repo),
    ):
        from gateway.startup import cleanup_old_tasks

        await cleanup_old_tasks()

    db_mock.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_expired_permissions_commits_when_grants_removed():
    db_mock = AsyncMock()
    db_mock.commit = AsyncMock()

    grant_repo = MagicMock()
    grant_repo.get_all_expired = AsyncMock(return_value=[MagicMock()])
    grant_repo.delete_expired = AsyncMock(return_value=3)

    async def _db_gen():
        yield db_mock

    with (
        patch("gateway.startup.get_db", return_value=_db_gen()),
        patch("gateway.startup.DatasetGrantRepository", grant_repo),
    ):
        from gateway.startup import cleanup_expired_permissions

        await cleanup_expired_permissions()

    db_mock.commit.assert_awaited_once()
