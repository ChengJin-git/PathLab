import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.storage.manager import StorageManager


class TestStorageManagerUploadsBoundary:
    def test_delete_wsi_files_skips_prefix_collision_paths(self, tmp_path):
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()

        collision_dir = tmp_path / "uploads_extra"
        collision_dir.mkdir()
        collision_file = collision_dir / "file.svs"
        collision_file.write_text("test")

        manager = StorageManager(str(uploads_dir))

        result = manager.delete_wsi_files(
            wsi_id="test_wsi",
            wsi_path=str(collision_file),
            mode="standard"
        )

        assert collision_file.exists()
        assert result["deleted_files"] == []
        assert result["failed"] == []

    def test_delete_wsi_files_deletes_actual_uploads_subpath(self, tmp_path):
        uploads_dir = tmp_path / "uploads"
        wsi_files = uploads_dir / "wsi_files"
        wsi_files.mkdir(parents=True)

        real_file = wsi_files / "real.svs"
        real_file.write_text("test")

        manager = StorageManager(str(uploads_dir))

        result = manager.delete_wsi_files(
            wsi_id="real_wsi",
            wsi_path=str(real_file),
            mode="standard"
        )

        assert not real_file.exists()
        assert str(real_file) in result["deleted_files"]

    def test_delete_training_task_files_skips_models_prefix_collision(self, tmp_path):
        uploads_dir = tmp_path / "uploads"
        models_dir = uploads_dir / "models"
        models_dir.mkdir(parents=True)

        collision_models = tmp_path / "uploads_extra" / "models"
        collision_models.mkdir(parents=True)
        collision_model = collision_models / "model_abc"
        collision_model.mkdir()

        manager = StorageManager(str(uploads_dir))

        result = manager.delete_training_task_files(
            task_id="test_task",
            mode="complete",
            model_paths=[str(collision_model)]
        )

        assert collision_model.exists()
        assert str(collision_model) not in result["deleted_dirs"]


class TestStorageScanUploadsBoundary:
    def test_check_external_files_sync_treats_prefix_collision_as_external(self):
        from gateway.routes.storage_scan import _check_external_files_sync

        with patch("gateway.routes.storage_scan._check_wsi_file_availability") as mock_check:
            mock_check.return_value = (True, "Available")

            wsi_data = [
                {
                    "wsi_id": "wsi_1",
                    "original_filename": "test.svs",
                    "wsi_path": "/uploads_extra/test.svs",
                    "dataset_id": "ds1",
                    "dataset_name": "Test Dataset",
                    "label": "test",
                    "associated_files": []
                }
            ]

            result = _check_external_files_sync(wsi_data, uploads_dir="/uploads")

            assert result["total_external"] == 1
            assert result["available_count"] == 1
            mock_check.assert_called_once()

    def test_check_external_files_sync_skips_actual_uploads_paths(self):
        from gateway.routes.storage_scan import _check_external_files_sync

        wsi_data = [
            {
                "wsi_id": "wsi_1",
                "original_filename": "test.svs",
                "wsi_path": "/uploads/wsi_files/test.svs",
                "dataset_id": "ds1",
                "dataset_name": "Test Dataset",
                "label": "test",
                "associated_files": []
            }
        ]

        result = _check_external_files_sync(wsi_data, uploads_dir="/uploads")

        assert result["total_external"] == 0
        assert result["available_count"] == 0

    def test_check_external_files_sync_handles_exact_uploads_root(self):
        from gateway.routes.storage_scan import _check_external_files_sync

        wsi_data = [
            {
                "wsi_id": "wsi_1",
                "original_filename": "test.svs",
                "wsi_path": "/uploads",
                "dataset_id": "ds1",
                "dataset_name": "Test Dataset",
                "label": "test",
                "associated_files": []
            }
        ]

        result = _check_external_files_sync(wsi_data, uploads_dir="/uploads")

        assert result["total_external"] == 0


class TestUploadsSourceOfTruth:
    def test_storage_manager_uses_configured_uploads_dir(self, tmp_path):
        uploads_dir = tmp_path / "custom_uploads"
        uploads_dir.mkdir()

        manager = StorageManager(str(uploads_dir))

        assert manager.uploads_dir == uploads_dir
        assert manager.coords_dir == uploads_dir / "coordinates"
        assert manager.models_dir == uploads_dir / "models"

    def test_storage_manager_update_uploads_dir_at_runtime(self, tmp_path):
        first_dir = tmp_path / "first"
        first_dir.mkdir()
        second_dir = tmp_path / "second"
        second_dir.mkdir()

        manager = StorageManager(str(first_dir))
        assert manager.uploads_dir == first_dir

        manager.set_uploads_dir(str(second_dir))
        assert manager.uploads_dir == second_dir
        assert manager.coords_dir == second_dir / "coordinates"
