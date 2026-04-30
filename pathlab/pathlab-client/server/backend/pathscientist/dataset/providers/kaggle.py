"""KaggleProvider — for ``kaggle_competition`` / ``kaggle_dataset`` records.

Plan-2026-04-30 dataset-provider-repair Task 4: PANDA / Kaggle datasets
need an actual provider. Implementation delegates to the ``kaggle`` CLI
via an injectable runner so unit tests don't shell out.

Safety: never auto-downloads without credentials AND never upgrades
``access``. The acquisition policy still has the final say (PANDA is
``access="manual"``, so ``download_policy="public_only"`` blocks it
before this provider ever runs).
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable

from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)


def _default_runner(cmd, cwd=None) -> tuple[int, str, str]:
    """Subprocess runner used in production; ``runner=`` in tests overrides."""
    p = subprocess.run(
        cmd, cwd=cwd, text=True, capture_output=True, check=False,
    )
    return p.returncode, p.stdout, p.stderr


class KaggleProvider:
    provider_name = "kaggle"

    def __init__(
        self,
        *,
        runner: Callable[..., tuple[int, str, str]] | None = None,
        kaggle_json_path: Path | None = None,
    ):
        self._runner = runner or _default_runner
        # Default to ``~/.kaggle/kaggle.json``; tests override with a tmp path.
        if kaggle_json_path is None:
            kaggle_json_path = Path.home() / ".kaggle" / "kaggle.json"
        self._kaggle_json_path = Path(kaggle_json_path)

    # ----------------------------------------------------------- credentials

    def _credentials_present(self) -> bool:
        env_user = (os.environ.get("KAGGLE_USERNAME") or "").strip()
        env_key = (os.environ.get("KAGGLE_KEY") or "").strip()
        if env_user and env_key:
            return True
        try:
            return self._kaggle_json_path.exists()
        except Exception:
            return False

    # ----------------------------------------------------------- probe

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Tag credential availability. NEVER upgrades access."""
        tag = (
            "probe:kaggle_credentials_present"
            if self._credentials_present()
            else "probe:kaggle_credentials_missing"
        )
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    # ----------------------------------------------------------- download

    def download(self, record: DatasetRecord, target_dir: Path) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        if not self._credentials_present():
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="missing_kaggle_credentials",
            )

        kind = (record.download.kind or "").strip()
        remote_id = (record.download.remote_id or "").strip()
        if not remote_id:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="no_remote_id",
            )

        if kind == "kaggle_competition":
            cmd = [
                "kaggle", "competitions", "download",
                "-c", remote_id,
                "-p", str(target_dir),
                "--force",
            ]
        elif kind == "kaggle_dataset":
            cmd = [
                "kaggle", "datasets", "download",
                "-d", remote_id,
                "-p", str(target_dir),
                "--force",
            ]
        else:
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason=f"kaggle_unsupported_kind:{kind or 'empty'}",
            )

        try:
            rc, out, err = self._runner(cmd, cwd=str(target_dir))
        except Exception as e:
            logger.warning("Kaggle CLI runner raised: %s", e)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"kaggle_error:{e}",
            )

        if rc != 0:
            stderr = (err or out or "").strip()
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"kaggle_error:{stderr}",
            )

        files = sorted(p for p in target_dir.rglob("*") if p.is_file())
        if not files:
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason="kaggle_no_files_after_download",
            )
        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
        )
