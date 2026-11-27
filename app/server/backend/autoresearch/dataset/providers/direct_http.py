"""Direct-HTTP provider: stream a file URL into target_dir."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.common.net_guard import guarded_requests_get
from ..downloader import compute_sha256
from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)

# File extensions we consider downloadable. Anything else → landing page,
# requiring manual access — skipped at the provider level rather than
# half-attempted.
_FILE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".7z", ".h5", ".hdf5", ".svs", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".csv", ".json")


def _is_file_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    # Strip query string from the path-tail-comparison just in case.
    path = path.split("?", 1)[0]
    return path.endswith(_FILE_EXTS)


class DirectHTTPProvider:
    provider_name = "direct_http"

    def __init__(self, session=None, timeout: int = 60, chunk_size: int = 1 << 16):
        # Caller-provided sessions allow tests to monkeypatch without
        # touching the real `requests` module.
        self._session = session
        self._timeout = timeout
        self._chunk = chunk_size

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Annotate the record with provisional probe tags. NEVER upgrades access.

        Plan-2026-04-30 dataset-discovery T5 / review constraint #3:
        no live HEAD calls; record stays at whatever ``access`` it had on
        entry. The tags surface what *would* be checked if the network
        leg ran.
        """
        urls = list(record.download.urls or [])
        tag: str
        if not urls:
            tag = "probe:no_urls"
        elif any(not _is_file_url(u) for u in urls):
            tag = "probe:not_file_url"
        else:
            tag = "probe:file_url_unverified"
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    def download(self, record: DatasetRecord, target_dir: Path, progress=None) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        urls = list(record.download.urls or [])
        if not urls:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="no_urls",
            )

        non_file = [u for u in urls if not _is_file_url(u)]
        if non_file:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason=f"not_file_url:{non_file[0]}",
            )

        files: list[Path] = []
        sess = self._session or requests
        bytes_total = 0
        names = [record.download.filename or Path(urlparse(url).path).name for url in urls]
        if len(set(names)) != len(names):
            return DownloadResult(status='failed', raw_root=target_dir, reason='duplicate_download_filenames')
        if progress is not None:
            progress.start(files_total=len(urls), bytes_total=0)
        for idx, url in enumerate(urls, start=1):
            filename = record.download.filename or Path(urlparse(url).path).name
            if not filename or Path(filename).name != filename or filename in {".", ".."}:
                return DownloadResult(status="failed", raw_root=target_dir, reason="invalid_filename")
            dest = target_dir / filename
            temporary = dest.with_name(dest.name + '.partial')
            try:
                with guarded_requests_get(
                    sess,
                    url,
                    stream=True,
                    timeout=self._timeout,
                ) as r:
                    r.raise_for_status()
                    if 'text/html' in (getattr(r, 'headers', {}) or {}).get('content-type', '').lower():
                        raise ValueError('Source returned an HTML page instead of dataset bytes')
                    try:
                        file_size = int((getattr(r, "headers", {}) or {}).get("content-length") or 0)
                    except (TypeError, ValueError):
                        file_size = 0
                    if file_size:
                        bytes_total += file_size
                    if progress is not None:
                        progress.start(
                            files_total=len(urls),
                            bytes_total=bytes_total,
                        )
                        progress.start_file(
                            filename,
                            file_index=idx,
                            file_size=file_size,
                        )
                    with temporary.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=self._chunk):
                            if chunk:
                                fh.write(chunk)
                                if progress is not None:
                                    progress.update_file(len(chunk))
                    if record.download.checksum_sha256 and len(urls) == 1 and compute_sha256(temporary) != record.download.checksum_sha256.lower():
                        raise ValueError('Dataset checksum mismatch')
                    temporary.replace(dest)
                    if progress is not None:
                        progress.finish_file(bytes_written=dest.stat().st_size)
            except Exception as e:
                logger.warning("DirectHTTP download failed (%s): %s", url, e)
                return DownloadResult(
                    status="failed", raw_root=target_dir, files=files,
                    reason=f"http_error:{e}",
                )
            finally:
                temporary.unlink(missing_ok=True)
            files.append(dest)
        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
            checksum_sha256=(
                compute_sha256(files[0]) if len(files) == 1 else ""
            ),
        )
