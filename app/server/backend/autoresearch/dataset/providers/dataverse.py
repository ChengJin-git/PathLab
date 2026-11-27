"""Dataverse API acquisition, including Harvard, with source metadata preservation."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests

from backend.common.net_guard import guarded_requests_get

from ..types import DatasetRecord
from .base import DownloadResult


class DataverseProvider:
    provider_name = "dataverse"

    def __init__(self, session=None):
        self.session = session or requests

    def probe(self, record):
        return record

    def download(
        self, record: DatasetRecord, target_dir: Path, progress=None
    ) -> DownloadResult:
        try:
            parsed = urlsplit(record.source_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            if not record.download.remote_id:
                raise ValueError(
                    "Dataverse requires the persistent dataset identifier (doi:...)"
                )
            url = (
                base
                + "/api/datasets/:persistentId/?"
                + urlencode({"persistentId": record.download.remote_id})
            )
            with guarded_requests_get(self.session, url, timeout=30) as response:
                response.raise_for_status()
                version = response.json()["data"]["latestVersion"]
            fields = {
                field["typeName"]: field.get("value")
                for field in version.get("metadataBlocks", {})
                .get("citation", {})
                .get("fields", [])
            }
            if fields.get("title"):
                record.name = str(fields["title"])
            license_value = version.get("license")
            if isinstance(license_value, dict):
                record.license = license_value.get("name") or record.license
            descriptions = fields.get("dsDescription") or []
            if descriptions:
                record.description = "\n".join(
                    str(d.get("dsDescriptionValue", {}).get("value", ""))
                    for d in descriptions
                )
            files = version.get("files", [])
            if not files:
                raise ValueError("Dataverse version contains no files")
            if any(file.get("restricted") for file in files):
                record.access = "gated"
                return DownloadResult(
                    "skipped_policy",
                    target_dir,
                    reason="Restricted Dataverse files require authorized access",
                )
            target_dir.mkdir(parents=True, exist_ok=True)
            if progress:
                progress.start(
                    files_total=len(files),
                    bytes_total=sum(f["dataFile"].get("filesize", 0) for f in files),
                )
            output = []
            for index, item in enumerate(files, 1):
                info = item["dataFile"]
                name = str(info["filename"])
                folder = str(item.get("directoryLabel") or "")
                path = target_dir / folder / name
                if Path(name).name != name or not path.resolve().is_relative_to(
                    target_dir.resolve()
                ):
                    raise ValueError("Invalid Dataverse file path")
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + ".partial")
                if progress:
                    progress.start_file(
                        name, file_index=index, file_size=info.get("filesize", 0)
                    )
                checksum = info.get("checksum") or {}
                algorithm = str(checksum.get("type", "")).lower().replace("-", "")
                digest = (
                    hashlib.new(algorithm)
                    if algorithm in {"md5", "sha256", "sha1"}
                    else None
                )
                try:
                    with guarded_requests_get(
                        self.session,
                        base + f"/api/access/datafile/{int(info['id'])}",
                        stream=True,
                        timeout=60,
                    ) as response:
                        response.raise_for_status()
                        with temporary.open("wb") as stream:
                            for chunk in response.iter_content(1 << 16):
                                if chunk:
                                    stream.write(chunk)
                                    if digest:
                                        digest.update(chunk)
                                    if progress:
                                        progress.update_file(len(chunk))
                    if (
                        digest
                        and digest.hexdigest().lower() != str(checksum["value"]).lower()
                    ):
                        raise ValueError("Dataverse checksum mismatch")
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                if progress:
                    progress.finish_file(bytes_written=path.stat().st_size)
                output.append(path)
            return DownloadResult("downloaded", target_dir, files=output)
        except Exception as exc:  # noqa: BLE001 - provider boundary returns structured failure
            return DownloadResult(
                "failed", target_dir, reason=f"dataverse:{type(exc).__name__}:{exc}"
            )
