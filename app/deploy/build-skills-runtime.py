"""Build, exercise, then atomically publish the scientific-skills sandbox.

Run with server/backend/autoresearch/.venv/bin/python from the client directory.
Temporary build files and verification outputs are removed on success or failure.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from dotenv import load_dotenv

load_dotenv(ROOT / "server/.env")

from backend.autoresearch.engine import runtime
from backend.autoresearch.runtime.sandbox import _resolve_default_image
from backend.common.config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuild-base', action='store_true', help='Build the ML base before adding scientific tools')
    args = parser.parse_args()
    target = Path(_resolve_default_image()).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    recipe = ROOT / "server/backend/autoresearch/runtime/containers/skills-runtime.def"
    with tempfile.TemporaryDirectory(
        prefix="skills-build-", dir=target.parent
    ) as temporary:
        staging = Path(temporary)
        candidate = staging / "pathlab-sandbox.sif"
        env = {**os.environ, "APPTAINER_TMPDIR": str(staging)}
        base_image = target
        if args.rebuild_base or not target.is_file():
            base_image = staging / 'ml-base.sif'
            subprocess.run(
                ['bash', str(ROOT / 'deploy/build-autoresearch-sandbox.sh')],
                env={**env, 'AUTORESEARCH_SANDBOX_IMAGE':str(base_image),
                     'AUTORESEARCH_SANDBOX_VERIFY':'0', 'AUTORESEARCH_SANDBOX_USE_NV':'0'},
                check=True,
            )
        subprocess.run(
            [
                runtime._resolve_apptainer_bin(),
                "build",
                "--fakeroot",
                "--mksquashfs-args",
                "-processors 4 -comp zstd -Xcompression-level 3",
                "--build-arg",
                f"base_image={base_image}",
                "--build-arg",
                f"repo_root={ROOT}",
                str(candidate),
                str(recipe),
            ],
            env=env,
            check=True,
        )
        runtime._resolve_default_image = lambda: str(candidate)
        Config.get_autoresearch_dir = classmethod(lambda cls: staging / "research")
        root = staging / "session_verify"
        root.mkdir()
        subprocess.run(
            runtime.sandbox_command(root, {})
            + ["python", "/opt/pathlab/verify-skills-runtime.py"],
            check=True,
            env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")},
        )
        os.replace(candidate, target)
    print(f"Verified scientific-skills sandbox published: {target}")


if __name__ == "__main__":
    main()
