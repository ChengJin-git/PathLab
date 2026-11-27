"""Migration wheel relocation and integrity regression checks."""
import importlib.metadata
import importlib.util
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    'runtime_bundle', Path(__file__).parents[2] / 'deploy/runtime_bundle.py'
)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def test_repacked_console_scripts_are_regenerated_without_host_paths(tmp_path):
    wheel = bundle.repack(importlib.metadata.distribution('httpx'), tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any(name.startswith('../') for name in names)
        assert not any('/scripts/httpx' in name for name in names)
        assert any(name.endswith('/entry_points.txt') for name in names)
        assert any(name.endswith('/RECORD') for name in names)
        assert not any(name.endswith('/direct_url.json') for name in names)
        assert archive.testzip() is None


def test_corrupt_bundle_fails_before_creating_environment(tmp_path):
    asset = tmp_path / 'requirements.lock'
    asset.write_text('modified')
    manifest = bundle.inventory()
    manifest['assets'] = {'requirements.lock': 'wrong hash'}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    target = tmp_path / 'new-env'
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        bundle.install(SimpleNamespace(bundle=str(tmp_path), target=str(target), python=None))
    assert not target.exists()


def test_export_missing_sandbox_fails_before_creating_a_partial_bundle(tmp_path):
    target = tmp_path / 'bundle'
    with pytest.raises(RuntimeError, match='Missing required asset'):
        bundle.export(SimpleNamespace(bundle=str(target), sandbox=str(tmp_path/'missing.sif'), opencode=None))
    assert not target.exists()


def test_multitag_pure_python_wheel_keeps_python3_compatibility(tmp_path):
    wheel = bundle.repack(importlib.metadata.distribution('six'), tmp_path)
    from packaging.tags import parse_tag, sys_tags
    tag = '-'.join(wheel.stem.split('-')[-3:])
    assert parse_tag(tag) & set(sys_tags())


def test_vendored_dist_info_does_not_replace_outer_wheel_record(tmp_path):
    wheel = bundle.repack(importlib.metadata.distribution('bleach'), tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        assert any(n.endswith('.dist-info/RECORD') and n.count('/') == 1 for n in archive.namelist())
