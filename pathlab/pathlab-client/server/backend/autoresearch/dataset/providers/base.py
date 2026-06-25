"""Provider interface for dataset acquisition.

A DatasetProvider knows how to fetch the bytes of a dataset described by
a DatasetRecord. Providers MUST NOT raise on network/auth/policy failures —
they return a structured DownloadResult so the acquisition service can
record it as a manifest entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..types import DatasetRecord


@dataclass
class DownloadResult:
    """What a provider returns from .download().

    Statuses:
      - "downloaded": files are on disk under raw_root.
      - "skipped_policy": refused before download (e.g. landing-page URL).
      - "skipped_unsupported": provider can't handle this kind.
      - "failed": tried but errored (network, auth, parse).
    """
    status: str
    raw_root: Path
    files: list[Path] = field(default_factory=list)
    checksum_sha256: str = ""
    reason: str = ""


class DatasetProvider(Protocol):
    provider_name: str

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Return the record possibly enriched with metadata (size, license).

        Default behavior (when probing isn't worth a network call): return
        the record unchanged.
        """
        ...

    def download(
        self,
        record: DatasetRecord,
        target_dir: Path,
        progress: Any | None = None,
    ) -> DownloadResult:
        """Fetch the dataset bytes into target_dir; return a DownloadResult.
        Must NOT raise on network/auth/policy failures.
        """
        ...
