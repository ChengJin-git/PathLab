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

import csv
import io
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from ...runtime.kaggle_auth import build_kaggle_cli_env, kaggle_credentials_present
from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)


def _default_runner(cmd, cwd=None, env=None) -> tuple[int, str, str]:
    """Subprocess runner used in production; ``runner=`` in tests overrides."""
    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env or build_kaggle_cli_env(),
    )
    return p.returncode, p.stdout, p.stderr


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _resolve_kaggle_cli() -> str:
    """Find the Kaggle console script without relying only on PATH.

    AutoResearch often runs inside a project virtualenv whose ``bin`` dir is
    not inherited by sandbox subprocesses. Falling back to the current Python's
    sibling console script fixes that environment without requiring users to
    manually activate the venv before starting a session.
    """
    found = shutil.which("kaggle")
    if found:
        return found

    candidates = []
    virtual_env = os.getenv("VIRTUAL_ENV", "").strip()
    if virtual_env:
        candidates.append(Path(virtual_env) / "bin" / "kaggle")
    # Do not resolve symlinks before taking the parent: virtualenv Python
    # binaries often point at a shared interpreter, while the console scripts
    # live next to the symlink under ``.venv/bin``.
    candidates.append(Path(sys.executable).expanduser().parent / "kaggle")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_executable(resolved):
            return str(resolved)
    return ""


def _snapshot_files(target_dir: Path) -> tuple[int, Path | None, list[Path]]:
    files = sorted(p for p in Path(target_dir).rglob("*") if p.is_file())
    total = 0
    newest: Path | None = None
    newest_mtime = -1.0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        total += int(stat.st_size)
        if stat.st_mtime >= newest_mtime:
            newest = path
            newest_mtime = stat.st_mtime
    return total, newest, files


def _progress_payload_int(progress, key: str) -> int:
    try:
        return int(getattr(progress, "_payload", {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _parse_kaggle_file_listing(output: str) -> tuple[int, int, str]:
    """Return (bytes_total, file_count, next_page_token) from Kaggle CSV output."""
    next_token = ""
    csv_lines: list[str] = []
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Next Page Token ="):
            next_token = line.split("=", 1)[1].strip()
            continue
        csv_lines.append(raw_line)
    if not csv_lines:
        return 0, 0, next_token

    total = 0
    count = 0
    reader = csv.DictReader(io.StringIO("\n".join(csv_lines)))
    for row in reader:
        try:
            total += max(0, int(float(row.get("size") or 0)))
        except (TypeError, ValueError):
            pass
        count += 1
    return total, count, next_token


def _kaggle_files_command(
    cli: str,
    kind: str,
    remote_id: str,
    *,
    page_token: str = "",
) -> list[str]:
    if kind == "kaggle_competition":
        cmd = [cli, "competitions", "files", remote_id, "-v", "--page-size", "200"]
    else:
        cmd = [cli, "datasets", "files", remote_id, "-v", "--page-size", "200"]
    if page_token:
        cmd.extend(["--page-token", page_token])
    return cmd


def _progress_start_extra(
    remote_id: str,
    total_bytes: int,
    total_files: int,
    total_source: str,
) -> dict[str, object]:
    extra: dict[str, object] = {"remote_id": remote_id}
    if total_bytes > 0:
        extra.update({
            "total_source": total_source,
            "total_files": total_files,
        })
    return extra


def _start_progress_polling(
    progress,
    target_dir: Path,
    remote_id: str,
    *,
    total_bytes: int = 0,
    total_files: int = 0,
    total_source: str = "",
) -> Callable[[], int]:
    """Poll files produced by the Kaggle CLI and mirror bytes into progress."""
    stop_event = threading.Event()
    current_name = f"{remote_id}.zip" if remote_id else "kaggle-download"
    progress.start(
        files_total=1,
        bytes_total=total_bytes,
        extra=_progress_start_extra(remote_id, total_bytes, total_files, total_source),
    )
    progress.start_file(current_name, file_index=1, file_size=total_bytes or None)
    last_total = 0

    def loop() -> None:
        nonlocal current_name, last_total
        while not stop_event.wait(1.0):
            total, newest, _files = _snapshot_files(target_dir)
            if newest is not None and current_name.endswith(".zip") and current_name.startswith(remote_id):
                current_name = newest.name
                progress.start_file(
                    current_name,
                    file_index=1,
                    file_size=_progress_payload_int(progress, "bytes_total") or None,
                )
                last_total = 0
            delta = max(0, total - last_total)
            if delta:
                progress.update_file(delta)
                last_total = total

    thread = threading.Thread(
        target=loop,
        name=f"autoresearch-kaggle-progress-{remote_id or 'download'}",
        daemon=True,
    )
    thread.start()

    def stop() -> int:
        nonlocal last_total
        stop_event.set()
        thread.join(timeout=2.0)
        total, newest, _files = _snapshot_files(target_dir)
        if newest is not None and newest.name != current_name:
            progress.start_file(
                newest.name,
                file_index=1,
                file_size=_progress_payload_int(progress, "bytes_total") or None,
            )
            last_total = 0
        delta = max(0, total - last_total)
        if delta:
            progress.update_file(delta)
            last_total = total
        return total

    return stop


def _finish_progress(progress, status: str, reason: str, target_dir: Path) -> None:
    if progress is None:
        return
    total, newest, files = _snapshot_files(target_dir)
    if files:
        if newest is not None:
            progress.start_file(
                newest.name,
                file_index=1,
                file_size=_progress_payload_int(progress, "bytes_total") or None,
            )
        progress.finish_file(bytes_written=total)
    progress.finish(status, reason=reason)


class KaggleProvider:
    provider_name = "kaggle"

    def __init__(
        self,
        *,
        runner: Callable[..., tuple[int, str, str]] | None = None,
        kaggle_json_path: Path | None = None,
        kaggle_cli_path: str | Path | None = None,
    ):
        self._runner = runner or _default_runner
        self._runner_is_default = runner is None
        self._kaggle_cli_path = (
            Path(kaggle_cli_path).expanduser() if kaggle_cli_path else None
        )
        # Default to ``~/.kaggle/kaggle.json``; tests override with a tmp path.
        if kaggle_json_path is None:
            kaggle_json_path = Path.home() / ".kaggle" / "kaggle.json"
        self._kaggle_json_path = Path(kaggle_json_path)

    # ----------------------------------------------------------- credentials

    def _credentials_present(self) -> bool:
        return kaggle_credentials_present(self._kaggle_json_path)

    def _cli_path(self) -> str:
        if self._kaggle_cli_path is not None:
            path = self._kaggle_cli_path
            return str(path) if _is_executable(path) else ""
        return _resolve_kaggle_cli()

    def _run_cli(
        self,
        cmd: list[str],
        *,
        target_dir: Path,
        env: dict[str, str],
    ) -> tuple[int, str, str]:
        try:
            return self._runner(cmd, cwd=str(target_dir), env=env)
        except TypeError:
            # Backward-compatible path for older unit-test runners that
            # only accept ``cmd`` and ``cwd``.
            return self._runner(cmd, cwd=str(target_dir))

    def _estimate_total_bytes(
        self,
        *,
        cli: str,
        kind: str,
        remote_id: str,
        target_dir: Path,
        env: dict[str, str],
    ) -> tuple[int, int, str]:
        """Estimate Kaggle download total from paginated file metadata."""
        if kind not in {"kaggle_competition", "kaggle_dataset"}:
            return 0, 0, ""
        try:
            max_pages = max(1, int(os.environ.get("AUTORESEARCH_KAGGLE_TOTAL_MAX_PAGES", "200")))
        except ValueError:
            max_pages = 200

        total = 0
        count = 0
        page_token = ""
        source = "kaggle_competitions_files" if kind == "kaggle_competition" else "kaggle_datasets_files"
        for _page in range(max_pages):
            cmd = _kaggle_files_command(cli, kind, remote_id, page_token=page_token)
            try:
                rc, out, err = self._run_cli(cmd, target_dir=target_dir, env=env)
            except Exception as exc:
                logger.debug("Kaggle file listing failed: %s", exc)
                return 0, 0, ""
            if rc != 0:
                logger.debug("Kaggle file listing failed: %s", (err or out or "").strip())
                return 0, 0, ""
            page_total, page_count, next_token = _parse_kaggle_file_listing(out)
            total += page_total
            count += page_count
            if not next_token or page_count == 0:
                break
            page_token = next_token
        return total, count, source

    # ----------------------------------------------------------- probe

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Tag credential availability. NEVER upgrades access."""
        credential_tag = (
            "probe:kaggle_credentials_present"
            if self._credentials_present()
            else "probe:kaggle_credentials_missing"
        )
        cli_tag = (
            "probe:kaggle_cli_present"
            if self._cli_path()
            else "probe:kaggle_cli_missing"
        )
        for tag in (credential_tag, cli_tag):
            if tag not in record.tags:
                record.tags.append(tag)
        return record

    # ----------------------------------------------------------- download

    def download(self, record: DatasetRecord, target_dir: Path, progress=None) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        if not self._credentials_present():
            if progress is not None:
                progress.start(files_total=1)
                progress.finish("skipped_policy", reason="missing_kaggle_credentials")
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="missing_kaggle_credentials",
            )

        kind = (record.download.kind or "").strip()
        remote_id = (record.download.remote_id or "").strip()
        if not remote_id:
            if progress is not None:
                progress.start(files_total=1)
                progress.finish("skipped_policy", reason="no_remote_id")
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason="no_remote_id",
            )

        if kind == "kaggle_competition":
            cli = self._cli_path()
            if not cli:
                if self._runner_is_default:
                    if progress is not None:
                        progress.start(files_total=1, extra={"remote_id": remote_id})
                        progress.finish("failed", reason="missing_kaggle_cli")
                    return DownloadResult(
                        status="failed", raw_root=target_dir,
                        reason="missing_kaggle_cli",
                    )
                cli = "kaggle"
            cmd = [
                cli, "competitions", "download",
                "-c", remote_id,
                "-p", str(target_dir),
            ]
        elif kind == "kaggle_dataset":
            cli = self._cli_path()
            if not cli:
                if self._runner_is_default:
                    if progress is not None:
                        progress.start(files_total=1, extra={"remote_id": remote_id})
                        progress.finish("failed", reason="missing_kaggle_cli")
                    return DownloadResult(
                        status="failed", raw_root=target_dir,
                        reason="missing_kaggle_cli",
                    )
                cli = "kaggle"
            cmd = [
                cli, "datasets", "download",
                "-d", remote_id,
                "-p", str(target_dir),
            ]
        else:
            if progress is not None:
                progress.start(files_total=1, extra={"remote_id": remote_id})
                progress.finish(
                    "skipped_policy",
                    reason=f"kaggle_unsupported_kind:{kind or 'empty'}",
                )
            return DownloadResult(
                status="skipped_policy", raw_root=target_dir,
                reason=f"kaggle_unsupported_kind:{kind or 'empty'}",
            )

        env = build_kaggle_cli_env(self._kaggle_json_path)
        total_bytes, total_files, total_source = self._estimate_total_bytes(
            cli=cmd[0],
            kind=kind,
            remote_id=remote_id,
            target_dir=target_dir,
            env=env,
        )

        stop_progress = (
            _start_progress_polling(
                progress,
                target_dir,
                remote_id,
                total_bytes=total_bytes,
                total_files=total_files,
                total_source=total_source,
            )
            if progress is not None and self._runner_is_default
            else None
        )
        if progress is not None and stop_progress is None:
            progress.start(
                files_total=1,
                bytes_total=total_bytes,
                extra=_progress_start_extra(remote_id, total_bytes, total_files, total_source),
            )
            progress.start_file(
                f"{remote_id}.zip",
                file_index=1,
                file_size=total_bytes or None,
            )
        try:
            rc, out, err = self._run_cli(cmd, target_dir=target_dir, env=env)
        except Exception as e:
            logger.warning("Kaggle CLI runner raised: %s", e)
            _finish_progress(progress, "failed", f"kaggle_error:{e}", target_dir)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"kaggle_error:{e}",
            )
        finally:
            if stop_progress is not None:
                stop_progress()

        if rc != 0:
            stderr = (err or out or "").strip()
            _finish_progress(progress, "failed", f"kaggle_error:{stderr}", target_dir)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason=f"kaggle_error:{stderr}",
            )

        files = sorted(p for p in target_dir.rglob("*") if p.is_file())
        if not files:
            _finish_progress(progress, "failed", "kaggle_no_files_after_download", target_dir)
            return DownloadResult(
                status="failed", raw_root=target_dir,
                reason="kaggle_no_files_after_download",
            )
        _finish_progress(progress, "downloaded", "", target_dir)
        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
        )
