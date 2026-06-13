"""Zenodo provider.

Plan-2026-04-30 dataset-provider-repair Task 3: when ``download.urls`` is
empty but ``download.remote_id`` is populated (record id or DOI), call
``https://zenodo.org/api/records/<id>`` to enumerate files, then delegate
to ``DirectHTTPProvider`` to stream them. Failures are structured rather
than raised.

``probe()`` stays no-network and never upgrades access — see Task 5 review
constraint.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from ..types import DatasetRecord
from .base import DownloadResult
from .direct_http import DirectHTTPProvider

logger = logging.getLogger(__name__)


_DOI_TO_ID_RE = re.compile(r"zenodo\.(\d+)$", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"^\d+$")


def _resolve_record_id(remote_id: str) -> str:
    """``"123"`` → ``"123"``. ``"10.5281/zenodo.123"`` → ``"123"``."""
    raw = (remote_id or "").strip()
    if not raw:
        return ""
    if _NUMERIC_RE.match(raw):
        return raw
    m = _DOI_TO_ID_RE.search(raw)
    if m:
        return m.group(1)
    return raw  # let the API tell us if it's invalid


class ZenodoProvider:
    provider_name = "zenodo"

    def __init__(self, session=None, timeout: int = 60):
        self._session = session
        self._timeout = timeout
        self._http = DirectHTTPProvider(session=session, timeout=timeout)

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Annotate provisional probe state. NEVER upgrades access.

        Plan-2026-04-30 dataset-discovery T5: when ``download.urls`` exists
        we delegate to ``DirectHTTPProvider.probe`` so the file-shape check
        happens once. With only DOI/remote_id, tag
        ``probe:zenodo_resolution_pending`` since the API would need to
        resolve the record into file URLs (Phase 5b territory).
        """
        urls = list(record.download.urls or [])
        if urls:
            return self._http.probe(record)
        tag = "probe:zenodo_resolution_pending"
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    def _resolve_files(self, record_id: str) -> list[tuple[str, str]]:
        """Call the Zenodo records API and return ``[(filename, url), ...]``.

        Raises on any error — the caller wraps failures into a structured
        ``DownloadResult``.
        """
        sess = self._session
        if sess is None:
            import requests
            sess = requests
        url = f"https://zenodo.org/api/records/{record_id}"
        with sess.get(url, timeout=self._timeout) as r:
            r.raise_for_status()
            payload = r.json() if hasattr(r, "json") else {}
        files = payload.get("files") or []
        out: list[tuple[str, str]] = []
        for f in files:
            if not isinstance(f, dict):
                continue
            links = f.get("links") or {}
            href = links.get("self") or links.get("download") or ""
            key = (f.get("key") or "").strip()
            if href:
                # Fall back to URL basename if no ``key``.
                name = key or Path(urlparse(href).path).name or "download.bin"
                out.append((name, href))
        return out

    def _stream_files(
        self,
        files: list[tuple[str, str]],
        target_dir: Path,
    ) -> list[Path]:
        """Stream resolved Zenodo file URLs into ``target_dir``. The API
        URLs already carry ``/files/.../content`` shape, so we don't pass
        them through the DirectHTTP file-extension gate."""
        sess = self._session
        if sess is None:
            import requests
            sess = requests
        written: list[Path] = []
        for name, url in files:
            dest = target_dir / name
            with sess.get(url, stream=True, timeout=self._timeout) as r:
                r.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
            written.append(dest)
        return written

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        urls = list(record.download.urls or [])

        # Path A: explicit urls — delegate straight to DirectHTTP.
        if urls:
            return self._http.download(record, target_dir)

        # Path B: resolve remote_id via Zenodo metadata API.
        record_id = _resolve_record_id(record.download.remote_id)
        if not record_id:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="no_urls_or_remote_id",
            )
        try:
            resolved = self._resolve_files(record_id)
        except Exception as e:
            logger.warning("Zenodo metadata resolution failed for %s: %s", record_id, e)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"zenodo_metadata_error:{e}",
            )
        if not resolved:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="zenodo_no_files",
            )
        try:
            written = self._stream_files(resolved, target_dir)
        except Exception as e:
            logger.warning("Zenodo file download failed: %s", e)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"zenodo_download_error:{e}",
            )
        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=written,
        )
