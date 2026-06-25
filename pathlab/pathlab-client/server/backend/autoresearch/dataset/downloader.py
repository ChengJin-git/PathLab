"""Download utilities for dataset acquisition.

Pure helpers used by the acquisition service (DatasetAcquisitionService):
- safe_dataset_id: turn ``hf:org/name`` into ``hf_org_name`` for a path-safe
  cache directory key.
- compute_sha256: hash a file in chunks for manifest provenance.
- extract_archive: zip / tar / tar.gz / tgz extraction with path-traversal
  guarding so a malicious archive can't escape the target dir.
"""
from __future__ import annotations

import hashlib
import logging
import re
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Replace anything that isn't [A-Za-z0-9._-] with an underscore. Slash, colon,
# space, etc. all collapse to "_" so the result is path-safe and stable.
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_dataset_id(dataset_id: str) -> str:
    """Return a path-safe form of dataset_id (filesystem-friendly)."""
    if not dataset_id:
        return "_"
    safe = _UNSAFE_RE.sub("_", dataset_id).strip("_")
    return safe or "_"


def compute_sha256(path: Path, chunk_size: int = 1 << 16) -> str:
    """Stream-hash the file at path; return hex digest."""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_within(parent: Path, child: Path) -> bool:
    """Return True iff child resolves to a path inside parent."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def extract_archive(archive_path: Path, target_dir: Path) -> list[Path]:
    """Extract archive_path into target_dir; return list of extracted file paths.

    Supports .zip, .tar, .tar.gz, .tgz. Rejects archive members whose
    resolved path would escape target_dir (path traversal protection).
    Returns ONLY regular files (not directories).
    """
    archive_path = Path(archive_path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()

    extracted: list[Path] = []

    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.infolist():
                # Skip directory entries explicitly.
                if member.is_dir():
                    continue
                dest = target_dir / member.filename
                if not _is_within(target_dir, dest):
                    logger.warning("Skipping unsafe zip member: %s", member.filename)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as dst:
                    while True:
                        chunk = src.read(1 << 16)
                        if not chunk:
                            break
                        dst.write(chunk)
                extracted.append(dest)
        return extracted

    if name.endswith((".tar", ".tar.gz", ".tgz")):
        mode = "r:gz" if name.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                dest = target_dir / member.name
                if not _is_within(target_dir, dest):
                    logger.warning("Skipping unsafe tar member: %s", member.name)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src:
                    if src is None:
                        continue
                    with dest.open("wb") as dst:
                        while True:
                            chunk = src.read(1 << 16)
                            if not chunk:
                                break
                            dst.write(chunk)
                extracted.append(dest)
        return extracted

    raise ValueError(f"Unsupported archive type: {archive_path.name}")
