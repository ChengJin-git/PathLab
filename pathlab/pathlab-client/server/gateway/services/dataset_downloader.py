"""
Dataset Download Service

Unified downloader supporting HuggingFace, Kaggle, GEO, and generic URL sources.
Downloads are managed in-memory (not persisted to database) — tasks are lost on restart.
"""
import asyncio
import json
import os
import shutil
import time
import uuid
import zipfile
import tarfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from backend.common import get_logger

logger = get_logger("DatasetDownloader")


# =============================================================================
# Models
# =============================================================================

class SourceType(str, Enum):
    HUGGINGFACE = "huggingface"
    KAGGLE = "kaggle"
    GEO = "geo"
    ZENODO = "zenodo"
    URL = "url"


class DownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadedFile(BaseModel):
    filename: str
    size: int
    path: str


class DownloadProgress(BaseModel):
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0  # bytes/sec
    current_file: str = ""
    files_done: int = 0
    files_total: int = 0


class DownloadTask(BaseModel):
    task_id: str
    source_type: SourceType
    identifier: str
    status: DownloadStatus = DownloadStatus.PENDING
    progress: DownloadProgress = Field(default_factory=DownloadProgress)
    dest_dir: str = ""
    files: list[DownloadedFile] = []
    total_size: int = 0
    error: Optional[str] = None
    created_at: str = ""
    user_id: str = ""


class DownloadRequest(BaseModel):
    source_type: SourceType
    identifier: str
    token: Optional[str] = None
    subset: Optional[str] = None
    file_patterns: Optional[list[str]] = None
    kaggle_username: Optional[str] = None
    kaggle_key: Optional[str] = None


# =============================================================================
# In-memory task store
# =============================================================================

_download_tasks: dict[str, DownloadTask] = {}
_cancellation_requests: set[str] = set()
_asyncio_tasks: dict[str, asyncio.Task] = {}


def get_task(task_id: str) -> Optional[DownloadTask]:
    return _download_tasks.get(task_id)


def get_user_tasks(user_id: str) -> list[DownloadTask]:
    return [t for t in _download_tasks.values() if t.user_id == user_id]


def request_cancellation(task_id: str) -> bool:
    _cancellation_requests.add(task_id)
    # Also cancel the asyncio task if it exists
    atask = _asyncio_tasks.get(task_id)
    if atask and not atask.done():
        atask.cancel()
    return True


def is_cancelled(task_id: str) -> bool:
    return task_id in _cancellation_requests


def _clear_cancellation(task_id: str) -> None:
    _cancellation_requests.discard(task_id)


def _meta_path(dest_dir: str) -> Path:
    return Path(dest_dir) / "_meta.json"


def _save_meta(task: DownloadTask) -> None:
    """Save task metadata alongside downloaded files."""
    try:
        meta = {
            "task_id": task.task_id,
            "source_type": task.source_type.value,
            "identifier": task.identifier,
            "status": task.status.value,
            "created_at": task.created_at,
            "files": [f.model_dump() for f in task.files],
            "total_size": task.total_size,
        }
        meta_file = _meta_path(task.dest_dir)
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Failed to save meta for task {task.task_id}: {e}")


# =============================================================================
# Download implementations
# =============================================================================

async def _download_huggingface(task: DownloadTask, req: DownloadRequest) -> None:
    """Download a dataset/model from HuggingFace Hub with real-time progress."""
    import httpx
    import fnmatch
    from huggingface_hub import HfApi

    task.status = DownloadStatus.DOWNLOADING
    task.progress.current_file = "Resolving repository..."

    token = req.token or None
    repo_id = req.identifier.strip()

    # Try to list files via HF API (dataset first, then model)
    api = HfApi(token=token)
    repo_type = "dataset"
    try:
        files_info = await asyncio.to_thread(api.list_repo_tree, repo_id, repo_type=repo_type, recursive=True)
        files_info = [f for f in files_info if hasattr(f, 'size')]  # filter to files only
    except Exception:
        repo_type = "model"
        try:
            files_info = await asyncio.to_thread(api.list_repo_tree, repo_id, repo_type=repo_type, recursive=True)
            files_info = [f for f in files_info if hasattr(f, 'size')]
        except Exception as e:
            raise RuntimeError(f"HuggingFace repository not found: {repo_id}") from e

    # Apply file patterns filter
    if req.file_patterns:
        files_info = [
            f for f in files_info
            if any(fnmatch.fnmatch(f.rfilename, pat) for pat in req.file_patterns)
        ]

    if not files_info:
        raise RuntimeError(f"No files found in {repo_id}")

    task.progress.files_total = len(files_info)
    task.progress.total_bytes = sum(f.size for f in files_info)

    dest = Path(task.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # Build auth headers
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        for i, file_info in enumerate(files_info):
            if is_cancelled(task.task_id):
                return

            filename = file_info.rfilename
            download_url = f"https://huggingface.co/{repo_type}s/{repo_id}/resolve/main/{filename}"

            task.progress.current_file = filename
            task.progress.files_done = i

            await _download_single_file(client, download_url, dest / filename, task,
                                        extra_headers=headers if token else None)

    task.progress.files_done = len(files_info)
    _scan_downloaded_files(task, dest)


async def _download_kaggle(task: DownloadTask, req: DownloadRequest) -> None:
    """Download a dataset from Kaggle using the REST API with streaming."""
    import httpx
    from base64 import b64encode

    task.status = DownloadStatus.DOWNLOADING

    kaggle_username = req.kaggle_username
    kaggle_key = req.kaggle_key

    if not kaggle_username or not kaggle_key:
        raise RuntimeError("Kaggle credentials (username + key) are required. Configure in Settings.")

    # identifier format: "owner/dataset-name"
    identifier = req.identifier.strip()
    if "/" not in identifier:
        raise RuntimeError(f"Invalid Kaggle dataset: '{identifier}'. Expected format: owner/dataset-name")

    dest = Path(task.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # Kaggle API uses HTTP Basic Auth
    auth_token = b64encode(f"{kaggle_username}:{kaggle_key}".encode()).decode()
    headers = {"Authorization": f"Basic {auth_token}"}

    # Download the dataset zip via Kaggle API
    owner, dataset_name = identifier.split("/", 1)
    api_url = f"https://www.kaggle.com/api/v1/datasets/download/{owner}/{dataset_name}"
    zip_path = dest / f"{dataset_name}.zip"

    task.progress.current_file = f"{dataset_name}.zip"
    task.progress.files_total = 1

    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        await _download_single_file(client, api_url, zip_path, task,
                                    extra_headers=headers)

    # Auto-extract the zip
    if zip_path.exists():
        task.progress.current_file = "Extracting..."
        await _auto_extract(zip_path, dest)

    task.progress.files_done = 1
    _scan_downloaded_files(task, dest)


async def _download_geo(task: DownloadTask, req: DownloadRequest) -> None:
    """Download data from NCBI GEO (Gene Expression Omnibus)."""
    import httpx

    task.status = DownloadStatus.DOWNLOADING
    geo_id = req.identifier.strip().upper()

    if not geo_id.startswith("GSE") and not geo_id.startswith("GPL") and not geo_id.startswith("GSM"):
        raise RuntimeError(f"Invalid GEO accession: {geo_id}. Expected GSExxxxx, GPLxxxxx, or GSMxxxxx")

    # Download supplementary files via FTP/HTTPS
    # GEO supplementary file URL pattern
    prefix = geo_id[:5]  # e.g. GSE12 for GSE12345
    nnn = geo_id[3:]  # numeric part
    # GEO stores files in ranges: GSE1nnn for GSE1000-GSE1999
    range_dir = f"{geo_id[:3]}{nnn[:-3]}nnn" if len(nnn) > 3 else f"{geo_id[:3]}nnn"

    base_url = f"https://ftp.ncbi.nlm.nih.gov/geo/series/{range_dir}/{geo_id}"
    suppl_url = f"{base_url}/suppl/"

    dest = Path(task.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    task.progress.current_file = f"Fetching file list for {geo_id}..."

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # Try to get the supplementary file listing
        try:
            resp = await client.get(suppl_url)
            if resp.status_code != 200:
                # Try soft file as fallback
                soft_url = f"{base_url}/soft/{geo_id}_family.soft.gz"
                task.progress.current_file = f"Downloading {geo_id}_family.soft.gz..."
                await _download_single_file(client, soft_url, dest / f"{geo_id}_family.soft.gz", task)
                _scan_downloaded_files(task, dest)
                return
        except Exception:
            raise RuntimeError(f"Cannot access GEO data for {geo_id}")

        # Parse file listing from HTML directory listing
        import re
        html = resp.text
        file_links = re.findall(r'href="([^"]+)"', html)
        files_to_download = [
            f for f in file_links
            if not f.startswith("?") and not f.startswith("/") and f != "../"
        ]

        if not files_to_download:
            raise RuntimeError(f"No supplementary files found for {geo_id}")

        task.progress.files_total = len(files_to_download)

        for i, filename in enumerate(files_to_download):
            if is_cancelled(task.task_id):
                return

            file_url = f"{suppl_url}{filename}"
            task.progress.current_file = filename
            task.progress.files_done = i

            await _download_single_file(client, file_url, dest / filename, task)

        task.progress.files_done = len(files_to_download)

    _scan_downloaded_files(task, dest)


async def _download_zenodo(task: DownloadTask, req: DownloadRequest) -> None:
    """Download all files from a Zenodo record by record ID or URL."""
    import httpx
    import re

    task.status = DownloadStatus.DOWNLOADING

    # Accept record ID ("12345") or full URL ("https://zenodo.org/records/12345")
    identifier = req.identifier.strip().rstrip("/")
    match = re.search(r'(\d+)$', identifier)
    if not match:
        raise RuntimeError(f"Invalid Zenodo identifier: {identifier}. Provide a record ID (e.g. 12345) or URL.")
    record_id = match.group(1)

    dest = Path(task.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    task.progress.current_file = f"Fetching record {record_id} metadata..."

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        # Fetch record metadata
        resp = await client.get(f"https://zenodo.org/api/records/{record_id}")
        if resp.status_code == 404:
            raise RuntimeError(f"Zenodo record {record_id} not found")
        resp.raise_for_status()
        record = resp.json()

        files_list = record.get("files", [])
        if not files_list:
            raise RuntimeError(f"No files found in Zenodo record {record_id}")

        # Apply file pattern filter if provided
        if req.file_patterns:
            import fnmatch
            filtered = []
            for f in files_list:
                if any(fnmatch.fnmatch(f["key"], pat) for pat in req.file_patterns):
                    filtered.append(f)
            if filtered:
                files_list = filtered

        task.progress.files_total = len(files_list)
        task.progress.total_bytes = sum(f.get("size", 0) for f in files_list)

        for i, file_info in enumerate(files_list):
            if is_cancelled(task.task_id):
                return

            filename = file_info["key"]
            download_url = file_info["links"]["self"]

            task.progress.current_file = filename
            task.progress.files_done = i

            await _download_single_file(client, download_url, dest / filename, task)

        task.progress.files_done = len(files_list)

    _scan_downloaded_files(task, dest)


async def _download_url(task: DownloadTask, req: DownloadRequest) -> None:
    """Download a file from a generic URL with streaming."""
    import httpx

    task.status = DownloadStatus.DOWNLOADING
    url = req.identifier

    dest = Path(task.dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # Determine filename from URL
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    filename = unquote(parsed.path.split("/")[-1]) or "download"

    task.progress.current_file = filename
    task.progress.files_total = 1

    async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
        await _download_single_file(client, url, dest / filename, task)

    # Auto-extract archives
    downloaded_file = dest / filename
    if downloaded_file.exists():
        await _auto_extract(downloaded_file, dest)

    task.progress.files_done = 1
    _scan_downloaded_files(task, dest)


async def _download_single_file(
    client: Any,
    url: str,
    dest_path: Path,
    task: DownloadTask,
    extra_headers: Optional[dict[str, str]] = None,
) -> None:
    """Stream-download a single file with progress tracking."""
    import httpx

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.time()

    async with client.stream("GET", url, headers=extra_headers or {}) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        if total:
            task.progress.total_bytes = task.progress.downloaded_bytes + total

        downloaded = 0
        with open(dest_path, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                if is_cancelled(task.task_id):
                    return
                f.write(chunk)
                downloaded += len(chunk)
                task.progress.downloaded_bytes += len(chunk)

                elapsed = time.time() - start_time
                if elapsed > 0:
                    task.progress.speed = downloaded / elapsed


async def _auto_extract(filepath: Path, dest_dir: Path) -> None:
    """Auto-extract zip/tar.gz archives."""
    name = filepath.name.lower()

    def _extract():
        if name.endswith(".zip"):
            with zipfile.ZipFile(filepath, "r") as zf:
                zf.extractall(dest_dir)
            filepath.unlink()
        elif name.endswith(".tar.gz") or name.endswith(".tgz"):
            with tarfile.open(filepath, "r:gz") as tf:
                tf.extractall(dest_dir)
            filepath.unlink()
        elif name.endswith(".tar"):
            with tarfile.open(filepath, "r") as tf:
                tf.extractall(dest_dir)
            filepath.unlink()

    if name.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
        await asyncio.to_thread(_extract)


def _scan_downloaded_files(task: DownloadTask, directory: Path) -> None:
    """Scan directory and populate task.files list."""
    files = []
    total_size = 0
    for f in sorted(directory.rglob("*")):
        if f.is_file() and f.name != "_meta.json":
            size = f.stat().st_size
            files.append(DownloadedFile(
                filename=str(f.relative_to(directory)),
                size=size,
                path=str(f),
            ))
            total_size += size
    task.files = files
    task.total_size = total_size


# =============================================================================
# Main download orchestrator
# =============================================================================

_DOWNLOADERS = {
    SourceType.HUGGINGFACE: _download_huggingface,
    SourceType.KAGGLE: _download_kaggle,
    SourceType.GEO: _download_geo,
    SourceType.ZENODO: _download_zenodo,
    SourceType.URL: _download_url,
}


async def run_download_task(task_id: str, req: DownloadRequest) -> None:
    """Execute the download task. Called as an asyncio.Task."""
    task = _download_tasks.get(task_id)
    if not task:
        return

    try:
        downloader = _DOWNLOADERS.get(req.source_type)
        if not downloader:
            raise RuntimeError(f"Unsupported source type: {req.source_type}")

        await downloader(task, req)

        if is_cancelled(task.task_id):
            task.status = DownloadStatus.CANCELLED
            # Cleanup partial downloads
            try:
                dest = Path(task.dest_dir)
                if dest.exists():
                    shutil.rmtree(dest)
            except Exception:
                pass
        else:
            task.status = DownloadStatus.COMPLETED
            _save_meta(task)

        logger.info(f"Download task {task_id} finished: {task.status.value}")

    except asyncio.CancelledError:
        task.status = DownloadStatus.CANCELLED
        try:
            dest = Path(task.dest_dir)
            if dest.exists():
                shutil.rmtree(dest)
        except Exception:
            pass
        logger.info(f"Download task {task_id} cancelled")

    except Exception as e:
        task.status = DownloadStatus.FAILED
        task.error = str(e)
        logger.error(f"Download task {task_id} failed: {e}")

    finally:
        _clear_cancellation(task_id)
        _asyncio_tasks.pop(task_id, None)


def create_download_task(
    req: DownloadRequest,
    uploads_dir: str,
    user_id: str,
) -> DownloadTask:
    """Create a new download task and start it in the background."""
    task_id = f"dl_{uuid.uuid4().hex[:16]}"
    dest_dir = str(Path(uploads_dir) / "downloads" / task_id)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    task = DownloadTask(
        task_id=task_id,
        source_type=req.source_type,
        identifier=req.identifier,
        status=DownloadStatus.PENDING,
        dest_dir=dest_dir,
        created_at=datetime.now(timezone.utc).isoformat(),
        user_id=user_id,
    )
    _download_tasks[task_id] = task

    # Launch background asyncio task
    atask = asyncio.create_task(run_download_task(task_id, req))
    _asyncio_tasks[task_id] = atask

    return task
