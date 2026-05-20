from contextlib import asynccontextmanager
from importlib import import_module

import numpy as np
import torch
from PIL import Image

trainer_mod = import_module("backend.ai.tasks.patch_classification.trainer")
PatchClassificationTrainer = trainer_mod.PatchClassificationTrainer


class _AsyncLogger:
    async def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _ConstantModel(torch.nn.Module):
    def forward(self, x):
        return torch.tensor([[0.1, 0.9]], device=x.device)


def test_patch_training_saves_each_cam_batch_before_generating_all_cams(
    monkeypatch, tmp_path
):
    wsi_ids = [f"patch-{idx}" for idx in range(5)]
    image_paths = {}
    for idx, wsi_id in enumerate(wsi_ids):
        image_path = tmp_path / f"{wsi_id}.png"
        Image.new("RGB", (4, 4), color=(idx, idx, idx)).save(image_path)
        image_paths[wsi_id] = str(image_path)

    events = []

    class _FakeCamExtractor:
        def extract_cam(self, model, input_tensor, target_class):
            cam_count = sum(1 for event in events if event[0] == "cam") + 1
            events.append(("cam", cam_count))
            return np.full((1, 2, 2), cam_count, dtype=np.float32)

    class _FakeExtractor:
        pass

    def fake_save(_uploads_dir, _task_id, wsi_id, _result_data, **_kwargs):
        generated_cams = sum(1 for event in events if event[0] == "cam")
        events.append(("save", wsi_id, generated_cams))

    @asynccontextmanager
    async def fake_scoped_db(_session_maker):
        yield object()

    async def fake_bulk_create(_db, _records, batch_size=100):
        pass

    async def fake_update_progress(*_args, **_kwargs):
        pass

    monkeypatch.setattr(trainer_mod, "SAVE_FILE_IO_BATCH_SIZE", 2)
    monkeypatch.setattr(trainer_mod, "SAVE_FILE_IO_MAX_WORKERS", 1)
    monkeypatch.setattr(trainer_mod, "get_extractor", lambda *args, **kwargs: _FakeExtractor())
    monkeypatch.setattr(trainer_mod, "resolve_patch_resize_size", lambda *args, **kwargs: 4)
    monkeypatch.setattr(
        trainer_mod,
        "build_patch_classification_transform",
        lambda *args, **kwargs: (lambda _img: torch.ones((3, 4, 4), dtype=torch.float32)),
    )
    monkeypatch.setattr(trainer_mod, "get_cam_extractor", lambda _name: _FakeCamExtractor())
    monkeypatch.setattr(trainer_mod, "get_cam_spatial_size", lambda _name: (2, 2))
    monkeypatch.setattr(trainer_mod, "save_ai_result_artifacts", fake_save)
    monkeypatch.setattr(trainer_mod, "finalize_ai_result_artifacts", lambda *_args: None)
    monkeypatch.setattr(trainer_mod, "scoped_db", fake_scoped_db)
    monkeypatch.setattr(trainer_mod.AIResultRepository, "bulk_create", fake_bulk_create)
    monkeypatch.setattr(trainer_mod, "_safe_update_progress", fake_update_progress)
    monkeypatch.setattr(trainer_mod.Config, "get_uploads_dir", lambda: tmp_path)

    import backend.ai.utils.cam_utils as cam_utils

    monkeypatch.setattr(cam_utils, "is_cnn_extractor", lambda _name: False)

    trainer = PatchClassificationTrainer(
        task_id="task-bounded-cam",
        uploads_root=str(tmp_path),
        device="cpu",
    )

    import asyncio

    asyncio.run(
        trainer._save_training_inference_results(
            model=_ConstantModel(),
            wsi_ids=wsi_ids,
            image_paths=image_paths,
            labels={wsi_id: 1 for wsi_id in wsi_ids},
            classes=["negative", "positive"],
            task_id="task-bounded-cam",
            extractor_name="fake-extractor",
            logger=_AsyncLogger(),
            session_maker=lambda: object(),
        )
    )

    save_events = [event for event in events if event[0] == "save"]
    assert len(save_events) == len(wsi_ids)
    assert save_events[0][2] <= 2
