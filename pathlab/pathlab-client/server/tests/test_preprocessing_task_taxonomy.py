import types

import pytest

from backend.preprocessing import main as preprocessing_main


@pytest.mark.asyncio
async def test_extract_regions_routes_canonical_patch_segmentation_to_reuse_flow(monkeypatch):
    calls: dict[str, object] = {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            calls["committed"] = True

    async def _fake_extract_segmentation_dataset(**kwargs):
        calls["dataset_id"] = kwargs["dataset_id"]
        calls["reuse_existing"] = kwargs["reuse_existing"]
        return 3

    progress_calls: list[tuple[str, object]] = []

    async def _fake_set_progress(task_id, value):
        progress_calls.append((task_id, value))

    async def _fake_clear_progress(_task_id):
        calls["cleared"] = True

    def _fake_import_module(name):
        if name == "backend.database":
            return types.SimpleNamespace(async_session_maker=lambda: FakeSession())
        if name == "backend.database.repositories":
            return types.SimpleNamespace(
                DataGroupRepository=types.SimpleNamespace(),
                DatasetRepository=types.SimpleNamespace(),
                WSIRepository=types.SimpleNamespace(),
                DatasetStatsRepository=types.SimpleNamespace(),
            )
        if name == "backend.common.progress_store":
            return types.SimpleNamespace(
                set_progress=_fake_set_progress,
                clear_progress=_fake_clear_progress,
            )
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(preprocessing_main, "import_module", _fake_import_module)
    monkeypatch.setattr(
        preprocessing_main,
        "_extract_segmentation_dataset",
        _fake_extract_segmentation_dataset,
    )

    await preprocessing_main._extract_regions_background(
        regions={"wsi-1": [{"x": 0, "y": 0, "width": 10, "height": 10}]},
        dataset_name=None,
        task_type="patch_segmentation",
        user_id="user-1",
        task_id="task-1",
        source_dataset_id="dataset-1",
    )

    assert calls["dataset_id"] == "dataset-1"
    assert calls["reuse_existing"] is True
    assert calls["committed"] is True
    assert progress_calls[0] == ("task-1", 0)
