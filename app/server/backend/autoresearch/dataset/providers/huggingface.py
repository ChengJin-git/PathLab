"""HuggingFace provider: list the repository, fetch only the selected files, report progress."""
from __future__ import annotations

import logging
import shutil
import threading
from fnmatch import fnmatch
from pathlib import Path

from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)

# A whole repository larger than this needs download.include: feature hubs hold many cohorts
# and encoders, and pulling all of them fills shared storage for data the study never reads.
MAX_UNSELECTED_FILES = 2000
MAX_UNSELECTED_BYTES = 50 << 30
# Free space that must remain after the download.
RESERVE_BYTES = 100 << 30
GB = 1 << 30


def _list_repo(repo_id: str) -> list[tuple[str, int]]:
    from huggingface_hub import HfApi
    return [(item.path, int(getattr(item, "size", 0) or 0))
            for item in HfApi().list_repo_tree(repo_id, repo_type="dataset", recursive=True)
            if getattr(item, "size", None) is not None]


def layout(files: list[tuple[str, int]], depth: int = 2, limit: int = 40) -> str:
    """Top folders with file counts and sizes, so a caller can choose include patterns."""
    groups: dict[str, list[int]] = {}
    for path, size in files:
        parts = path.split("/")
        key = "/".join(parts[:depth]) + ("/" if len(parts) > depth else "")
        count_size = groups.setdefault(key, [0, 0])
        count_size[0] += 1
        count_size[1] += size
    rows = sorted(groups.items(), key=lambda item: -item[1][1])
    text = "; ".join(f"{key} ({count} files, {size / GB:.1f} GB)" for key, (count, size) in rows[:limit])
    return text + (f"; ... {len(rows) - limit} more" if len(rows) > limit else "")


class HuggingFaceProvider:
    provider_name = "huggingface"

    def __init__(self, snapshot_fn=None, list_fn=None, disk_free_fn=None, poll_seconds: float = 5.0):
        # Injectable for tests; the real huggingface_hub functions are imported lazily.
        self._snapshot_fn = snapshot_fn
        self._list_fn = list_fn or _list_repo
        self._disk_free = disk_free_fn or (lambda path: shutil.disk_usage(path).free)
        self._poll = poll_seconds

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Annotate provisional probe state. NEVER upgrades access."""
        repo_id = (record.download.remote_id or "").strip()
        if not repo_id:
            tag = "probe:no_remote_id"
            if tag not in record.tags:
                record.tags.append(tag)
            return record
        unverified = "probe:hf_remote_unverified"
        if unverified not in record.tags:
            record.tags.append(unverified)
        if any((t or "").strip().lower() == "gated" for t in record.tags):
            gated = "probe:hf_gated"
            if gated not in record.tags:
                record.tags.append(gated)
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

    def select(self, record: DatasetRecord, target_dir: Path) -> tuple[list[tuple[str, int]], str]:
        """Files to fetch, or the reason nothing should be fetched."""
        repo_id = record.download.remote_id
        try:
            files = self._list_fn(repo_id)
        except Exception as e:
            return [], f"hf_error: cannot list {repo_id}: {e}"
        patterns = [p.strip().lstrip("/") for p in record.download.include if p.strip()]
        selected = [f for f in files if not patterns or any(fnmatch(f[0], p) for p in patterns)]
        size = sum(s for _, s in selected)
        if patterns and not selected:
            return [], f"include {patterns} matched no files in {repo_id}. Repository layout: {layout(files)}"
        if not patterns and (len(selected) > MAX_UNSELECTED_FILES or size > MAX_UNSELECTED_BYTES):
            return [], (f"{repo_id} has {len(selected)} files ({size / GB:.1f} GB); set download.include to the "
                        f"files this study needs. Repository layout: {layout(files)}")
        free = self._disk_free(target_dir)
        if size + RESERVE_BYTES > free:
            return [], (f"Selected files need {size / GB:.1f} GB but only {free / GB:.1f} GB is free and "
                        f"{RESERVE_BYTES / GB:.0f} GB must remain; narrow download.include or ask the user for storage.")
        return selected, ""

    def download(self, record: DatasetRecord, target_dir: Path, progress=None) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        snapshot = self._resolve_snapshot()
        if snapshot is None:
            return DownloadResult(status="failed", raw_root=target_dir, reason="missing_huggingface_hub")
        repo_id = record.download.remote_id
        if not repo_id:
            return DownloadResult(status="skipped_policy", raw_root=target_dir, reason="no_remote_id")
        selected, reason = self.select(record, target_dir)
        if reason:
            return DownloadResult(status="failed", raw_root=target_dir, reason=reason)
        paths = [path for path, _ in selected]
        total = sum(size for _, size in selected)
        if progress is not None:
            progress.start(files_total=len(paths), bytes_total=total)
        done = threading.Event()

        def report():
            while not done.wait(self._poll):
                present = [target_dir / p for p in paths if (target_dir / p).is_file()]
                progress.observe(files_done=len(present), downloaded_bytes=sum(p.stat().st_size for p in present))

        watcher = threading.Thread(target=report, daemon=True) if progress is not None else None
        if watcher:
            watcher.start()
        try:
            snapshot(repo_id=repo_id, repo_type="dataset", local_dir=str(target_dir), allow_patterns=paths)
        except Exception as e:
            logger.warning("HF snapshot_download failed for %s: %s", repo_id, e)
            return DownloadResult(status="failed", raw_root=target_dir, reason=f"hf_error:{e}")
        finally:
            done.set()
            if watcher:
                watcher.join()
        files = [target_dir / p for p in paths if (target_dir / p).is_file()]
        if progress is not None:
            progress.observe(files_done=len(files), downloaded_bytes=sum(p.stat().st_size for p in files))
        if len(files) != len(paths):
            return DownloadResult(status="failed", raw_root=target_dir,
                                  reason=f"hf_incomplete: {len(files)}/{len(paths)} selected files present")
        return DownloadResult(status="downloaded", raw_root=target_dir, files=files)
