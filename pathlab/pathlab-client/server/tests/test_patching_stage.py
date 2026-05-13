import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from importlib import import_module

TaskStatus = import_module("backend.ai.schemas.base").TaskStatus


def test_feature_extraction_stage_estimate_fits_24gb_gpu_startup_gate():
    """Gateway should not reject feature extraction before AI's runtime VRAM probe."""
    pipeline = import_module("gateway.pipeline")

    required_vram_mb = pipeline._estimate_feature_extraction_vram_mb("conch", 64)

    assert required_vram_mb <= 24576.0


@pytest.mark.asyncio
async def test_compute_patches_passes_use_otsu_to_segmenter_once():
    """compute_patches should not pass duplicate use_otsu kwargs to TissueSegmenter."""
    compute_patches = import_module("backend.preprocessing.main").compute_patches

    mock_segmenter = MagicMock()
    mock_segmenter.segment_tissue.return_value = (["contour"], [])
    segmenter_cls = MagicMock(return_value=mock_segmenter)
    slide = MagicMock(filepath="/tmp/test.svs")

    with (
        patch("backend.preprocessing.main.get_slide", new_callable=AsyncMock) as get_slide,
        patch("backend.preprocessing.main.TissueSegmenter", segmenter_cls),
        patch(
            "backend.preprocessing.main.get_or_compute_coordinates",
            return_value=([(1, 2)], Path("/tmp/test.h5")),
        ),
        patch("backend.preprocessing.main._force_release_memory"),
        patch("backend.preprocessing.main.evict_slide"),
    ):
        get_slide.return_value = slide

        response = await compute_patches(
            "wsi_1",
            level=0,
            force_recompute=True,
            seg_level=-1,
            sthresh=8,
            mthresh=7,
            close=4,
            use_otsu=False,
            contour_fn="four_pt",
            use_padding=True,
            a_t=5,
            a_h=16,
            max_n_holes=8,
            save_mask=False,
            db=MagicMock(),
        )

    assert response.status_code == 200
    segmenter_cls.assert_called_once_with(
        sthresh=8,
        mthresh=7,
        close=4,
        use_otsu=False,
        seg_level=-1,
        filter_params={"a_t": 5, "a_h": 16, "max_n_holes": 8},
    )


@pytest.mark.asyncio
async def test_run_patching_stage_processes_all_wsis():
    """run_patching_stage iterates over all WSI IDs and calls ensure_coords_ready for each."""
    task_id = "test_task_123"
    wsi_ids = ["wsi_1", "wsi_2", "wsi_3"]
    preprocessing_config = {}

    mock_result = {"num_patches": 100, "cached": False}

    with (
        patch(
            "gateway.pipeline.ensure_coords_ready", return_value=mock_result
        ) as mock_coords,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.PATCHING)
        )

        run_patching_stage = import_module("gateway.pipeline").run_patching_stage

        await run_patching_stage(task_id, wsi_ids, preprocessing_config)

    assert mock_coords.await_count == 3
    initial_status_call = mock_repo.update_status.call_args_list[0]
    assert initial_status_call.args[2] == TaskStatus.PATCHING
    assert initial_status_call.kwargs.get("progress") == 0


@pytest.mark.asyncio
async def test_run_patching_stage_stops_on_cancelled_status():
    """run_patching_stage raises CancelledError when DB status is CANCELLED."""
    task_id = "test_task_456"
    wsi_ids = ["wsi_1", "wsi_2"]
    preprocessing_config = {}

    with (
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.CANCELLED)
        )

        run_patching_stage = import_module("gateway.pipeline").run_patching_stage

        with pytest.raises(asyncio.CancelledError):
            await run_patching_stage(task_id, wsi_ids, preprocessing_config)


@pytest.mark.asyncio
async def test_run_patching_stage_empty_wsi_ids_returns_early():
    """run_patching_stage with empty wsi_ids returns without calling ensure_coords_ready."""
    with (
        patch(
            "gateway.pipeline.ensure_coords_ready", new_callable=AsyncMock
        ) as mock_coords,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()

        run_patching_stage = import_module("gateway.pipeline").run_patching_stage

        await run_patching_stage("task_empty", [], {})

    mock_coords.assert_not_awaited()
    mock_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_patching_stage_single_wsi_progress_reaches_33():
    """Single WSI: final progress update is exactly 33% (int(1/1 * 33))."""
    with (
        patch(
            "gateway.pipeline.ensure_coords_ready",
            return_value={"num_patches": 50, "cached": False},
        ),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(
            return_value=MagicMock(status=TaskStatus.PATCHING)
        )

        run_patching_stage = import_module("gateway.pipeline").run_patching_stage

        await run_patching_stage("task_single", ["wsi_only"], {})

    progress_values = [
        c.kwargs.get("progress")
        for c in mock_repo.update_status.call_args_list
        if c.kwargs.get("progress") is not None
    ]
    assert 33 in progress_values, (
        f"Expected progress=33 in calls, got: {progress_values}"
    )


@pytest.mark.asyncio
async def test_run_patching_then_submit_happy_path():
    """On success: runs patching, submits to GPU queue with patching_complete=True."""
    task_id = "test_happy"
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_queue.deregister_patching_task = MagicMock()

    with (
        patch(
            "gateway.pipeline.run_patching_stage", new_callable=AsyncMock
        ) as mock_patching,
        patch("gateway.task_queue.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.safe_session") as mock_safe_session,
    ):
        mock_task = MagicMock(status=TaskStatus.PATCHING)
        mock_repo.get_by_id = AsyncMock(return_value=mock_task)
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe_session.return_value = ctx

        run_patching_then_submit = import_module(
            "gateway.pipeline"
        ).run_patching_then_submit

        await run_patching_then_submit(task_id, pipeline_kwargs)

    mock_patching.assert_awaited_once()
    mock_queue.submit.assert_awaited_once()
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete") is True
    mock_queue.deregister_patching_task.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_run_training_pipeline_reselects_gpu_for_wsi_feature_and_training_stages():
    """WSI feature extraction and MIL training each acquire a fresh global GPU stage."""
    pipeline = import_module("gateway.pipeline")
    mock_queue = MagicMock()
    mock_queue.acquire_gpu_stage = AsyncMock(side_effect=["cuda:0", "cuda:1"])
    mock_queue.release_gpu_stage = MagicMock()

    with (
        patch("gateway.task_queue.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline._call_ai_service", new_callable=AsyncMock) as mock_call_ai,
        patch("gateway.pipeline._ensure_gpu_vram_for_step", new_callable=AsyncMock),
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)

        await pipeline.run_training_pipeline(
            task_id="task_wsi_stage",
            data_type="wsi",
            wsi_ids=["wsi_1"],
            preprocessing_config={"feature_extractor": "resnet50"},
            model_config={"aggregator": "abmil"},
            training_task_type="wsi_classification",
            assigned_device="cuda:6",
            patching_complete=True,
        )

    stage_calls = mock_queue.acquire_gpu_stage.await_args_list
    assert [call.kwargs["stage"] for call in stage_calls] == [
        "feature_extraction",
        "wsi_training",
    ]
    assert stage_calls[0].kwargs["required_vram_mb"] > 2000.0
    assert stage_calls[1].kwargs["required_vram_mb"] == 2000.0
    feature_payload = mock_call_ai.await_args_list[0].kwargs["payload"]
    training_payload = mock_call_ai.await_args_list[1].kwargs["payload"]
    assert feature_payload["device"] == "cuda:0"
    assert training_payload["device"] == "cuda:1"
    assert mock_queue.release_gpu_stage.call_args_list[0].args == (
        "task_wsi_stage",
        "feature_extraction",
    )


@pytest.mark.asyncio
async def test_run_training_pipeline_reselects_gpu_for_patch_classification_stage():
    """Patch classification training acquires a fresh global GPU stage."""
    pipeline = import_module("gateway.pipeline")
    mock_queue = MagicMock()
    mock_queue.acquire_gpu_stage = AsyncMock(return_value="cuda:3")
    mock_queue.release_gpu_stage = MagicMock()

    with (
        patch("gateway.task_queue.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline._call_ai_service", new_callable=AsyncMock) as mock_call_ai,
        patch("gateway.pipeline._ensure_gpu_vram_for_step", new_callable=AsyncMock),
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status=TaskStatus.TRAINING, progress=50))
        mock_repo.update_status = AsyncMock()

        await pipeline.run_training_pipeline(
            task_id="task_patch_cls",
            data_type="patch",
            wsi_ids=["patch_1"],
            preprocessing_config={"feature_extractor": "resnet50"},
            model_config={"classifier": "linear", "batch_size": 32},
            training_task_type="patch_classification",
            assigned_device="cuda:6",
        )

    mock_queue.acquire_gpu_stage.assert_awaited_once()
    acquire_call = mock_queue.acquire_gpu_stage.await_args
    assert acquire_call.kwargs["stage"] == "patch_classification"
    assert mock_call_ai.await_args is not None
    assert mock_call_ai.await_args.kwargs["payload"]["device"] == "cuda:3"
    mock_queue.release_gpu_stage.assert_called_once_with(
        "task_patch_cls",
        "patch_classification",
    )


@pytest.mark.asyncio
async def test_run_training_pipeline_reselects_gpu_for_patch_segmentation_stage():
    """Patch segmentation training acquires a fresh global GPU stage."""
    pipeline = import_module("gateway.pipeline")
    mock_queue = MagicMock()
    mock_queue.acquire_gpu_stage = AsyncMock(return_value="cuda:4")
    mock_queue.release_gpu_stage = MagicMock()

    segmentation_dataset = {
        "train": {"annotations_path": "/tmp/train.json"},
        "val": {"annotations_path": "/tmp/val.json"},
        "test": {"annotations_path": "/tmp/test.json"},
    }

    with (
        patch("gateway.task_queue.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline._call_ai_service", new_callable=AsyncMock) as mock_call_ai,
        patch("gateway.pipeline._ensure_gpu_vram_for_step", new_callable=AsyncMock),
        patch(
            "gateway.pipeline._load_segmentation_training_dataset_inputs",
            new_callable=AsyncMock,
            return_value=([{"wsi_id": "patch_1", "dataset_id": "ds_1", "wsi_path": "/tmp/p1.png"}], [{"images": [1]}], {"train": ["patch_1"], "val": [], "test": []}),
        ),
        patch(
            "gateway.pipeline._prepare_segmentation_training_dataset_async",
            new_callable=AsyncMock,
            return_value=(segmentation_dataset, 2),
        ),
        patch(
            "gateway.pipeline._generate_patch_segmentation_visualizations",
            new_callable=AsyncMock,
        ),
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock())
        )
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status=TaskStatus.TRAINING, progress=50))
        mock_repo.update_status = AsyncMock()
        mock_repo.update_preprocessing_config = AsyncMock()

        await pipeline.run_training_pipeline(
            task_id="task_patch_seg",
            data_type="patch",
            wsi_ids=["patch_1"],
            preprocessing_config={"split_config": {"seed": 7}},
            model_config={"architecture": "unet", "backbone": "resnet50", "batch_size": 8},
            training_task_type="patch_segmentation",
            assigned_device="cuda:6",
        )

    mock_queue.acquire_gpu_stage.assert_awaited_once()
    acquire_call = mock_queue.acquire_gpu_stage.await_args
    assert acquire_call.kwargs["stage"] == "patch_segmentation"
    assert mock_call_ai.await_args is not None
    assert mock_call_ai.await_args.kwargs["payload"]["device"] == "cuda:4"
    mock_queue.release_gpu_stage.assert_called_once_with(
        "task_patch_seg",
        "patch_segmentation",
    )


@pytest.mark.asyncio
async def test_run_patching_then_submit_cancellation():
    """On CancelledError during patching: deregisters from queue manager and re-raises."""
    task_id = "test_cancel"
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1"],
        "preprocessing_config": {},
    }

    mock_queue = MagicMock()
    mock_queue.deregister_patching_task = MagicMock()

    with (
        patch(
            "gateway.pipeline.run_patching_stage", side_effect=asyncio.CancelledError
        ),
        patch("gateway.task_queue.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.safe_session") as mock_safe_session,
    ):
        mock_task = MagicMock(status=TaskStatus.PATCHING)
        mock_repo.get_by_id = AsyncMock(return_value=mock_task)
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe_session.return_value = ctx

        run_patching_then_submit = import_module(
            "gateway.pipeline"
        ).run_patching_then_submit

        with pytest.raises(asyncio.CancelledError):
            await run_patching_then_submit(task_id, pipeline_kwargs)

    mock_queue.deregister_patching_task.assert_called_once_with(task_id)
