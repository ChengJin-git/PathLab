"""Vendor pinned upstream skill packages without running upstream installers/hooks.

Run from any directory. Existing packages must match the lock before replacement,
so a local edit cannot be silently overwritten. Runtime never fetches these files.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1] / "server/backend/autoresearch/skill_library"
SOURCES = [
    (
        "Yuan1z0825/nature-skills",
        "4a04b953c13c57adc51e202ce296597f00d29d67",
        "nature-skills",
        ("skills/",),
        ("LICENSE", "NOTICE"),
    ),
    (
        "blader/humanizer",
        "0ef9fe5bc3572734fd3ae6c448fe00a30cd5dcf0",
        "editing/humanizer",
        ("",),
        (),
    ),
    (
        "op7418/Humanizer-zh",
        "f4518a8eab97b8bfebc66a89d34320a89bef6930",
        "editing/humanizer-zh",
        ("",),
        (),
    ),
    (
        # Stdlib-only MCP server + skills; its data-manifest.json pins the data archive sha256
        # that deploy/install-pathtrove-data.py installs.
        "DearCaat/PathTrove",
        "89cd983def7f0bf264fee172856071fda94c5c2e",
        "pathtrove",
        ("plugin/",),
        ("LICENSE", "TERMS_OF_USE.md", "CITATION.cff"),
    ),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    lock_path = ROOT / "sources.lock.json"
    if lock_path.exists():
        previous = json.loads(lock_path.read_text())
        for item in previous["sources"]:
            package_root = ROOT / item["directory"]
            existing = {
                str(path.relative_to(package_root))
                for path in package_root.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
            }
            if existing != set(item["files"]):
                raise SystemExit(
                    f"Local files added/removed in {package_root}; review them before syncing."
                )
            for relative, expected in item["files"].items():
                path = ROOT / item["directory"] / relative
                if not path.is_file() or digest(path) != expected:
                    raise SystemExit(
                        f"Local skill change: {path}. Review it before syncing."
                    )
    ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="pathlab-skill-import-") as temporary:
        for repo, commit, destination, prefixes, extras in SOURCES:
            url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
            with urlopen(
                Request(url, headers={"User-Agent": "PathLab-skill-vendor/1"}),
                timeout=90,
            ) as response:
                archive = response.read(128 * 1024 * 1024 + 1)
            if len(archive) > 128 * 1024 * 1024:
                raise ValueError("Skill archive exceeds import size limit")
            staging = Path(temporary) / destination
            staging.mkdir(parents=True)
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
                for member in package.getmembers():
                    relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
                    name = str(relative)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("Unsafe archive path")
                    if (
                        not any(name.startswith(prefix) for prefix in prefixes)
                        and name not in extras
                    ):
                        continue
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError(f"Unsupported skill entry: {name}")
                    stream = package.extractfile(member)
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(stream.read())
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
            files = {
                str(path.relative_to(staging)): digest(path)
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            }
            records.append(
                {
                    "repository": f"https://github.com/{repo}",
                    "commit": commit,
                    "directory": destination,
                    "archive_sha256": hashlib.sha256(archive).hexdigest(),
                    "files": files,
                    "executables": [
                        str(path.relative_to(staging))
                        for path in sorted(staging.rglob("*"))
                        if path.is_file() and path.stat().st_mode & 0o111
                    ],
                }
            )
            print(f"{repo}@{commit[:12]}: {len(files)} files")
        for record in records:
            target = ROOT / record["directory"]
            if target.exists():
                if not lock_path.exists():
                    raise ValueError(
                        f"Refusing to overwrite untracked package {target}"
                    )
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(Path(temporary) / record["directory"], target)
    lock_path.write_text(
        json.dumps({"sources": records}, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
