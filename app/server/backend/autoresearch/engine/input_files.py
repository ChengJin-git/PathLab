"""Compact, selected-file-only input views on each source filesystem."""

import hashlib
import os
import shutil
import tempfile
from pathlib import Path


class InputFiles:
    def __init__(self, private: Path, dataset_id: str):
        self.registry = private / 'input_views'
        self.root = private / 'inputs' / dataset_id
        self.dataset_id = dataset_id
        self.mounts = {str(self.root): f'/research-data/{dataset_id}'}
        self.views: dict[Path, tuple[Path, str] | None] = {}

    def _view(self, source: Path, relative: Path) -> tuple[Path, str] | None:
        parent = source.parent
        if parent in self.views:
            return self.views[parent]
        key = hashlib.sha256(f'{self.dataset_id}:{parent}'.encode()).hexdigest()[:24]
        alias = f'/research-inputs/{key}'
        self.registry.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = self.registry / key
        if record.is_symlink() and record.is_dir():
            result = (record.resolve(), alias)
            self.views[parent] = result
            return result
        device = source.stat().st_dev
        for directory in (parent, *parent.parents):
            if directory.stat().st_dev != device:
                break
            view = None
            try:
                view = Path(tempfile.mkdtemp(prefix='.pathlab-inputs-', dir=directory))
                target = view / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target)
                record.unlink(missing_ok=True)
                record.symlink_to(view, target_is_directory=True)
            except OSError:
                if view is not None:
                    shutil.rmtree(view)
                continue
            result = (view, alias)
            self.views[parent] = result
            return result
        self.views[parent] = None
        return None

    def add(self, source: Path, destination: str):
        relative = Path(destination.removeprefix(f'/research-data/{self.dataset_id}/'))
        link = self.root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            if os.path.samefile(source, link):
                return
            link.unlink()
        try:
            os.link(source, link)
            return
        except OSError:
            pass
        # Cross-filesystem links cannot live in the session storage. Keep a
        # private view alongside the source instead of mounting its whole parent.
        view = self._view(source, relative)
        if view is not None:
            directory, alias = view
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not os.path.samefile(source, target):
                target.unlink()
            try:
                if not target.exists():
                    os.link(source, target)
            except OSError:
                self.mounts[str(source)] = destination
                return
            link.symlink_to(f'{alias}/{relative.as_posix()}')
            self.mounts[str(directory)] = alias
        else:
            # Read-only sources or protected hardlinks still need exact binds.
            self.mounts[str(source)] = destination


def cleanup_input_views(private: Path):
    """Remove only registered session-owned links after its processes stop."""
    for record in (private / 'input_views').glob('*'):
        if not record.is_symlink():
            continue
        view = record.resolve()
        if not view.name.startswith('.pathlab-inputs-'):
            raise ValueError('Invalid research input view')
        if view.exists():
            shutil.rmtree(view)
        record.unlink()
