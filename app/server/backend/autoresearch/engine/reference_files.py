"""Selected research files exposed through a read-only view, without runtime secrets."""

import os
from pathlib import Path

EXCLUDED = {'.opencode', '.venv', '.git', '__pycache__', 'node_modules',
            'opencode.json', 'opencode.jsonc', 'process.json', 'credentials.json'}


def research_file_view(source: Path, destination: Path):
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Referenced research workspace is not a directory')
    if destination.is_symlink():
        raise ValueError('Research reference view contains an unexpected symlink')
    destination.mkdir(parents=True, exist_ok=True)
    present = set()
    for directory, dirs, files in os.walk(source, followlinks=False):
        dirs[:] = [name for name in dirs if not name.startswith('.') and name not in EXCLUDED
                   and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if name.startswith('.') or name in EXCLUDED or path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(source)
            # Reject a view path that was replaced by a symlink between refreshes.
            for parent in [destination, *(destination / part for part in relative.parents if part != Path('.'))]:
                if parent.is_symlink():
                    raise ValueError('Research reference view contains an unexpected symlink')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            if target.exists() and not os.path.samefile(path, target):
                target.unlink()
            if not target.exists():
                os.link(path, target)  # Workspaces and reference views share research storage.
            present.add(relative)
    for directory, dirs, files in os.walk(destination, topdown=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink() or path.relative_to(destination) not in present:
                path.unlink()
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink():
                path.unlink()
            elif not any(path.iterdir()):
                path.rmdir()
    return len(present)
