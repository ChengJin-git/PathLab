"""PathTrove: pinned catalogue of public computational-pathology datasets, served to the agent over MCP.

The plugin is vendored in the skill library (commit and file hashes in sources.lock.json); its
data-manifest.json pins the data archive by sha256. install() puts exactly that archive under home(),
which the sandbox mounts read-only: deploy/start.sh runs it (deploy/install-pathtrove-data.py), and
the agent runtime runs it once if a host skipped that step. Offline hosts pass a local archive copy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.common.config import Config

from .builtin_skills import LIBRARY

PLUGIN = LIBRARY / "pathtrove/plugin"
SANDBOX_PLUGIN = "/opt/pathlab/skill-library/pathtrove/plugin"
SANDBOX_HOME = "/opt/pathlab/pathtrove"
MARKER = ".pathtrove-installed.json"


def manifest() -> dict:
    return json.loads((PLUGIN / "data-manifest.json").read_text(encoding="utf-8"))


def home() -> Path:
    return Config.get_autoresearch_dir() / "pathtrove"


def ready() -> bool:
    pinned = manifest()
    marker = home() / "data" / pinned["data_version"] / MARKER
    try:
        return json.loads(marker.read_text(encoding="utf-8"))["archive_sha256"] == pinned["archive"]["sha256"]
    except (OSError, ValueError, KeyError):
        return False


def mcp_server() -> dict:
    return {
        "type": "local",
        "command": ["python", f"{SANDBOX_PLUGIN}/bin/pathtrove", "mcp"],
        "codemode": False,
        "environment": {"PATHTROVE_HOME": SANDBOX_HOME, "PATHTROVE_LANG": "en"},
    }


def archive_url() -> str:
    pinned = manifest()
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    return f"{endpoint}/datasets/{pinned['hf_repo']}/resolve/main/{quote(pinned['archive']['path'])}"


def install(archive: Path | None = None) -> None:
    """Install the pinned data package (download unless a local archive is given). Idempotent."""
    if ready():
        return
    pinned = manifest()["archive"]
    home().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=home(), prefix=".download-") as temporary:
        if archive is None:
            archive = Path(temporary) / pinned["name"]
            try:
                with urlopen(Request(archive_url(), headers={"User-Agent": "PathLab-pathtrove/1"}), timeout=120) as response, archive.open("wb") as out:
                    while chunk := response.read(1 << 20):
                        out.write(chunk)
                        if out.tell() > pinned["size"]:
                            raise OSError(f"larger than the pinned {pinned['size']} bytes")
            except OSError as error:
                raise RuntimeError(
                    f"PathTrove data download failed ({error}). Download {archive_url()} (sha256 {pinned['sha256']}) "
                    "and run deploy/install-pathtrove-data.py --file ARCHIVE, or set HF_ENDPOINT to a mirror."
                ) from None
        # The plugin re-checks size and sha256 against the same pinned manifest before unpacking.
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "bin/pathtrove"), "data", "install", "--file", str(archive), "--lang", "en"],
            env={**os.environ, "PATHTROVE_HOME": str(home())}, capture_output=True, text=True, timeout=300, check=False,
        )
    if result.returncode or not ready():
        raise RuntimeError(f"PathTrove data install failed: {(result.stderr or result.stdout).strip()[-2000:]}")
