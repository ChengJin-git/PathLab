"""Object storage information and explicit per-image result editing.

Object deletion is owned by the transactional outbox in deletion.py. Global
statistics and reference-aware reclamation are owned by inventory.py.
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from backend.ai.result_store import AIResultStore
from .stats_mixin import StorageStatsMixin

logger = logging.getLogger(__name__)


class StorageManager(StorageStatsMixin):
    def __init__(self, uploads_dir: str):
        self.set_uploads_dir(uploads_dir)

    def set_uploads_dir(self, uploads_dir: str):
        self.uploads_dir = Path(uploads_dir)
        self.coords_dir = self.uploads_dir / "coordinates"
        self.masks_dir = self.uploads_dir / "masks"
        self.features_dir = self.uploads_dir / "features"
        self.ai_result_bundles_dir = self.uploads_dir / "ai_results_bundles"
        self.training_dir = self.uploads_dir / "training"
        self.models_dir = self.uploads_dir / "models"
        self.logs_dir = self.uploads_dir / "logs"
        self.wsi_files_dir = self.uploads_dir / "wsi_files"
        self.metadata_dir = self.uploads_dir / "metadata"

    def delete_wsi_ai_results(self, wsi_id: str, task_id: str | None = None):
        store = AIResultStore(self.uploads_dir)
        identities = (
            [task_id]
            if task_id
            else sorted({item["task_id"] for item in store.list_wsi_artifacts(wsi_id)})
        )
        deleted, failed, size = [], [], 0
        for identity in identities:
            try:
                result = store.delete_wsi_result(identity, wsi_id)
                if result["deleted"]:
                    deleted.append(str(store.bundle_path(identity)))
                    size += max(0, result["size_before"] - result["size_after"])
            except Exception as exc:
                failed.append((str(store.bundle_path(identity)), str(exc)))
        return {
            "deleted_files": deleted,
            "deleted_dirs": [],
            "failed": failed,
            "total_size": size,
            "summary": f"{len(deleted)} result bundles updated; {len(failed)} failed",
        }

    def get_wsi_storage_info(self, wsi_id: str, wsi_path: str | None = None):
        from .deletion import image_paths

        paths = image_paths(self.uploads_dir, wsi_id, wsi_path)
        features = []
        coordinates = []
        for name in paths:
            path = self.uploads_dir / name
            if name.startswith("features/") and path.suffix == ".pt" and path.exists():
                features.append(
                    {**self._get_file_info(path), "is_symlink": path.is_symlink()}
                )
            elif name.startswith("coordinates/") and path.exists():
                coordinates.append(path)
        store = AIResultStore(self.uploads_dir)
        artifacts = store.list_wsi_artifacts(wsi_id)
        bundles = {store.bundle_path(item["task_id"]) for item in artifacts}
        result = {
            "wsi_id": wsi_id,
            "wsi_file": self._get_file_info(Path(wsi_path))
            if wsi_path
            else {"exists": False, "size": 0, "path": ""},
            "coordinates": {
                "exists": bool(coordinates),
                "paths": list(map(str, coordinates)),
                "size": sum(p.lstat().st_size for p in coordinates),
                "file_count": len(coordinates),
            },
            "mask": self._get_file_info(self.masks_dir / f"{wsi_id}_mask.png"),
            "ai_results": {
                "exists": bool(artifacts),
                "path": str(self.ai_result_bundles_dir),
                "file_count": len(bundles),
                "artifact_count": len(artifacts),
                "size": sum(p.stat().st_size for p in bundles if p.exists()),
            },
            "features": features,
        }
        result["total_size"] = sum(
            result[key]["size"]
            for key in ("wsi_file", "coordinates", "mask", "ai_results")
        ) + sum(item["size"] for item in features)
        result["total_files"] = (
            int(result["wsi_file"]["exists"])
            + len(coordinates)
            + int(result["mask"]["exists"])
            + len(bundles)
            + len(features)
        )
        return result

    def get_training_task_storage_info(
        self, task_id: str, model_paths=None, quick=False
    ):
        def info(path, directory=True):
            exists = path.is_dir() if directory else path.is_file()
            stats = {"size": 0, "file_count": 0}
            if exists and not quick:
                stats = (
                    self._get_directory_stats(path)
                    if directory
                    else {"size": path.stat().st_size, "file_count": 1}
                )
            return {"path": str(path), "exists": exists, **stats}

        result = {
            "task_id": task_id,
            "quick": quick,
            "ai_results": info(
                self.ai_result_bundles_dir / f"{task_id}.zarr.zip", False
            ),
            "training_dir": info(self.training_dir / task_id),
            "training_logs": info(self.logs_dir / "training" / task_id),
            "analysis_logs": info(self.logs_dir / "analysis" / task_id),
            "models": [
                info(Path(path).parent if Path(path).is_file() else Path(path))
                for path in model_paths or []
            ],
        }
        objects = [
            result[key]
            for key in ("ai_results", "training_dir", "training_logs", "analysis_logs")
        ] + result["models"]
        result["total_size"] = sum(item["size"] for item in objects)
        result["total_files"] = sum(item["file_count"] for item in objects)
        return result

    def save_wsi_metadata(self, wsi_id, metadata):
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.metadata_dir / f"{wsi_id}.json"
        temporary = path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {**metadata, "saved_at": datetime.now(timezone.utc).isoformat()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return str(path)

    def get_wsi_metadata(self, wsi_id):
        try:
            return json.loads(
                (self.metadata_dir / f"{wsi_id}.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
