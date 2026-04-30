"""GDCProvider — for TCGA / GDC / TCIA datasets.

Plan-2026-04-30 dataset-provider-repair Task 5: portal/project URLs do
NOT bulk-download — they require an explicit manifest or per-file
``api.gdc.cancer.gov/data/<uuid>`` URL. The factory aliases ``"tcia"``
to the same provider class so legacy seed records using
``"provider": "tcia"`` reach a meaningful adapter rather than
``no_provider:tcia``.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)


_GDC_DATA_URL_RE = re.compile(
    r"^https?://api\.gdc\.cancer\.gov/data/[^/?\s]+",
    re.IGNORECASE,
)
_GDC_PORTAL_RE = re.compile(
    r"^https?://(?:portal|www)?\.?gdc\.cancer\.gov/(?:projects|files)/",
    re.IGNORECASE,
)


def _is_gdc_data_url(url: str) -> bool:
    return bool(_GDC_DATA_URL_RE.match(url or ""))


def _filename_from_response(resp, fallback_url: str) -> str:
    """Prefer ``Content-Disposition: attachment; filename=...``; fall back to URL basename."""
    cd = ""
    headers = getattr(resp, "headers", None) or {}
    if isinstance(headers, dict):
        cd = headers.get("content-disposition", "") or headers.get("Content-Disposition", "")
    if cd:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Fallback: basename of URL.
    parsed = urlparse(fallback_url)
    base = Path(parsed.path).name or "download.bin"
    return base


class GDCProvider:
    provider_name = "gdc"

    def __init__(self, session=None, timeout: int = 60, chunk_size: int = 1 << 16):
        self._session = session
        self._timeout = timeout
        self._chunk = chunk_size

    # ----------------------------------------------------------- probe

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Annotate provisional probe state. NEVER upgrades access."""
        urls = [u for u in (record.download.urls or []) if u]
        if any(_is_gdc_data_url(u) for u in urls):
            tag = "probe:gdc_data_urls_present"
        else:
            tag = "probe:gdc_manifest_required"
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    # ----------------------------------------------------------- download

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        urls = [u for u in (record.download.urls or []) if u]
        data_urls = [u for u in urls if _is_gdc_data_url(u)]
        if not data_urls:
            # Either nothing, or only portal/project URLs.
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="gdc_manifest_required",
            )

        sess = self._session
        if sess is None:
            import requests
            sess = requests

        files: list[Path] = []
        for url in data_urls:
            try:
                with sess.get(url, stream=True, timeout=self._timeout) as r:
                    r.raise_for_status()
                    name = _filename_from_response(r, url)
                    dest = target_dir / name
                    with dest.open("wb") as fh:
                        for chunk in r.iter_content(chunk_size=self._chunk):
                            if chunk:
                                fh.write(chunk)
                    files.append(dest)
            except Exception as e:
                logger.warning("GDC download failed (%s): %s", url, e)
                return DownloadResult(
                    status="failed", raw_root=target_dir,
                    files=files,
                    reason=f"gdc_error:{e}",
                )

        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
        )
