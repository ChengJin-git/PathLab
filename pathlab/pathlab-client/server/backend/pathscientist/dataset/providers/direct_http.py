"""Direct-HTTP provider: stream a file URL into target_dir."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)

# File extensions we consider downloadable. Anything else → landing page,
# requiring manual access — skipped at the provider level rather than
# half-attempted.
_FILE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".7z", ".h5", ".hdf5")


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
        return record

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
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
        for url in urls:
            filename = record.download.filename or Path(urlparse(url).path).name
            dest = target_dir / filename
            try:
                with sess.get(url, stream=True, timeout=self._timeout) as r:
                    r.raise_for_status()
                    with dest.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=self._chunk):
                            if chunk:
                                fh.write(chunk)
            except Exception as e:
                logger.warning("DirectHTTP download failed (%s): %s", url, e)
                return DownloadResult(
                    status="failed", raw_root=target_dir, files=files,
                    reason=f"http_error:{e}",
                )
            files.append(dest)
        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
        )
