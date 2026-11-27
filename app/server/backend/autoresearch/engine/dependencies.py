"""Install task-specific Python dependencies inside the research sandbox only."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from .runtime import sandbox_command, terminate
from ..runtime import container_backend

# Package names and ordinary version constraints only, never pip flags or shell code.
SPEC = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:(?:==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!_-]+(?:,(?:==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!_-]+)*)?"
)
IMPORT = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
INSTALL = r"""
import fcntl, json, os, subprocess, sys
from pathlib import Path
root = Path.cwd()
packages, imports = json.loads(sys.argv[1]), json.loads(sys.argv[2])
with (root / '.dependency-install.lock').open('w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    python = root / '.venv/bin/python'
    if not python.is_file():
        subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(root / '.venv')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', *packages], check=True)
    subprocess.run([str(python), '-c', 'import importlib, json, sys; [importlib.import_module(name) for name in json.loads(sys.argv[1])]', json.dumps(imports)], check=True)
    print(json.dumps({'installed': packages, 'verified_imports': imports, 'python': str(python)}))
"""


async def install(
    root: Path, mounts: dict, packages: list[str], imports: list[str]
) -> dict:
    if not 1 <= len(packages) <= 10 or any(not SPEC.fullmatch(p) for p in packages):
        raise ValueError(
            "Use up to ten Python package names with optional version constraints."
        )
    if not 1 <= len(imports) <= 10 or any(
        not IMPORT.fullmatch(name) for name in imports
    ):
        raise ValueError("Use Python module names for import verification.")
    log_path = root / "dependency-install.log"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
    }
    command = sandbox_command(root, mounts) + [
        "python",
        "-c",
        INSTALL,
        json.dumps(packages),
        json.dumps(imports),
    ]
    command, env, container = container_backend.prepare(command, env)
    with log_path.open("ab") as log:
        process = await asyncio.create_subprocess_exec(
            *command, env=env, stdout=log, stderr=log, start_new_session=os.name != 'nt'
        )
        try:
            # Remain inside the MCP transport's 180-second request timeout.
            await asyncio.wait_for(process.wait(), 150)
        finally:
            await container_backend.remove_container(container)
            if process.returncode is None:
                await terminate(process.pid)
                await process.wait()
    if process.returncode:
        raise RuntimeError(
            "Dependency installation failed. Inspect dependency-install.log, correct the package/version or retry a transient network failure."
        )
    return {
        "installed": packages,
        "verified_imports": imports,
        "python": str(root / ".venv/bin/python"),
        "instruction": "Python experiment/computation commands now use this session environment automatically. Retry the failed job with a new source snapshot.",
    }
