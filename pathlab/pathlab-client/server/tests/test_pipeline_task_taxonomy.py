import asyncio
from importlib import import_module

import pytest

pipeline = import_module("gateway.pipeline")


def test_training_pipeline_task_family_accepts_canonical_task_ids():
    assert pipeline._training_task_family("wsi_survival") == "survival"
    assert pipeline._training_task_family("patch_segmentation") == "segmentation"
    assert pipeline._training_task_family("patch_classification") == "classification"
    assert pipeline._training_task_family("wsi_classification") == "classification"


def test_training_pipeline_task_family_raises_on_legacy_values():
    with pytest.raises(ValueError, match="unknown canonical task id: survival"):
        pipeline._training_task_family("survival")
    with pytest.raises(ValueError, match="unknown canonical task id: segmentation"):
        pipeline._training_task_family("segmentation")
    with pytest.raises(ValueError, match="unknown canonical task id: classification"):
        pipeline._training_task_family("classification")


async def _ticker(stop_event: asyncio.Event) -> int:
    ticks = 0
    while not stop_event.is_set():
        ticks += 1
        await asyncio.sleep(0)
    return ticks


async def test_prepare_segmentation_training_dataset_async_yields_event_loop(
    monkeypatch: pytest.MonkeyPatch,
):
    stop_event = asyncio.Event()

    def _blocking_prepare(*_args: object, **_kwargs: object) -> tuple[dict[str, int], int]:
        import time

        time.sleep(0.05)
        return {"classes": 1}, 1

    monkeypatch.setattr(
        pipeline,
        "_prepare_segmentation_training_dataset",
        _blocking_prepare,
    )

    ticker_task = asyncio.create_task(_ticker(stop_event))
    try:
        result = await pipeline._prepare_segmentation_training_dataset_async(
            task_id="task_1",
            wsis=[],
            coco_payloads=[],
            splits_map={},
        )
    finally:
        stop_event.set()

    ticks = await ticker_task

    assert result == ({"classes": 1}, 1)
    assert ticks > 1
