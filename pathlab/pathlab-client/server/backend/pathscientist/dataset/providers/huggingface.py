"""HuggingFace provider: snapshot_download via huggingface_hub when available."""
from __future__ import annotations

import logging
from pathlib import Path

from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)


class HuggingFaceProvider:
    provider_name = "huggingface"

    def __init__(self, snapshot_fn=None):
        # snapshot_fn is injectable for tests. When None, attempt to import
        # the real huggingface_hub.snapshot_download lazily inside .download().
        self._snapshot_fn = snapshot_fn

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        return record

    def _resolve_snapshot(self):
        if self._snapshot_fn is not None:
            return self._snapshot_fn
        try:
            from huggingface_hub import snapshot_download
            return snapshot_download
        except Exception as e:
            logger.warning("huggingface_hub not available: %s", e)
            return None

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self._resolve_snapshot()
        if snapshot is None:
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason="missing_huggingface_hub",
            )
        repo_id = record.download.remote_id
        if not repo_id:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="no_remote_id",
            )
        try:
            local_dir = snapshot(
                repo_id=repo_id,
                repo_type="dataset",
                local_dir=str(target_dir),
            )
        except Exception as e:
            logger.warning("HF snapshot_download failed for %s: %s", repo_id, e)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"hf_error:{e}",
            )
        # Walk target_dir for files (snapshot_download dumps files there).
        files = sorted(p for p in Path(local_dir).rglob("*") if p.is_file())
        return DownloadResult(
            status="downloaded", raw_root=Path(local_dir), files=files,
        )
