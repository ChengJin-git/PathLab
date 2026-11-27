import errno
import os
from pathlib import Path

from backend.autoresearch.engine.input_files import InputFiles, cleanup_input_views


def test_cross_filesystem_inputs_share_private_view_without_exposing_neighbors(tmp_path, monkeypatch):
    source = tmp_path / 'nas'
    source.mkdir()
    (source / 'unselected.pt').write_bytes(b'private')
    private = tmp_path / 'runtime'
    link = os.link

    def cross_device(src, dst):
        if Path(dst).is_relative_to(private):
            raise OSError(errno.EXDEV, 'cross-device link')
        return link(src, dst)

    monkeypatch.setattr(os, 'link', cross_device)
    inputs = InputFiles(private, 'cohort')
    for index in range(100):
        original = source / f'original,{index}.pt'
        original.write_bytes(str(index).encode())
        inputs.add(original, f'/research-data/cohort/features/uni/id-{index}.pt')
    assert len(inputs.mounts) == 2
    view, alias = next((Path(src), dst) for src, dst in inputs.mounts.items() if dst.startswith('/research-inputs/'))
    assert len(list(view.rglob('*.pt'))) == 100
    assert not (view / 'unselected.pt').exists()
    assert (view / 'features/uni/id-0.pt').read_bytes() == b'0'
    assert (private / 'inputs/cohort/features/uni/id-0.pt').readlink() == Path(alias) / 'features/uni/id-0.pt'
    # Repreparation reuses its durable view and still records the mount.
    again = InputFiles(private, 'cohort')
    again.add(source / 'original,0.pt', '/research-data/cohort/features/uni/id-0.pt')
    assert again.mounts == inputs.mounts
    cleanup_input_views(private)
    cleanup_input_views(private)
    assert not view.exists()
    assert (source / 'original,0.pt').read_bytes() == b'0'
    assert (source / 'unselected.pt').read_bytes() == b'private'


def test_protected_sources_keep_exact_read_only_mounts(tmp_path, monkeypatch):
    source = tmp_path / 'protected.pt'
    source.write_bytes(b'protected')
    monkeypatch.setattr(os, 'link', lambda *args: (_ for _ in ()).throw(OSError(errno.EPERM, 'protected')))
    inputs = InputFiles(tmp_path / 'runtime', 'cohort')
    inputs.add(source, '/research-data/cohort/features/uni/id.pt')
    assert inputs.mounts[str(source)] == '/research-data/cohort/features/uni/id.pt'
    assert not list(tmp_path.rglob('.pathlab-inputs-*'))
