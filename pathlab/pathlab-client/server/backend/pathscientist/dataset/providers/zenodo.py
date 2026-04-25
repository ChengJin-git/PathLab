"""Zenodo provider: v1 uses pre-listed urls in DownloadSpec; DOI metadata is later."""
from __future__ import annotations

import logging
from pathlib import Path

from ..types import DatasetRecord
from .base import DownloadResult
from .direct_http import DirectHTTPProvider

logger = logging.getLogger(__name__)


class ZenodoProvider:
    provider_name = "zenodo"

    def __init__(self, session=None, timeout: int = 60):
        # Reuse DirectHTTPProvider for the actual download once we have
        # file URLs. Zenodo records typically expose direct .zip URLs in
        # their JSON API (zenodo.org/api/records/<id>); for v1 we trust
        # the seed-supplied urls.
        self._http = DirectHTTPProvider(session=session, timeout=timeout)

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        return record

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
        urls = list(record.download.urls or [])
        if not urls:
            return DownloadResult(
                status="skipped_policy", raw_root=Path(target_dir),
                reason="no_urls_zenodo_doi_resolution_pending",
            )
        return self._http.download(record, target_dir)
