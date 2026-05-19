from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.ai.schemas.base import TaskStatus


def _make_user(role: str = "admin") -> MagicMock:
    user = MagicMock()
    user.id = "user_1"
    user.role = role
    user.is_active = True
    user.is_admin = MagicMock(return_value=(role == "admin"))
    user.can_use_gpu = MagicMock(return_value=(role in ("admin", "pathologist")))
    return user


class _SafeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_safe_session_factory(*dbs):
    queue = list(dbs)

    def _factory():
        if not queue:
            raise AssertionError("safe_session called more times than expected")
        return _SafeSessionCtx(queue.pop(0))

    return _factory


@pytest.mark.asyncio
async def test_create_reference_is_reference_only_for_segmentation_dataset():
    training_repo_module = __import__(
        "backend.database.repositories.training", fromlist=[""]
    )

    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    task_data = {
        "task_id": "train_seg_large",
        "task_name": "large segmentation",
        "task_type": "patch_segmentation",
        "group_id": "group_seg",
        "task_description": None,
        "preprocessing_config": {},
        "model_config": {},
        "user_id": "user_1",
    }

    with (
        patch(
            "backend.database.repositories.training._load_wsis_for_training_reference",
            new=AsyncMock(side_effect=AssertionError("create_reference must not materialize dataset rows")),
        ),
        patch(
            "backend.database.repositories.training._insert_dataset_wsi_associations",
            new=AsyncMock(),
        ) as insert_associations,
    ):
        task = await training_repo_module.TrainingTaskRepository.create_reference(
            db,
            task_data,
            dataset_id="ds_large",
            data_type="patch",
            split_config={"strategy": "random"},
        )

    assert task.task_id == "train_seg_large"
    assert task.classes == []
    assert task.preprocessing_config == {"split_config": {"strategy": "random"}}
    assert task.status == TaskStatus.PENDING
    insert_associations.assert_awaited_once_with(
        db, task_id="train_seg_large", dataset_id="ds_large", data_type="patch"
    )
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_dataset_based_training_task_enqueues_dataset_input_reference_without_materializing_ids():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_large_dataset",
        task_name="large dataset",
        task_type="patch_classification",
        data_type="patch",
        dataset_id="ds_large",
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    dataset = SimpleNamespace(
        dataset_id="ds_large",
        user_id="owner_1",
        is_public=False,
        parent_dataset_id=None,
    )
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_large_dataset"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    captured_descriptor = None

    async def _capture_enqueue(descriptor):
        nonlocal captured_descriptor
        captured_descriptor = descriptor

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_wsi_ids",
            new=AsyncMock(side_effect=AssertionError("Gateway must not materialize dataset IDs")),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(side_effect=AssertionError("Gateway must not fetch every dataset row")),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch("gateway.routes.training.DatasetRepository.get_by_id", new=AsyncMock(return_value=dataset)),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DatasetStatsRepository.get_by_dataset_id",
            new=AsyncMock(return_value=SimpleNamespace(file_count=250000)),
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create_reference",
            new=AsyncMock(return_value=created_task),
        ) as create_reference,
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch("gateway.routes.training.Config.get_global_settings", return_value={}),
        patch("gateway.routes.training.Config.get_uploads_dir", return_value=Path("/uploads")),
        patch("gateway.routes.training.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=training_module.build_task_descriptor,
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=_capture_enqueue),
        ),
    ):
        result = await training_module.create_training_task(req=req, user=user)

    assert captured_descriptor is not None
    payload = mock_build_descriptor.call_args.kwargs["payload"]
    assert payload["task_id"] == "train_large_dataset"
    assert payload["paths_to_check"] == []
    assert payload["pipeline_kwargs"]["input_ref"] == {
        "kind": "dataset",
        "dataset_id": "ds_large",
    }
    assert payload["pipeline_kwargs"]["wsi_count"] == 250000
    assert "wsi_ids" not in payload["pipeline_kwargs"]
    assert "source_dataset_id" not in payload["pipeline_kwargs"]
    assert result["wsi_count"] == 250000
    create_reference.assert_awaited_once()
    assert create_reference.await_args.kwargs["data_type"] == "patch"


@pytest.mark.asyncio
async def test_worker_resolves_training_input_reference_before_preflight():
    training_jobs_module = __import__("task_worker.jobs.training", fromlist=[""])

    pipeline_kwargs = {
        "data_type": "patch",
        "input_ref": {"kind": "training_task_selection", "task_id": "train_large_dataset"},
        "wsi_count": 2,
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "patch_classification",
    }

    db = AsyncMock()
    captured_pipeline_kwargs = None
    captured_paths_to_check = None

    async def _capture_validate(task_id, paths_to_check, uploads_dir, pipeline_kwargs):
        nonlocal captured_pipeline_kwargs, captured_paths_to_check
        captured_paths_to_check = paths_to_check
        captured_pipeline_kwargs = pipeline_kwargs

    wsi_map = {
        "patch_1": SimpleNamespace(
            wsi_id="patch_1", wsi_path="patches/p1.png", original_filename="p1.png"
        ),
        "patch_2": SimpleNamespace(
            wsi_id="patch_2", wsi_path="patches/p2.png", original_filename="p2.png"
        ),
    }

    with (
        patch(
            "gateway.pipeline.safe_session",
            side_effect=_make_safe_session_factory(db),
        ),
        patch(
            "gateway.pipeline.TrainingTaskRepository.get_wsi_ids",
            new=AsyncMock(return_value=["patch_1", "patch_2"]),
        ) as mock_get_wsi_ids,
        patch(
            "gateway.pipeline.WSIRepository.get_by_ids",
            new=AsyncMock(return_value=wsi_map),
        ) as mock_get_wsis,
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            new=AsyncMock(side_effect=_capture_validate),
        ),
    ):
        await training_jobs_module.validate_files_and_enqueue(
            "train_large_dataset",
            [],
            "/uploads",
            pipeline_kwargs,
        )

    mock_get_wsi_ids.assert_awaited_once_with(db, "train_large_dataset")
    mock_get_wsis.assert_awaited_once_with(db, ["patch_1", "patch_2"])
    assert captured_paths_to_check == [
        ("patch_1", "patches/p1.png", "p1.png"),
        ("patch_2", "patches/p2.png", "p2.png"),
    ]
    assert captured_pipeline_kwargs is not None
    assert captured_pipeline_kwargs["wsi_ids"] == ["patch_1", "patch_2"]
    assert captured_pipeline_kwargs["wsi_count"] == 2
    assert "input_ref" not in captured_pipeline_kwargs


@pytest.mark.asyncio
async def test_worker_rejects_inline_wsi_ids_training_descriptors():
    training_jobs_module = __import__("task_worker.jobs.training", fromlist=[""])

    with pytest.raises(ValueError, match="must use input_ref"):
        await training_jobs_module.validate_files_and_enqueue(
            "train_legacy_descriptor",
            [],
            "/uploads",
            {
                "data_type": "patch",
                "wsi_ids": ["patch_1"],
                "preprocessing_config": {},
                "model_config": {},
                "training_task_type": "patch_classification",
            },
        )


@pytest.mark.asyncio
async def test_worker_finalizes_dataset_reference_split_metadata_outside_gateway_submission():
    training_jobs_module = __import__("task_worker.jobs.training", fromlist=[""])

    pipeline_kwargs = {
        "data_type": "patch",
        "input_ref": {"kind": "dataset", "dataset_id": "ds_large"},
        "wsi_count": 2,
        "preprocessing_config": {
            "split_config": {
                "strategy": "random",
                "ratios": {"train": 0.5, "val": 0.5, "test": 0.0},
                "seed": 42,
                "stratified": False,
            }
        },
        "model_config": {},
        "training_task_type": "patch_classification",
    }

    db = AsyncMock()
    task = SimpleNamespace(task_id="train_large_dataset", user_id="user_1", classes=[])
    wsi_map = {
        "patch_1": SimpleNamespace(
            wsi_id="patch_1",
            dataset_id="ds_large",
            wsi_path="patches/p1.png",
            original_filename="p1.png",
            label="tumor",
            case_id=None,
        ),
        "patch_2": SimpleNamespace(
            wsi_id="patch_2",
            dataset_id="ds_large",
            wsi_path="patches/p2.png",
            original_filename="p2.png",
            label="normal",
            case_id=None,
        ),
    }
    captured_pipeline_kwargs = None

    async def _capture_validate(task_id, paths_to_check, uploads_dir, pipeline_kwargs):
        nonlocal captured_pipeline_kwargs
        captured_pipeline_kwargs = pipeline_kwargs

    with (
        patch(
            "gateway.pipeline.safe_session",
            side_effect=_make_safe_session_factory(db),
        ),
        patch(
            "gateway.pipeline.WSIRepository.get_ids_by_dataset",
            new=AsyncMock(return_value=["patch_1", "patch_2"]),
        ) as mock_get_dataset_ids,
        patch(
            "gateway.pipeline.WSIRepository.get_by_ids",
            new=AsyncMock(return_value=wsi_map),
        ),
        patch(
            "gateway.pipeline.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=task),
        ),
        patch(
            "gateway.pipeline.TrainingTaskRepository.get_dataset_aggregation_level",
            new=AsyncMock(return_value="file"),
        ),
        patch(
            "gateway.pipeline.TrainingTaskRepository.update_training_reference_metadata",
            new=AsyncMock(return_value=task),
        ) as mock_update_metadata,
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            new=AsyncMock(side_effect=_capture_validate),
        ),
    ):
        await training_jobs_module.validate_files_and_enqueue(
            "train_large_dataset",
            [],
            "/uploads",
            pipeline_kwargs,
        )

    mock_get_dataset_ids.assert_awaited_once_with(db, "ds_large", data_type="patch")
    metadata_kwargs = mock_update_metadata.await_args.kwargs
    assert metadata_kwargs["classes"] == ["normal", "tumor"]
    assert set(metadata_kwargs["split_map"].values()) <= {"train", "val", "test"}
    assert captured_pipeline_kwargs["wsi_ids"] == ["patch_1", "patch_2"]
    assert "input_ref" not in captured_pipeline_kwargs


@pytest.mark.asyncio
async def test_create_training_task_enqueues_descriptor_and_does_not_run_preflight_locally():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_dispatch_test",
        task_name="dispatch test",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_dispatch_test"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()

    captured_descriptor = None

    async def _capture_enqueue(descriptor):
        nonlocal captured_descriptor
        captured_descriptor = descriptor

    create_task = AsyncMock(return_value=created_task)

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            side_effect=RuntimeError("Gateway must not call _validate_files_and_enqueue"),
        ) as mock_local_preflight,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=training_module.build_task_descriptor,
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=_capture_enqueue),
        ) as mock_enqueue,
    ):
        result = await training_module.create_training_task(req=req, user=user)

    mock_local_preflight.assert_not_called()
    mock_build_descriptor.assert_called_once()
    mock_enqueue.assert_awaited_once()
    assert captured_descriptor is not None

    build_call = mock_build_descriptor.call_args
    assert build_call.kwargs["handler"] == "training.preflight"
    payload = build_call.kwargs["payload"]
    assert payload["task_id"] == "train_dispatch_test"
    assert payload["paths_to_check"] == []
    assert payload["uploads_dir"] == "/uploads"
    assert payload["pipeline_kwargs"]["training_task_type"] == "patch_classification"
    assert payload["pipeline_kwargs"]["data_type"] == "patch"
    assert payload["pipeline_kwargs"]["input_ref"] == {
        "kind": "training_task_selection",
        "task_id": "train_dispatch_test",
    }
    assert "wsi_ids" not in payload["pipeline_kwargs"]

    assert result["task_id"] == "train_dispatch_test"
    assert result["status"] == "pending"
    assert result["progress"] == 0


@pytest.mark.asyncio
async def test_create_training_task_returns_503_when_worker_unhealthy():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_unhealthy",
        task_name="unhealthy worker",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_unhealthy"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    create_task = AsyncMock(return_value=created_task)

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training._validate_files_and_enqueue",
            side_effect=RuntimeError("must not be called"),
        ) as mock_local_preflight,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=RuntimeError("must not build descriptor when unhealthy"),
        ) as mock_build_descriptor,
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=RuntimeError("must not enqueue when unhealthy")),
        ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail

    create_task.assert_not_awaited()
    mock_local_preflight.assert_not_called()
    mock_build_descriptor.assert_not_called()
    mock_enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_returns_validation_error_before_worker_health_check():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_invalid_before_health",
        task_name="invalid before health",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )

    db_read = AsyncMock()

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(side_effect=RuntimeError("must not check health")),
        ) as mock_health,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 400
    assert "Requested data_type 'patch' does not match dataset data_type 'wsi'" in exc_info.value.detail
    mock_health.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_marks_task_failed_when_descriptor_enqueue_fails():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    req = training_module.TrainingTaskRequest(
        task_id="train_enqueue_failure",
        task_name="enqueue failure",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = _make_user("admin")

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    contract = SimpleNamespace(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_enqueue_failure"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    db_cleanup = AsyncMock()
    create_task = AsyncMock(return_value=created_task)
    update_status = AsyncMock()

    with (
        patch(
            "gateway.routes.training.safe_session",
            side_effect=_make_safe_session_factory(db_read, db_write, db_cleanup),
        ),
        patch(
            "gateway.routes.training.WSIRepository.get_by_ids_with_dataset",
            new=AsyncMock(return_value={"patch_1": wsi}),
        ),
        patch(
            "gateway.routes.training.require_no_active_batch_imports",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.DatasetRepository.get_by_ids",
            new=AsyncMock(return_value=[dataset]),
        ),
        patch(
            "gateway.routes.training.ensure_dataset_segmentation_contract",
            return_value=contract,
        ),
        patch(
            "gateway.routes.training.DataGroupRepository.get_or_create",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    group_id="g1",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            ),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.create",
            new=create_task,
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.update_status",
            new=update_status,
        ),
        patch(
            "gateway.routes.training.invalidate_chat_context",
            new=AsyncMock(side_effect=RuntimeError("must not invalidate after enqueue failure")),
        ) as mock_invalidate,
        patch(
            "gateway.routes.training.Config.get_global_settings",
            return_value={},
        ),
        patch(
            "gateway.routes.training.Config.get_uploads_dir",
            return_value=Path("/uploads"),
        ),
        patch(
            "gateway.routes.training.is_worker_healthy",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "gateway.routes.training.build_task_descriptor",
            side_effect=training_module.build_task_descriptor,
        ),
        patch(
            "gateway.routes.training.enqueue_task_descriptor",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ) as mock_enqueue,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 503
    assert "Task worker unavailable" in exc_info.value.detail
    create_task.assert_awaited_once()
    mock_enqueue.assert_awaited_once()
    update_status.assert_awaited_once_with(
        db_cleanup,
        "train_enqueue_failure",
        training_module.TaskStatus.FAILED,
        error_message="Failed to enqueue task descriptor: redis down",
    )
    db_cleanup.commit.assert_awaited_once()
    mock_invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_active_training_task_publishes_cancellation_and_does_not_call_local_queue():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    task = SimpleNamespace(
        task_id="train_delete_active",
        user_id="user_1",
        status=training_module.TaskStatus.TRAINING,
    )
    db = AsyncMock()
    user = _make_user("admin")

    publish_mock = AsyncMock()

    with (
        patch(
            "gateway.routes.training.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=task),
        ),
        patch(
            "gateway.routes.training.TrainedModelRepository.get_by_task_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "gateway.routes.training.AIResultRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.delete",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingLogRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.cancel_ai_service_training",
            new=AsyncMock(),
        ) as mock_cancel_ai,
        patch(
            "gateway.routes.training.get_task_queue",
            side_effect=AssertionError("must not call local queue"),
        ),
        patch(
            "gateway.routes.training.publish_task_cancellation",
            new=publish_mock,
        ),
    ):
        response = await training_module.delete_training_task(
            task_id="train_delete_active", mode="standard", user=user, db=db
        )

    assert response["task_id"] == "train_delete_active"
    publish_mock.assert_awaited_once_with("train_delete_active")
    mock_cancel_ai.assert_awaited_once_with("train_delete_active")


@pytest.mark.asyncio
async def test_delete_completed_training_task_still_publishes_cancellation_to_stop_postprocessing():
    training_module = __import__("gateway.routes.training", fromlist=[""])

    task = SimpleNamespace(
        task_id="train_delete_completed",
        user_id="user_1",
        status=training_module.TaskStatus.COMPLETED,
    )
    db = AsyncMock()
    user = _make_user("admin")
    publish_mock = AsyncMock()

    with (
        patch(
            "gateway.routes.training.TrainingTaskRepository.get_by_id",
            new=AsyncMock(return_value=task),
        ),
        patch(
            "gateway.routes.training.TrainedModelRepository.get_by_task_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "gateway.routes.training.AIResultRepository.delete_by_task_id",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.TrainingTaskRepository.delete",
            new=AsyncMock(),
        ),
        patch(
            "gateway.routes.training.cancel_ai_service_training",
            new=AsyncMock(),
        ) as mock_cancel_ai,
        patch(
            "gateway.routes.training.publish_task_cancellation",
            new=publish_mock,
        ),
    ):
        response = await training_module.delete_training_task(
            task_id="train_delete_completed", mode="complete", user=user, db=db
        )

    assert response["task_id"] == "train_delete_completed"
    publish_mock.assert_awaited_once_with("train_delete_completed")
    mock_cancel_ai.assert_awaited_once_with("train_delete_completed")
