import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch


def _make_training_logger_mock():
    mock = MagicMock()
    mock.info = AsyncMock()
    mock.error = AsyncMock()
    return mock


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


def _close_background_coro(coro):
    if hasattr(coro, "close"):
        coro.close()
    return MagicMock()


@pytest.mark.asyncio
async def test_wsi_task_launches_pre_queue_patching():
    """WSI tasks launch run_patching_then_submit and register with queue manager."""
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1", "wsi_2"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = MagicMock()
    mock_queue.register_patching_task = MagicMock()
    mock_queue.submit = AsyncMock()
    mock_training_logger = _make_training_logger_mock()
    real_create_task = asyncio.create_task

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch(
            "gateway.routes.training.run_patching_then_submit",
            new_callable=AsyncMock,
        ) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
        patch("gateway.routes.training.asyncio.create_task") as mock_create_task,
    ):
        mock_repo.update_status = AsyncMock()
        mock_create_task.side_effect = real_create_task

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_wsi",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    mock_queue.submit.assert_not_awaited()
    mock_queue.register_patching_task.assert_called_once()


@pytest.mark.asyncio
async def test_patch_task_submits_directly_to_queue():
    """Patch tasks submit directly to GPU queue without pre-queue patching."""
    pipeline_kwargs = {
        "data_type": "patch",
        "wsi_ids": ["img_1"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = AsyncMock()
    mock_queue.register_patching_task = MagicMock()
    mock_training_logger = _make_training_logger_mock()

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch(
            "gateway.routes.training.run_patching_then_submit",
            new_callable=AsyncMock,
        ) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_patch",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    mock_queue.register_patching_task.assert_not_called()


@pytest.mark.asyncio
async def test_validate_files_and_enqueue_marks_failed_on_blocking_preflight_error():
    mock_training_logger = _make_training_logger_mock()

    with (
        patch(
            "gateway.routes.training._check_file_accessibility",
            side_effect=HTTPException(
                status_code=503, detail="storage root unavailable"
            ),
        ),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        mock_db = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_failed_preflight",
            paths_to_check=[("wsi_1", "/uploads/file.png", "file.png")],
            uploads_dir="/uploads",
            pipeline_kwargs={
                "data_type": "patch",
                "wsi_ids": ["wsi_1"],
                "preprocessing_config": {},
                "model_config": {},
                "training_task_type": "classification",
            },
        )

    mock_repo.update_status.assert_awaited_once()
    mock_training_logger.error.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_files_and_enqueue_marks_failed_when_inaccessible_files_found():
    mock_training_logger = _make_training_logger_mock()

    with (
        patch(
            "gateway.routes.training._check_file_accessibility",
            return_value=["broken_patch_001.png"],
        ),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch(
            "gateway.routes.training.TrainingLogger",
            return_value=mock_training_logger,
        ),
    ):
        mock_repo.update_status = AsyncMock()
        mock_db = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        training_module = importlib.import_module("gateway.routes.training")

        await training_module._validate_files_and_enqueue(
            task_id="task_inaccessible_files",
            paths_to_check=[("wsi_1", "/uploads/file.png", "file.png")],
            uploads_dir="/uploads",
            pipeline_kwargs={
                "data_type": "patch",
                "wsi_ids": ["wsi_1"],
                "preprocessing_config": {},
                "model_config": {},
                "training_task_type": "classification",
            },
        )

    mock_repo.update_status.assert_awaited_once()
    mock_training_logger.error.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_training_task_normalizes_wsi_classification_for_canonical_group_task_type():
    training_module = importlib.import_module("gateway.routes.training")

    req = training_module.TrainingTaskRequest(
        task_id="train_taxonomy_legacy_match",
        task_name="canonical wsi classification",
        task_type="wsi_classification",
        data_type="wsi",
        wsi_ids=["wsi_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = MagicMock()
    user.id = "user_1"
    user.is_admin.return_value = True
    user.can_use_gpu.return_value = True

    wsi = SimpleNamespace(
        wsi_id="wsi_1",
        dataset_id="ds_1",
        user_id="owner_1",
        wsi_path="slides/a.svs",
        original_filename="a.svs",
        label="tumor",
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_1")
    canonical_contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_taxonomy_legacy_match"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()

    with (
        patch("gateway.routes.training.safe_session", side_effect=_make_safe_session_factory(db_read, db_write)),
        patch("gateway.routes.training.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"wsi_1": wsi})),
        patch("gateway.routes.training.require_no_active_batch_imports", new=AsyncMock()),
        patch("gateway.routes.training.DatasetRepository.get_by_ids", new=AsyncMock(return_value=[dataset])),
        patch("gateway.routes.training.ensure_dataset_segmentation_contract", return_value=canonical_contract),
        patch("gateway.routes.training.DataGroupRepository.get_or_create", new=AsyncMock(return_value=SimpleNamespace(group_id="g1", task_type="wsi_classification", data_type="wsi", aggregation_level="case"))) as mock_get_or_create,
        patch("gateway.routes.training.TrainingTaskRepository.create", new=AsyncMock(return_value=created_task)) as mock_create,
        patch("gateway.routes.training.invalidate_chat_context", new=AsyncMock()),
        patch("gateway.routes.training._validate_files_and_enqueue", new=AsyncMock()) as mock_preflight_enqueue,
        patch("gateway.routes.training.Config.get_global_settings", return_value={}),
        patch("gateway.routes.training.Config.get_uploads_dir", return_value=Path("/uploads")),
        patch("gateway.routes.training.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.training.build_task_descriptor", side_effect=training_module.build_task_descriptor) as mock_build_descriptor,
        patch("gateway.routes.training.enqueue_task_descriptor", new=AsyncMock()) as mock_enqueue,
    ):
        result = await training_module.create_training_task(req=req, user=user)

    create_await_args = mock_create.await_args
    assert create_await_args is not None
    create_args = create_await_args.args
    create_task_data = create_args[1]
    get_or_create_await_args = mock_get_or_create.await_args
    assert get_or_create_await_args is not None
    build_call = mock_build_descriptor.call_args
    assert build_call is not None
    assert create_task_data["task_type"] == "wsi_classification"
    assert get_or_create_await_args.kwargs["task_type"] == "wsi_classification"
    assert get_or_create_await_args.kwargs["aggregation_level"] == "case"
    assert build_call.kwargs["payload"]["pipeline_kwargs"]["training_task_type"] == "wsi_classification"
    assert result["task_id"] == "train_taxonomy_legacy_match"


@pytest.mark.asyncio
async def test_create_training_task_preserves_case_level_for_wsi_classification_dataset():
    training_module = importlib.import_module("gateway.routes.training")

    req = training_module.TrainingTaskRequest(
        task_id="train_taxonomy_case_level",
        task_name="case-level wsi classification",
        task_type="wsi_classification",
        data_type="wsi",
        wsi_ids=["wsi_2"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = MagicMock()
    user.id = "user_2"
    user.is_admin.return_value = True
    user.can_use_gpu.return_value = True

    wsi = SimpleNamespace(
        wsi_id="wsi_2",
        dataset_id="ds_2",
        user_id="owner_2",
        wsi_path="slides/b.svs",
        original_filename="b.svs",
        label="tumor",
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_2")
    canonical_contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )
    created_task = SimpleNamespace(
        classes=["tumor", "normal"],
        to_dict=lambda: {"task_id": "train_taxonomy_case_level"},
    )

    db_read = AsyncMock()
    db_write = AsyncMock()

    with (
        patch("gateway.routes.training.safe_session", side_effect=_make_safe_session_factory(db_read, db_write)),
        patch("gateway.routes.training.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"wsi_2": wsi})),
        patch("gateway.routes.training.require_no_active_batch_imports", new=AsyncMock()),
        patch("gateway.routes.training.DatasetRepository.get_by_ids", new=AsyncMock(return_value=[dataset])),
        patch("gateway.routes.training.ensure_dataset_segmentation_contract", return_value=canonical_contract),
        patch("gateway.routes.training.DataGroupRepository.get_or_create", new=AsyncMock(return_value=SimpleNamespace(group_id="g2", task_type="wsi_classification", data_type="wsi", aggregation_level="case"))) as mock_get_or_create,
        patch("gateway.routes.training.TrainingTaskRepository.create", new=AsyncMock(return_value=created_task)) as mock_create,
        patch("gateway.routes.training.invalidate_chat_context", new=AsyncMock()),
        patch("gateway.routes.training._validate_files_and_enqueue", new=AsyncMock()),
        patch("gateway.routes.training.Config.get_global_settings", return_value={}),
        patch("gateway.routes.training.Config.get_uploads_dir", return_value=Path("/uploads")),
        patch("gateway.routes.training.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.training.build_task_descriptor", side_effect=training_module.build_task_descriptor) as mock_build_descriptor,
        patch("gateway.routes.training.enqueue_task_descriptor", new=AsyncMock()),
    ):
        await training_module.create_training_task(req=req, user=user)

    get_or_create_await_args = mock_get_or_create.await_args
    assert get_or_create_await_args is not None
    create_await_args = mock_create.await_args
    assert create_await_args is not None

    assert get_or_create_await_args.kwargs["aggregation_level"] == "case"
    assert get_or_create_await_args.kwargs["task_type"] == "wsi_classification"
    assert create_await_args.args[1]["task_type"] == "wsi_classification"


@pytest.mark.asyncio
async def test_create_training_task_rejects_patch_segmentation_case_aggregation():
    training_module = importlib.import_module("gateway.routes.training")

    req = training_module.TrainingTaskRequest(
        task_id="train_taxonomy_invalid_seg_case",
        task_name="invalid segmentation case aggregation",
        task_type="patch_segmentation",
        data_type="patch",
        wsi_ids=["patch_1"],
        preprocessing={"tile_size": 224},
        model={"architecture": "linear_decoder", "backbone": "uni"},
    )
    user = MagicMock()
    user.id = "user_3"
    user.is_admin.return_value = True
    user.can_use_gpu.return_value = True

    wsi = SimpleNamespace(
        wsi_id="patch_1",
        dataset_id="ds_3",
        user_id="owner_3",
        wsi_path="patches/p1.png",
        original_filename="p1.png",
        label=None,
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_3")
    invalid_contract = SimpleNamespace(
        task_type="patch_segmentation",
        data_type="patch",
        aggregation_level="case",
    )

    db_read = AsyncMock()
    db_write = AsyncMock()
    created_task = SimpleNamespace(
        classes=["background", "tumor"],
        to_dict=lambda: {"task_id": "train_taxonomy_invalid_seg_case"},
    )

    with (
        patch("gateway.routes.training.safe_session", side_effect=_make_safe_session_factory(db_read, db_write)),
        patch("gateway.routes.training.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"patch_1": wsi})),
        patch("gateway.routes.training.require_no_active_batch_imports", new=AsyncMock()),
        patch("gateway.routes.training.DatasetRepository.get_by_ids", new=AsyncMock(return_value=[dataset])),
        patch("gateway.routes.training.ensure_dataset_segmentation_contract", return_value=invalid_contract),
        patch("gateway.routes.training.DataGroupRepository.get_or_create", new=AsyncMock(return_value=SimpleNamespace(group_id="g3", task_type="patch_segmentation", data_type="patch", aggregation_level="case"))),
        patch("gateway.routes.training.TrainingTaskRepository.create", new=AsyncMock(return_value=created_task)) as mock_create,
        patch("gateway.routes.training.invalidate_chat_context", new=AsyncMock()),
        patch("gateway.routes.training._validate_files_and_enqueue", new=AsyncMock()),
        patch("gateway.routes.training.Config.get_global_settings", return_value={}),
        patch("gateway.routes.training.Config.get_uploads_dir", return_value=Path("/uploads")),
        patch("gateway.routes.training.asyncio.create_task", side_effect=_close_background_coro),
    ):
        with pytest.raises(HTTPException, match="unsupported aggregation_level") as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 400
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_rejects_when_resolved_data_group_task_type_conflicts():
    training_module = importlib.import_module("gateway.routes.training")

    req = training_module.TrainingTaskRequest(
        task_id="train_taxonomy_group_conflict",
        task_name="group conflict",
        task_type="wsi_classification",
        data_type="wsi",
        wsi_ids=["wsi_conflict"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = MagicMock()
    user.id = "user_conflict"
    user.is_admin.return_value = True
    user.can_use_gpu.return_value = True

    wsi = SimpleNamespace(
        wsi_id="wsi_conflict",
        dataset_id="ds_conflict",
        user_id="owner_conflict",
        wsi_path="slides/conflict.svs",
        original_filename="conflict.svs",
        label="tumor",
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_conflict")
    contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )

    db_read = AsyncMock()
    db_write = AsyncMock()

    with (
        patch("gateway.routes.training.safe_session", side_effect=_make_safe_session_factory(db_read, db_write)),
        patch("gateway.routes.training.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"wsi_conflict": wsi})),
        patch("gateway.routes.training.require_no_active_batch_imports", new=AsyncMock()),
        patch("gateway.routes.training.DatasetRepository.get_by_ids", new=AsyncMock(return_value=[dataset])),
        patch("gateway.routes.training.ensure_dataset_segmentation_contract", return_value=contract),
        patch("gateway.routes.training.is_worker_healthy", new=AsyncMock(return_value=True)),
        patch("gateway.routes.training.DataGroupRepository.get_or_create", new=AsyncMock(return_value=SimpleNamespace(group_id="g_conflict", task_type="patch_classification", data_type="patch", aggregation_level="file"))),
        patch("gateway.routes.training.TrainingTaskRepository.create", new=AsyncMock()) as mock_create,
    ):
        with pytest.raises(HTTPException, match="does not match requested task_type") as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 400
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_training_task_prefers_explicit_data_type_mismatch_error_over_taxonomy_error():
    training_module = importlib.import_module("gateway.routes.training")

    req = training_module.TrainingTaskRequest(
        task_id="train_taxonomy_data_type_mismatch",
        task_name="data_type mismatch",
        task_type="patch_classification",
        data_type="patch",
        wsi_ids=["wsi_dtype"],
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )
    user = MagicMock()
    user.id = "user_dtype"
    user.is_admin.return_value = True
    user.can_use_gpu.return_value = True

    wsi = SimpleNamespace(
        wsi_id="wsi_dtype",
        dataset_id="ds_dtype",
        user_id="owner_dtype",
        wsi_path="slides/dtype.svs",
        original_filename="dtype.svs",
        label="tumor",
        dataset=SimpleNamespace(is_public=False, parent_dataset_id=None),
    )
    dataset = SimpleNamespace(dataset_id="ds_dtype")
    contract = SimpleNamespace(
        task_type="wsi_classification",
        data_type="wsi",
        aggregation_level="case",
    )

    db_read = AsyncMock()

    with (
        patch("gateway.routes.training.safe_session", side_effect=_make_safe_session_factory(db_read)),
        patch("gateway.routes.training.WSIRepository.get_by_ids_with_dataset", new=AsyncMock(return_value={"wsi_dtype": wsi})),
        patch("gateway.routes.training.require_no_active_batch_imports", new=AsyncMock()),
        patch("gateway.routes.training.DatasetRepository.get_by_ids", new=AsyncMock(return_value=[dataset])),
        patch("gateway.routes.training.ensure_dataset_segmentation_contract", return_value=contract),
    ):
        with pytest.raises(HTTPException, match="Requested data_type 'patch' does not match dataset data_type 'wsi'") as exc_info:
            await training_module.create_training_task(req=req, user=user)

    assert exc_info.value.status_code == 400
