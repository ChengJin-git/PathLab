"""GDCProvider — for TCGA / GDC / TCIA datasets.

The adapter supports local GDC manifest TSVs, explicit
``api.gdc.cancer.gov/data/<uuid>`` URLs, and TCGA project ids such as
``TCGA-BRCA`` by querying the GDC ``/files`` API for slide images. The
factory aliases ``"tcia"`` to this provider so legacy seed records using
``"provider": "tcia"`` reach a meaningful adapter.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

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
_TCGA_PROJECT_RE = re.compile(r"\bTCGA-[A-Z0-9]{2,12}\b", re.IGNORECASE)
_GDC_FILES_URL = "https://api.gdc.cancer.gov/files"
_GDC_DATA_URL = "https://api.gdc.cancer.gov/data/{file_id}"
_GDC_FIELDS = (
    "file_id,file_name,file_size,data_type,data_format,experimental_strategy,"
    "cases.case_id,cases.submitter_id,cases.project.project_id"
)
_SLIDE_SUFFIXES = (".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn")
_TCGA_DIAGNOSTIC_SLIDE_RE = re.compile(
    r"(?:^|-)DX\d+(?:[.-])",
    re.IGNORECASE,
)


def _is_gdc_data_url(url: str) -> bool:
    return bool(_GDC_DATA_URL_RE.match(url or ""))


def _filename_from_response(resp, fallback_url: str, preferred: str = "") -> str:
    """Prefer ``Content-Disposition: attachment; filename=...``; fall back to URL basename."""
    cd = ""
    headers = getattr(resp, "headers", None) or {}
    if isinstance(headers, dict):
        cd = headers.get("content-disposition", "") or headers.get("Content-Disposition", "")
    if cd:
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    if preferred:
        return Path(preferred).name
    # Fallback: basename of URL.
    parsed = urlparse(fallback_url)
    base = Path(parsed.path).name or "download.bin"
    return base


def _is_slide_name(name: str) -> bool:
    return (name or "").lower().endswith(_SLIDE_SUFFIXES)


def _is_diagnostic_slide_name(name: str) -> bool:
    """Return True for TCGA diagnostic WSI filenames, e.g. ``...-DX1....svs``."""
    return bool(_TCGA_DIAGNOSTIC_SLIDE_RE.search(name or ""))


def _coerce_int(value) -> int:
    try:
        if value is None or value == "":
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_float(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _env_int(name: str, default: int) -> int:
    return _coerce_int(os.getenv(name, default)) or default


def _env_float(name: str, default: float) -> float:
    value = _coerce_float(os.getenv(name, default))
    return value if value > 0 else default


def _project_id_from_record(record: DatasetRecord) -> str:
    """Infer TCGA project id from remote_id, URLs, dataset_id, name, or tags."""
    candidates = [
        record.download.remote_id or "",
        record.dataset_id or "",
        record.name or "",
        " ".join(record.tags or []),
    ]
    candidates.extend(record.download.urls or [])
    for text in candidates:
        m = _TCGA_PROJECT_RE.search(str(text or ""))
        if m:
            return m.group(0).upper()
    return ""


def _local_manifest_path(raw: str) -> Path | None:
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path)).expanduser()
    elif parsed.scheme:
        return None
    else:
        path = Path(raw).expanduser()
    return path if path.is_file() else None


def _read_gdc_manifest(path: Path) -> list[dict]:
    """Read a GDC manifest TSV into download entries."""
    entries: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            file_id = (
                row.get("id")
                or row.get("file_id")
                or row.get("uuid")
                or ""
            ).strip()
            if not file_id:
                continue
            filename = (
                row.get("filename")
                or row.get("file_name")
                or row.get("name")
                or file_id
            ).strip()
            entries.append({
                "file_id": file_id,
                "file_name": filename,
                "file_size": _coerce_int(row.get("size") or row.get("file_size")),
            })
    return entries


class GDCProvider:
    provider_name = "gdc"

    def __init__(
        self,
        session=None,
        timeout: int = 60,
        chunk_size: int = 1 << 16,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ):
        self._session = session
        self._timeout = timeout
        self._chunk = chunk_size
        self._max_retries = max(
            1,
            int(max_retries)
            if max_retries is not None
            else _env_int("PATHSCIENTIST_GDC_MAX_RETRIES", 3),
        )
        self._retry_backoff_seconds = (
            max(0.0, float(retry_backoff_seconds))
            if retry_backoff_seconds is not None
            else _env_float("PATHSCIENTIST_GDC_RETRY_BACKOFF_SECONDS", 0.0)
        )

    # ----------------------------------------------------------- probe

    def probe(self, record: DatasetRecord) -> DatasetRecord:
        """Annotate provisional probe state. NEVER upgrades access."""
        urls = [u for u in (record.download.urls or []) if u]
        if any(_is_gdc_data_url(u) for u in urls):
            tag = "probe:gdc_data_urls_present"
        elif (record.download.kind or "") == "gdc_manifest":
            tag = "probe:gdc_manifest_present"
        elif _project_id_from_record(record):
            tag = "probe:gdc_project_query_available"
        else:
            tag = "probe:gdc_manifest_required"
        if tag not in record.tags:
            record.tags.append(tag)
        return record

    # ----------------------------------------------------------- download

    def download(self, record: DatasetRecord, target_dir: Path, progress=None) -> DownloadResult:
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        urls = [u for u in (record.download.urls or []) if u]
        manifest_entries = self._entries_from_manifest_urls(record)
        if manifest_entries:
            return self._download_entries(
                manifest_entries,
                target_dir,
                progress=progress,
            )

        data_urls = [u for u in urls if _is_gdc_data_url(u)]
        if data_urls:
            return self._download_urls(data_urls, target_dir, progress=progress)

        project_id = _project_id_from_record(record)
        if project_id:
            try:
                entries = self._query_project_slide_files(project_id)
            except Exception as e:
                logger.warning("GDC project query failed (%s): %s", project_id, e)
                return DownloadResult(
                    status="failed",
                    raw_root=target_dir,
                    reason=f"gdc_query_error:{e}",
                )
            if not entries:
                return DownloadResult(
                    status="failed",
                    raw_root=target_dir,
                    reason=f"gdc_no_slide_files:{project_id}",
                )
            return self._download_entries(
                entries,
                target_dir,
                progress=progress,
            )

        # Either nothing, or only portal/files URLs without a project id.
        return DownloadResult(
            status="skipped_policy", raw_root=target_dir,
            reason="gdc_manifest_required",
        )

    # ----------------------------------------------------------- helpers

    def _get_session(self):
        sess = self._session
        if sess is None:
            import requests
            sess = requests
        return sess

    def _auth_headers(self) -> dict[str, str]:
        token = os.getenv("GDC_TOKEN", "").strip()
        token_path = os.getenv("GDC_TOKEN_PATH", "").strip()
        if not token and token_path:
            try:
                token = Path(token_path).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        return {"X-Auth-Token": token} if token else {}

    def _entries_from_manifest_urls(self, record: DatasetRecord) -> list[dict]:
        entries: list[dict] = []
        kind = (record.download.kind or "").strip().lower()
        for raw in record.download.urls or []:
            path = _local_manifest_path(raw)
            if path is None:
                continue
            if kind != "gdc_manifest" and path.suffix.lower() not in {".txt", ".tsv"}:
                continue
            entries.extend(_read_gdc_manifest(path))
        return entries

    def _query_project_slide_files(self, project_id: str) -> list[dict]:
        sess = self._get_session()
        headers = self._auth_headers()
        entries: list[dict] = []
        offset = 0
        page_size = 1000

        while True:
            query = {
                "filters": {
                    "op": "and",
                    "content": [
                        {
                            "op": "in",
                            "content": {
                                "field": "cases.project.project_id",
                                "value": [project_id],
                            },
                        },
                        {
                            "op": "in",
                            "content": {
                                "field": "data_type",
                                "value": ["Slide Image"],
                            },
                        },
                    ],
                },
                "fields": _GDC_FIELDS,
                "format": "JSON",
                "size": page_size,
                "from": offset,
                "sort": "file_name:asc",
            }
            resp = sess.post(
                _GDC_FILES_URL,
                json=query,
                timeout=self._timeout,
                headers=headers or None,
            )
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else {}
            data = data or {}
            hits = data.get("hits") or []
            for hit in hits:
                file_id = str(hit.get("file_id") or hit.get("id") or "").strip()
                file_name = str(hit.get("file_name") or hit.get("filename") or file_id).strip()
                data_type = str(hit.get("data_type") or "").strip().lower()
                if not file_id:
                    continue
                if data_type != "slide image" and not _is_slide_name(file_name):
                    continue
                if not _is_diagnostic_slide_name(file_name):
                    continue
                entries.append({
                    "file_id": file_id,
                    "file_name": file_name,
                    "file_size": _coerce_int(hit.get("file_size") or hit.get("size")),
                })

            pagination = data.get("pagination") or {}
            count = _coerce_int(pagination.get("count"))
            total = _coerce_int(pagination.get("total"))
            if count <= 0:
                break
            offset += count
            if total and offset >= total:
                break
        return entries

    def local_completeness(self, record: DatasetRecord, local_root: Path) -> dict:
        """Check whether a local TCGA/GDC cache already has all diagnostic slides.

        Project-id records are filtered to diagnostic ``DX*`` slide images, matching
        ``download()``. This lets acquisition skip a redundant download when the
        unified data root already contains the complete diagnostic WSI cohort.
        """
        entries = self._entries_from_manifest_urls(record)
        if not entries:
            project_id = _project_id_from_record(record)
            if not project_id:
                return {"checked": False, "reason": "gdc_no_project_id"}
            try:
                entries = self._query_project_slide_files(project_id)
            except Exception as e:
                logger.warning("GDC local completeness query failed (%s): %s", project_id, e)
                return {"checked": False, "reason": f"gdc_query_error:{e}"}
        if not entries:
            return {"checked": False, "reason": "gdc_no_slide_files"}

        root = Path(local_root)
        missing: list[str] = []
        zero_byte: list[str] = []
        size_mismatch: list[str] = []
        present = 0
        expected_bytes = 0
        present_bytes = 0

        for entry in entries:
            name = Path(str(entry.get("file_name") or entry.get("file_id") or "")).name
            if not name:
                continue
            expected_size = _coerce_int(entry.get("file_size"))
            expected_bytes += expected_size
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
            if expected_size and size != expected_size:
                missing.append(name)
                size_mismatch.append(name)
                continue
            present += 1
            present_bytes += size

        return {
            "checked": True,
            "complete": not missing,
            "expected_files": len(entries),
            "present_files": present,
            "missing_count": len(missing),
            "missing_files": missing[:20],
            "zero_byte_files": zero_byte[:20],
            "size_mismatch_files": size_mismatch[:20],
            "expected_bytes": expected_bytes,
            "present_bytes": present_bytes,
        }

    def _download_urls(self, data_urls: list[str], target_dir: Path, progress=None) -> DownloadResult:
        entries = [
            {
                "url": url,
                "file_id": Path(urlparse(url).path).name,
                "file_name": "",
                "file_size": 0,
            }
            for url in data_urls
        ]
        return self._download_entries(entries, target_dir, progress=progress)

    def _existing_file_complete(self, path: Path, expected_size: int) -> bool:
        if expected_size <= 0:
            return False
        try:
            return path.is_file() and path.stat().st_size == expected_size
        except OSError:
            return False

    def _cleanup_part_file(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("GDC partial cleanup failed: %s", path)

    def _finish_skipped_file(
        self,
        *,
        progress,
        name: str,
        idx: int,
        file_size: int,
        dest: Path,
    ) -> None:
        if progress is None:
            return
        size = file_size
        if size <= 0:
            try:
                size = dest.stat().st_size
            except OSError:
                size = 0
        progress.start_file(name, file_index=idx, file_size=file_size)
        progress.finish_file(bytes_written=size)

    def _download_entries(self, entries: list[dict], target_dir: Path, progress=None) -> DownloadResult:
        sess = self._get_session()
        headers = self._auth_headers()
        files: list[Path] = []
        bytes_total = sum(_coerce_int(e.get("file_size")) for e in entries)
        if progress is not None:
            progress.start(files_total=len(entries), bytes_total=bytes_total)

        for idx, entry in enumerate(entries, start=1):
            file_id = str(entry.get("file_id") or "").strip()
            url = str(entry.get("url") or "").strip() or _GDC_DATA_URL.format(file_id=file_id)
            preferred = str(entry.get("file_name") or "").strip()
            file_size = _coerce_int(entry.get("file_size"))
            if preferred:
                existing = target_dir / Path(preferred).name
                if self._existing_file_complete(existing, file_size):
                    self._finish_skipped_file(
                        progress=progress,
                        name=existing.name,
                        idx=idx,
                        file_size=file_size,
                        dest=existing,
                    )
                    files.append(existing)
                    continue

            downloaded = False
            last_error = ""
            for attempt in range(1, self._max_retries + 1):
                part_path: Path | None = None
                try:
                    with sess.get(
                        url,
                        stream=True,
                        timeout=self._timeout,
                        headers=headers or None,
                    ) as r:
                        r.raise_for_status()
                        name = _filename_from_response(r, url, preferred)
                        dest = target_dir / name
                        if self._existing_file_complete(dest, file_size):
                            self._finish_skipped_file(
                                progress=progress,
                                name=name,
                                idx=idx,
                                file_size=file_size,
                                dest=dest,
                            )
                            files.append(dest)
                            downloaded = True
                            break
                        if progress is not None:
                            progress.start_file(name, file_index=idx, file_size=file_size)
                        part_path = dest.with_name(dest.name + ".part")
                        self._cleanup_part_file(part_path)
                        with part_path.open("wb") as fh:
                            for chunk in r.iter_content(chunk_size=self._chunk):
                                if chunk:
                                    fh.write(chunk)
                                    if progress is not None:
                                        progress.update_file(len(chunk))
                        written = part_path.stat().st_size
                        if file_size > 0 and written != file_size:
                            raise IOError(
                                f"size_mismatch:expected={file_size},actual={written}"
                            )
                        part_path.replace(dest)
                        if progress is not None:
                            progress.finish_file(bytes_written=dest.stat().st_size)
                        files.append(dest)
                        downloaded = True
                        break
                except Exception as e:
                    last_error = str(e)
                    self._cleanup_part_file(part_path)
                    logger.warning(
                        "GDC download failed (%s) attempt %s/%s: %s",
                        url,
                        attempt,
                        self._max_retries,
                        e,
                    )
                    if attempt < self._max_retries and self._retry_backoff_seconds > 0:
                        time.sleep(self._retry_backoff_seconds)

            if not downloaded:
                return DownloadResult(
                    status="failed", raw_root=target_dir,
                    files=files,
                    reason=f"gdc_error:{last_error}",
                )

        return DownloadResult(
            status="downloaded", raw_root=target_dir, files=files,
        )
