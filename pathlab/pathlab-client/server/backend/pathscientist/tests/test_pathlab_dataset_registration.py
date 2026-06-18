from __future__ import annotations

import json
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.dataset.types import DatasetManifest


def _install_registration_repository_stubs(monkeypatch):
    package = types.ModuleType("backend.database.repositories")
    package.__path__ = [str(Path(__file__).parents[2] / "database" / "repositories")]

    class _Repo:
        pass

    package.DataGroupRepository = _Repo
    package.DatasetRepository = _Repo
    package.WSIRepository = _Repo
    monkeypatch.setitem(sys.modules, "backend.database.repositories", package)

    stats = types.ModuleType("backend.database.repositories.dataset_stats")
    stats.DatasetStatsRepository = _Repo
    monkeypatch.setitem(sys.modules, "backend.database.repositories.dataset_stats", stats)


def test_register_manifest_creates_pathlab_dataset_and_wsi_rows(tmp_path, monkeypatch):
    _install_registration_repository_stubs(monkeypatch)
    from pathscientist.dataset import pathlab_registration as reg

    prepared = tmp_path / "prepared"
    wsi_dir = prepared / "WSIs"
    wsi_dir.mkdir(parents=True)
    slide_a = wsi_dir / "slide_a.tiff"
    slide_b = wsi_dir / "slide_b.svs"
    slide_a.write_bytes(b"a" * 40)
    slide_b.write_bytes(b"b" * 80)

    labels = prepared / "labels.csv"
    labels.write_text("slide_id,label\nslide_a,0\nslide_b,1\n", encoding="utf-8")
    splits = prepared / "splits.json"
    splits.write_text(
        json.dumps({"train": ["slide_a"], "val": [], "test": ["slide_b"]}),
        encoding="utf-8",
    )

    manifest = DatasetManifest(
        dataset_id="kaggle:prostate-cancer-grade-assessment",
        provider="kaggle",
        selected_for_task="mil_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(prepared),
        data_mounts={str(prepared): "/data"},
        prepared_contract={
            "task_type": "mil_classification",
            "wsi_dir": str(wsi_dir),
            "labels_file": str(labels),
            "splits_file": str(splits),
        },
        access="manual",
        status="prepared",
    )

    created = {"dataset": None, "wsi": []}
    stats = []

    class _DataGroupRepo:
        @staticmethod
        async def get_or_create(db, **kwargs):
            assert kwargs["data_type"] == "wsi"
            assert kwargs["aggregation_level"] == "file"
            assert kwargs["task_type"] == "classification"
            return type("Group", (), {"group_id": "group-1"})()

    class _DatasetRepo:
        @staticmethod
        async def get_by_name(db, name, user_id=None):
            assert name == "PANDA - Prostate cANcer graDe Assessment"
            assert user_id == "user-1"
            return created["dataset"]

        @staticmethod
        async def get_or_create(db, **kwargs):
            created["dataset"] = type(
                "Dataset",
                (),
                {"dataset_id": "dataset-1", "name": kwargs["name"]},
            )()
            return created["dataset"]

    class _WSIRepo:
        @staticmethod
        async def get_by_id(db, wsi_id):
            return None

        @staticmethod
        async def create(db, **kwargs):
            created["wsi"].append(kwargs)
            return type("WSI", (), kwargs)()

    class _StatsRepo:
        @staticmethod
        async def recompute(db, dataset_id):
            stats.append(dataset_id)

    monkeypatch.setattr(reg, "DataGroupRepository", _DataGroupRepo)
    monkeypatch.setattr(reg, "DatasetRepository", _DatasetRepo)
    monkeypatch.setattr(reg, "WSIRepository", _WSIRepo)
    monkeypatch.setattr(reg, "DatasetStatsRepository", _StatsRepo)

    result = asyncio.run(
        reg.register_manifest_with_pathlab(
            db=object(),
            manifest=manifest,
            session_id="sid",
            user_id="user-1",
        )
    )

    assert result["status"] == "registered"
    assert result["dataset_id"] == "dataset-1"
    assert result["created_wsi_count"] == 2
    assert result["skipped_wsi_count"] == 0
    assert stats == ["dataset-1"]

    rows = {row["original_filename"]: row for row in created["wsi"]}
    assert rows["slide_a.tiff"]["label"] == "0"
    assert rows["slide_a.tiff"]["split"] == "train"
    assert rows["slide_a.tiff"]["data_type"] == "wsi"
    assert rows["slide_b.svs"]["label"] == "1"
    assert rows["slide_b.svs"]["split"] == "test"


def test_register_manifest_skips_without_owner(tmp_path, monkeypatch):
    _install_registration_repository_stubs(monkeypatch)
    from pathscientist.dataset import pathlab_registration as reg

    wsi_dir = tmp_path / "prepared" / "WSIs"
    wsi_dir.mkdir(parents=True)
    (wsi_dir / "slide_a.svs").write_bytes(b"a" * 40)
    manifest = DatasetManifest(
        dataset_id="demo:slides",
        provider="local",
        selected_for_task="mil_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(tmp_path / "prepared"),
        data_mounts={},
        prepared_contract={"wsi_dir": str(wsi_dir)},
        access="public",
        status="prepared",
    )

    class _DatasetRepo:
        @staticmethod
        async def get_or_create(*args, **kwargs):
            raise AssertionError("ownerless registration must not create datasets")

    monkeypatch.setattr(reg, "DatasetRepository", _DatasetRepo)

    result = asyncio.run(
        reg.register_manifest_with_pathlab(
            db=object(),
            manifest=manifest,
            session_id="sid",
            user_id="",
        )
    )

    assert result == {"status": "skipped", "reason": "no_owner"}


def test_register_manifest_is_idempotent_for_existing_wsi_rows(tmp_path, monkeypatch):
    _install_registration_repository_stubs(monkeypatch)
    from pathscientist.dataset import pathlab_registration as reg

    wsi_dir = tmp_path / "prepared" / "WSIs"
    wsi_dir.mkdir(parents=True)
    slide = wsi_dir / "slide_a.tiff"
    slide.write_bytes(b"a" * 40)
    manifest = DatasetManifest(
        dataset_id="demo:slides",
        provider="local",
        selected_for_task="mil_classification",
        raw_root=str(tmp_path / "raw"),
        prepared_root=str(tmp_path / "prepared"),
        data_mounts={},
        prepared_contract={"wsi_dir": str(wsi_dir)},
        access="public",
        status="prepared",
    )

    existing_ids = set()
    created = []

    class _DataGroupRepo:
        @staticmethod
        async def get_or_create(db, **kwargs):
            return type("Group", (), {"group_id": "group-1"})()

    class _DatasetRepo:
        @staticmethod
        async def get_by_name(db, name, user_id=None):
            return type("Dataset", (), {"dataset_id": "dataset-1", "name": name})()

        @staticmethod
        async def get_or_create(db, **kwargs):
            raise AssertionError("existing dataset should be reused")

    class _WSIRepo:
        @staticmethod
        async def get_by_id(db, wsi_id):
            return object() if wsi_id in existing_ids else None

        @staticmethod
        async def create(db, **kwargs):
            existing_ids.add(kwargs["wsi_id"])
            created.append(kwargs)
            return type("WSI", (), kwargs)()

    class _StatsRepo:
        @staticmethod
        async def recompute(db, dataset_id):
            return None

    monkeypatch.setattr(reg, "DataGroupRepository", _DataGroupRepo)
    monkeypatch.setattr(reg, "DatasetRepository", _DatasetRepo)
    monkeypatch.setattr(reg, "WSIRepository", _WSIRepo)
    monkeypatch.setattr(reg, "DatasetStatsRepository", _StatsRepo)

    first = asyncio.run(
        reg.register_manifest_with_pathlab(
            db=object(),
            manifest=manifest,
            session_id="sid",
            user_id="user-1",
        )
    )
    second = asyncio.run(
        reg.register_manifest_with_pathlab(
            db=object(),
            manifest=manifest,
            session_id="sid",
            user_id="user-1",
        )
    )

    assert first["created_wsi_count"] == 1
    assert second["created_wsi_count"] == 0
    assert second["skipped_wsi_count"] == 1
    assert len(created) == 1
