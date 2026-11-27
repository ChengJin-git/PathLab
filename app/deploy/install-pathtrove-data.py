"""Install the pinned PathTrove data package for the research sandbox. Idempotent.

The archive path, size and sha256 come from the vendored plugin's data-manifest.json, which is
itself hash-locked in skill_library/sources.lock.json. Offline hosts: download the archive URL
elsewhere and pass --file. HF_ENDPOINT selects a Hugging Face mirror.

Usage: python deploy/install-pathtrove-data.py [--file ARCHIVE]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from backend.autoresearch.engine import pathtrove


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="local copy of the pinned archive")
    args = parser.parse_args()
    version = pathtrove.manifest()["data_version"]
    if not pathtrove.ready():
        print(f"Installing PathTrove data {version} from {args.file or pathtrove.archive_url()}")
        try:
            pathtrove.install(args.file)
        except RuntimeError as error:
            raise SystemExit(str(error)) from None
    print(f"PathTrove data {version}: {pathtrove.home()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
