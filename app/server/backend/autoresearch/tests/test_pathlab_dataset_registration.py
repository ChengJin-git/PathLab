from __future__ import annotations

import json
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.dataset.types import DatasetManifest


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalarResult(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.commits = 0
        self.bind=types.SimpleNamespace(dialect=types.SimpleNamespace(name='postgresql'))

    async def execute(self, _stmt):
        return _FakeExecuteResult(self._rows)

    async def commit(self):
        self.commits += 1


def _feature_fixture(path,coords=None):
    import torch,h5py
    torch.save(torch.ones((2,4)),path)
    if coords:
        with h5py.File(coords,'w') as file:
            data=file.create_dataset('coords',data=[[0,0],[32,32]]);data.attrs['patch_size']=16


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
    from autoresearch.dataset import pathlab_registration as reg

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
            assert kwargs["task_type"] == "wsi_classification"
            return type("Group", (), {"group_id": "group-1"})()

    class _DatasetRepo:
        @staticmethod
        async def get_by_acquisition(db, **kwargs):
            return None

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


def test_register_extracted_features_uses_pathlab_view_manifest_mapping(tmp_path):
    from autoresearch.dataset.feature_registration import register_extracted_features_with_pathlab

    dataset_root = tmp_path / "Nanfang-NSCLC"
    wsi_dir = dataset_root / "wsi_files"
    features_dir = dataset_root / "features" / "virchow2"
    coords_dir = dataset_root / "coordinates"
    wsi_dir.mkdir(parents=True)
    features_dir.mkdir(parents=True)
    coords_dir.mkdir(parents=True)
    _feature_fixture(features_dir/'uuid-slide.pt',coords_dir/'uuid-slide_coords.h5')
    original_wsi = tmp_path / "tmp_test_data" / "Nanfang-NSCLC" / "WSIs" / "1025997.svs"
    original_wsi.parent.mkdir(parents=True)
    original_wsi.write_bytes(b"wsi")
    (wsi_dir / "uuid-slide.svs").symlink_to(original_wsi)
    (dataset_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(wsi_dir / "uuid-slide.svs"),
                        "wsi_path": str(original_wsi),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    row = type(
        "WSIRow",
        (),
        {
            "wsi_path": str(original_wsi),
            "wsi_id": "uuid-slide",
            "associated_files": {},
            "feature_extracted": False,
        },
    )()
    db = _FakeDb([row])

    result = asyncio.run(
        register_extracted_features_with_pathlab(
            db=db,
            features_dir=features_dir,
            wsi_dir=wsi_dir,
            extractor_name="virchow2",
            data_role="external",
        )
    )

    assert result["status"] == "registered"
    assert result["updated_wsi_count"] == 1
    assert db.commits == 1
    assert row.feature_extracted is True
    feature_info = row.associated_files["autoresearch_features"]["external"]
    assert feature_info["feature_path"] == str(features_dir / "uuid-slide.pt")
    assert feature_info["coordinates_path"] == str(coords_dir / "uuid-slide_coords.h5")
    assert feature_info["extractor_name"] == "virchow2"


def test_register_extracted_features_uses_synced_pathlab_view_manifest(tmp_path):
    from autoresearch.dataset.feature_registration import register_extracted_features_with_pathlab

    dataset_root = tmp_path / "tmp_test_data" / "Nanfang-NSCLC"
    wsi_dir = dataset_root / "WSIs"
    features_dir = dataset_root / "features" / "virchow2"
    coords_dir = dataset_root / "coordinates"
    wsi_dir.mkdir(parents=True)
    features_dir.mkdir(parents=True)
    coords_dir.mkdir(parents=True)
    _feature_fixture(features_dir/'uuid-slide.pt',coords_dir/'uuid-slide_coords.h5')
    original_wsi = wsi_dir / "1025997.svs"
    original_wsi.write_bytes(b"wsi")
    view_root = tmp_path / "uploads" / "autoresearch_nanfang"
    view_wsi_dir = view_root / "wsi_files"
    view_wsi_dir.mkdir(parents=True)
    (view_wsi_dir / "uuid-slide.svs").symlink_to(original_wsi)
    (dataset_root / "autoresearch_pathlab_view_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "uuid-slide",
                        "view_wsi_path": str(view_wsi_dir / "uuid-slide.svs"),
                        "wsi_path": str(original_wsi),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    row = type(
        "WSIRow",
        (),
        {
            "wsi_path": str(original_wsi),
            "wsi_id": "uuid-slide",
            "associated_files": {},
            "feature_extracted": False,
        },
    )()
    db = _FakeDb([row])

    result = asyncio.run(
        register_extracted_features_with_pathlab(
            db=db,
            features_dir=features_dir,
            wsi_dir=view_wsi_dir,
            extractor_name="virchow2",
            data_role="external",
        )
    )

    assert result["status"] == "registered"
    assert result["updated_wsi_count"] == 1
    assert db.commits == 1
    feature_info = row.associated_files["autoresearch_features"]["external"]
    assert feature_info["feature_path"] == str(features_dir / "uuid-slide.pt")
    assert feature_info["coordinates_path"] == str(coords_dir / "uuid-slide_coords.h5")


def test_register_extracted_features_records_no_tissue_metadata(tmp_path):
    from autoresearch.dataset.feature_registration import register_extracted_features_with_pathlab

    dataset_root = tmp_path / "Nanfang-NSCLC"
    wsi_dir = dataset_root / "wsi_files"
    features_dir = dataset_root / "features" / "virchow2"
    wsi_dir.mkdir(parents=True)
    features_dir.mkdir(parents=True)
    _feature_fixture(features_dir/'slide_a.pt')
    original_a = tmp_path / "raw" / "slide_a.svs"
    original_b = tmp_path / "raw" / "slide_b.svs"
    original_a.parent.mkdir(parents=True)
    original_a.write_bytes(b"wsi")
    original_b.write_bytes(b"wsi")
    (wsi_dir / "slide_a.svs").symlink_to(original_a)
    (wsi_dir / "slide_b.svs").symlink_to(original_b)
    (dataset_root / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": "slide_a",
                        "view_wsi_path": str(wsi_dir / "slide_a.svs"),
                        "wsi_path": str(original_a),
                    },
                    {
                        "slide_id": "slide_b",
                        "view_wsi_path": str(wsi_dir / "slide_b.svs"),
                        "wsi_path": str(original_b),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "extraction_meta.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "extractor": "virchow2",
                "results": {
                    "slide_a": {"status": "success"},
                    "slide_b": {
                        "status": "no_tissue",
                        "reason": "No detectable tissue found during tiling",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    row_a = type(
        "WSIRow",
        (),
        {"wsi_id":"slide_a","wsi_path": str(original_a), "associated_files": {}, "feature_extracted": False},
    )()
    row_b = type(
        "WSIRow",
        (),
        {"wsi_path": str(original_b), "associated_files": {}, "feature_extracted": False},
    )()
    db = _FakeDb([row_a, row_b])

    result = asyncio.run(
        register_extracted_features_with_pathlab(
            db=db,
            features_dir=features_dir,
            wsi_dir=wsi_dir,
            extractor_name="virchow2",
            data_role="internal",
        )
    )

    assert result["status"] == "registered"
    assert result["updated_wsi_count"] == 2
    feature_info = row_a.associated_files["autoresearch_features"]["internal"]
    assert feature_info["feature_path"] == str(features_dir / "slide_a.pt")
    no_tissue_info = row_b.associated_files["autoresearch_features"]["internal"]
    assert no_tissue_info["status"] == "no_tissue"
    assert no_tissue_info["reason"] == "No detectable tissue found during tiling"
    assert no_tissue_info["extractor_name"] == "virchow2"
    assert row_b.feature_extracted is False


def test_register_manifest_skips_without_owner(tmp_path, monkeypatch):
    _install_registration_repository_stubs(monkeypatch)
    from autoresearch.dataset import pathlab_registration as reg

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
    from autoresearch.dataset import pathlab_registration as reg

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
        async def get_by_acquisition(db, **kwargs):
            return type('Dataset', (), {'dataset_id':'dataset-1', 'name':'demo', 'group_id':'group-1', 'is_public':True,'data_type':'wsi','tasks':[types.SimpleNamespace(task_type='wsi_classification')],
                'acquisition_metadata':{'dataset_id':'demo:slides','provider':'local'}})()

        @staticmethod
        async def get_by_name(db, name, user_id=None):
            return type("Dataset", (), {"dataset_id": "dataset-1", "name": name})()

        @staticmethod
        async def get_or_create(db, **kwargs):
            raise AssertionError("existing dataset should be reused")

    class _WSIRepo:
        @staticmethod
        async def get_by_id(db, wsi_id):
            return type('WSI', (), {})() if wsi_id in existing_ids else None

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
