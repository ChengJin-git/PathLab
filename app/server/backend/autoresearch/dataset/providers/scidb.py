"""Science Data Bank (SciDB) provider.

SciDB dataset pages expose Croissant/schema.org JSON-LD with a
``distribution`` list. Each entry carries the real ``contentUrl`` download
endpoint, filename, size and often an MD5 checksum. The public download
endpoint itself is query-shaped (``/download?fileId=...``), so the generic
DirectHTTP suffix check cannot handle it safely.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import requests

from backend.common.net_guard import guarded_requests_get
from ..types import DatasetRecord
from .base import DownloadResult

logger = logging.getLogger(__name__)

_DETAIL_URL_TEMPLATE = "https://www.scidb.cn/detail?dataSetId={dataset_id}"
_JSON_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_SCIDB_DOWNLOAD_HOSTS = {"china.scidb.cn", "www.scidb.cn"}
_USER_AGENT = "AutoResearch dataset acquisition"
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class _SciDBFile:
    url: str
    name: str = ""
    md5: str = ""
    size_bytes: int = 0


def _query_value(url: str, key: str) -> str:
    try:
        values = parse_qs(urlparse(url).query).get(key) or []
    except Exception:
        return ""
    return values[0].strip() if values else ""


def _is_scidb_download_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in _SCIDB_DOWNLOAD_HOSTS
        and parsed.path.rstrip("/") == "/download"
        and bool(_query_value(url, "fileId"))
    )


def _is_scidb_detail_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in _SCIDB_DOWNLOAD_HOSTS
        and parsed.path.rstrip("/").endswith("/detail")
        and bool(_query_value(url, "dataSetId"))
    )


def _safe_filename(name: str) -> str:
    base = Path(str(name or "").strip()).name
    if base in {"", ".", ".."}:
        return ""
    return base


def _filename_from_content_disposition(header: str) -> str:
    header = header or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", header, re.IGNORECASE)
    if m:
        return _safe_filename(unquote(m.group(1).strip().strip('"')))
    m = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    if m:
        return _safe_filename(unquote(m.group(1).strip()))
    return ""


def _fallback_filename_from_url(url: str) -> str:
    file_id = _query_value(url, "fileId")
    if file_id:
        return f"{file_id}.bin"
    return _safe_filename(Path(urlparse(url).path).name) or "download.bin"


def _md5(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_content_size(value) -> int:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0
    try:
        return max(0, int(float(text)))
    except ValueError:
        pass
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?I?B?)?\s*$", text, re.I)
    if not match:
        return 0
    number = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    factors = {
        "B": 1,
        "KB": 1000,
        "MB": 1000 ** 2,
        "GB": 1000 ** 3,
        "TB": 1000 ** 4,
        "KIB": 1024,
        "MIB": 1024 ** 2,
        "GIB": 1024 ** 3,
        "TIB": 1024 ** 4,
        "K": 1000,
        "M": 1000 ** 2,
        "G": 1000 ** 3,
        "T": 1000 ** 4,
    }
    return int(number * factors.get(unit, 1))


def _json_ld_payload(page_html: str) -> dict:
    match = _JSON_LD_RE.search(page_html or "")
    if not match:
        return {}
    raw = match.group(1).strip()
    parsed = None
    for candidate in (raw, html.unescape(raw)):
        try:
            parsed = json.loads(candidate)
            break
        except Exception:
            parsed = None
    return parsed if isinstance(parsed, dict) else {}


class SciDBProvider:
    provider_name = "scidb"

    def __init__(
        self,
        session=None,
        timeout: int = 60,
        chunk_size: int = 1 << 20,
        retry_attempts: int = 5,
        retry_backoff_seconds: float = 30.0,
        retry_max_sleep_seconds: float = 300.0,
        sleep: Callable[[float], None] | None = None,
    ):
        self._session = session
        self._timeout = timeout
        self._chunk = chunk_size
        self._retry_attempts = max(0, int(retry_attempts))
        self._retry_backoff = max(0.0, float(retry_backoff_seconds))
        self._retry_max_sleep = max(0.0, float(retry_max_sleep_seconds))
        self._sleep = sleep or time.sleep

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        tag = "probe:scidb_metadata_unverified"
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    def _detail_url(self, record: DatasetRecord) -> str:
        remote_id = (record.download.remote_id or "").strip()
        if remote_id.startswith(("http://", "https://")):
            if _is_scidb_detail_url(remote_id):
                return remote_id
            remote_id = _query_value(remote_id, "dataSetId")
        if not remote_id:
            for url in record.download.urls or []:
                if _is_scidb_detail_url(url):
                    return url
                remote_id = _query_value(url, "dataSetId")
                if remote_id:
                    break
        if remote_id:
            return _DETAIL_URL_TEMPLATE.format(dataset_id=remote_id)
        return ""

    def _files_from_detail(self, detail_url: str) -> tuple[list[_SciDBFile], str]:
        sess = self._session or requests
        try:
            resp = guarded_requests_get(
                sess,
                detail_url,
                timeout=self._timeout,
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
        except Exception as e:
            return [], f"scidb_metadata_error:{e}"

        payload = _json_ld_payload(getattr(resp, "text", ""))
        distribution = payload.get("distribution") or []
        if isinstance(distribution, dict):
            distribution = [distribution]
        files: list[_SciDBFile] = []
        for row in distribution:
            if not isinstance(row, dict):
                continue
            url = str(row.get("contentUrl") or "").strip()
            if not url:
                continue
            files.append(_SciDBFile(
                url=url,
                name=_safe_filename(str(row.get("name") or "")),
                md5=str(row.get("md5") or row.get("contentMD5") or "").lower(),
                size_bytes=_parse_content_size(
                    row.get("contentSize") or row.get("size") or row.get("content_length")
                ),
            ))
        if not files:
            return [], "scidb_no_distribution_files"
        return files, ""

    def _files_from_direct_urls(self, urls: list[str]) -> list[_SciDBFile]:
        return [
            _SciDBFile(url=url)
            for url in urls
            if _is_scidb_download_url(url)
        ]

    def local_completeness(self, record: DatasetRecord, local_root: Path) -> dict:
        """Check whether a local SciDB cache contains every distribution file.

        This is intentionally a metadata/existence check, not a full MD5 pass.
        The actual download path still verifies MD5 before skipping a file.
        """
        urls = list(record.download.urls or [])
        files = self._files_from_direct_urls(urls)
        if not files:
            detail_url = self._detail_url(record)
            if not detail_url:
                return {
                    "checked": False,
                    "reason": "scidb_no_detail_url_or_remote_id",
                }
            files, reason = self._files_from_detail(detail_url)
            if reason:
                return {"checked": False, "reason": reason}

        root = Path(local_root)
        missing: list[str] = []
        zero_byte: list[str] = []
        present = 0
        expected_bytes = 0
        present_bytes = 0
        for entry in files:
            name = _safe_filename(entry.name) or _fallback_filename_from_url(entry.url)
            expected_bytes += entry.size_bytes
            candidates = [
                root / name,
                root / "WSIs" / name,
                root / "wsis" / name,
                root / "slides" / name,
                root / "images" / name,
            ]
            existing = next((p for p in candidates if p.is_file()), None)
            if existing is None:
                missing.append(name)
                continue
            size = existing.stat().st_size
            if size <= 0:
                missing.append(name)
                zero_byte.append(name)
                continue
            if entry.size_bytes and size != entry.size_bytes:
                missing.append(name)
                continue
            present += 1
            present_bytes += size

        return {
            "checked": True,
            "complete": not missing,
            "expected_files": len(files),
            "present_files": present,
            "missing_count": len(missing),
            "missing_files": missing[:20],
            "zero_byte_files": zero_byte[:20],
            "expected_bytes": expected_bytes,
            "present_bytes": present_bytes,
        }

    def _retry_sleep_seconds(self, attempt_index: int) -> float:
        if self._retry_backoff <= 0:
            return 0.0
        delay = self._retry_backoff * (2 ** max(0, attempt_index))
        if self._retry_max_sleep:
            delay = min(delay, self._retry_max_sleep)
        return delay

    def _retryable_status(self, exc: Exception) -> int:
        response = getattr(exc, "response", None)
        try:
            return int(getattr(response, "status_code", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _download_file(
        self,
        entry: _SciDBFile,
        target_dir: Path,
        *,
        progress=None,
        file_index: int = 0,
    ) -> tuple[Path | None, str]:
        sess = self._session or requests
        known_name = _safe_filename(entry.name)
        if known_name:
            dest = target_dir / known_name
            if dest.exists() and (not entry.md5 or _md5(dest) == entry.md5):
                if progress is not None:
                    progress.start_file(
                        dest.name,
                        file_index=file_index,
                        file_size=entry.size_bytes or dest.stat().st_size,
                    )
                    progress.finish_file(bytes_written=dest.stat().st_size)
                return dest, ""

        last_error = None
        for attempt in range(self._retry_attempts + 1):
            try:
                with guarded_requests_get(
                    sess,
                    entry.url,
                    stream=True,
                    timeout=self._timeout,
                    headers={"User-Agent": _USER_AGENT},
                ) as resp:
                    resp.raise_for_status()
                    name = (
                        known_name
                        or _filename_from_content_disposition(
                            getattr(resp, "headers", {}).get("content-disposition", "")
                        )
                        or _fallback_filename_from_url(entry.url)
                    )
                    dest = target_dir / name
                    if dest.exists() and (not entry.md5 or _md5(dest) == entry.md5):
                        if progress is not None:
                            progress.start_file(
                                dest.name,
                                file_index=file_index,
                                file_size=entry.size_bytes or dest.stat().st_size,
                            )
                            progress.finish_file(bytes_written=dest.stat().st_size)
                        return dest, ""
                    tmp = dest.with_name(dest.name + ".part")
                    if progress is not None:
                        progress.start_file(
                            dest.name,
                            file_index=file_index,
                            file_size=entry.size_bytes,
                        )
                    with tmp.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=self._chunk):
                            if chunk:
                                fh.write(chunk)
                                if progress is not None:
                                    progress.update_file(len(chunk))
                    if entry.md5:
                        actual = _md5(tmp)
                        if actual != entry.md5:
                            tmp.unlink(missing_ok=True)
                            return None, (
                                f"md5_mismatch:{dest.name}:"
                                f"expected={entry.md5},actual={actual}"
                            )
                    tmp.replace(dest)
                    if progress is not None:
                        progress.finish_file(bytes_written=dest.stat().st_size)
                    return dest, ""
            except Exception as e:
                last_error = e
                status = self._retryable_status(e)
                if status in _RETRY_STATUS_CODES and attempt < self._retry_attempts:
                    delay = self._retry_sleep_seconds(attempt)
                    if delay > 0:
                        logger.warning(
                            "SciDB download retry %s/%s after HTTP %s in %.1fs: %s",
                            attempt + 1,
                            self._retry_attempts,
                            status,
                            delay,
                            entry.url,
                        )
                        self._sleep(delay)
                    continue
                break
        return None, f"scidb_download_error:{last_error}"

    def download(self, record: DatasetRecord, target_dir: Path, progress=None) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        urls = list(record.download.urls or [])
        files = self._files_from_direct_urls(urls)
        if not files:
            detail_url = self._detail_url(record)
            if not detail_url:
                return DownloadResult(
                    status="skipped_policy",
                    raw_root=target_dir,
                    reason="scidb_no_detail_url_or_remote_id",
                )
            files, reason = self._files_from_detail(detail_url)
            if reason:
                return DownloadResult(
                    status="failed" if "error" in reason else "skipped_policy",
                    raw_root=target_dir,
                    reason=reason,
                )

        if progress is not None:
            progress.start(
                files_total=len(files),
                bytes_total=sum(f.size_bytes for f in files),
            )

        written: list[Path] = []
        for idx, entry in enumerate(files, start=1):
            path, reason = self._download_file(
                entry,
                target_dir,
                progress=progress,
                file_index=idx,
            )
            if reason:
                logger.warning("SciDB download failed (%s): %s", entry.url, reason)
                return DownloadResult(
                    status="failed",
                    raw_root=target_dir,
                    files=written,
                    reason=reason,
                )
            if path is not None:
                written.append(path)

        return DownloadResult(status="downloaded", raw_root=target_dir, files=written)
