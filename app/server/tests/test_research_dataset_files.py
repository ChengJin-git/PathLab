from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.autoresearch.engine.dataset_files import DatasetFiles


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    from backend.autoresearch.engine import datasets
    image_root = tmp_path / 'images'
    image_root.mkdir()
    slides = []
    for index, split in enumerate(['train', 'val', 'test']):
        source = image_root / f'original-{index}.jpg'
        source.write_bytes(f'image-{index}'.encode())
        slides.append(SimpleNamespace(wsi_id=f'uuid-{index}', wsi_path=str(source), original_filename=source.name,
            associated_files={}, label='Benign' if index < 2 else 'Malignant', split=split, case_id=f'case-{index}',
            event_time=None, event_status=None))
    dataset = SimpleNamespace(to_dict=lambda: {'dataset_id':'cohort','name':'Cytology','data_type':'patch',
        'task_types':['patch_classification'],'aggregation_level':'file','source_organ':'Other','is_public':True})
    user = SimpleNamespace(is_admin=lambda: True, id='00000000-0000-0000-0000-000000000001')
    session = SimpleNamespace(user_id=user.id, workspace_path=str(tmp_path / 'workspace'), research_question='Audit cytology', recovery_metadata={})
    db = SimpleNamespace(get=AsyncMock(return_value=user), scalar=AsyncMock(return_value=dataset))
    async def scalars(statement):
        return SimpleNamespace(all=lambda: ['cohort'] if statement == 'scope' else [] if 'feature_artifacts' in str(statement) else slides)
    db.scalars = scalars
    @asynccontextmanager
    async def database():
        yield db
    monkeypatch.setattr(datasets, 'safe_session', database)
    monkeypatch.setattr(datasets.store, 'get', AsyncMock(return_value=session))
    attach = AsyncMock()
    monkeypatch.setattr(datasets.store, 'attach_dataset', attach)
    monkeypatch.setattr('backend.auth.dependencies.get_dataset_with_access', AsyncMock(return_value=dataset))
    monkeypatch.setattr('backend.services.workspaces.resolve_scope', AsyncMock(return_value=SimpleNamespace(datasets=lambda user: 'scope')))
    monkeypatch.setattr(datasets.Config, 'get_uploads_dir', lambda: tmp_path)
    monkeypatch.setattr(datasets, 'private_dir', lambda sid: tmp_path / 'private')
    return SimpleNamespace(module=datasets, root=tmp_path, session=session, slides=slides, attach=attach)


def test_shared_directories_are_scanned_once_for_many_slides(tmp_path, monkeypatch):
    from backend.autoresearch.engine import dataset_files

    root = tmp_path / 'images'
    root.mkdir()
    (root / 'labels.csv').write_text('slide_id,label\na,A\n')
    (root / 'train.csv').write_text('slide_id,label\na,A\n')
    (root / 'source-labels.tsv').write_text('slide_id\tlabel\na\tA\n')
    (root / 'not-label.csv').mkdir()
    extractor = tmp_path / 'features' / 'uni'
    nested = extractor / 'params'
    nested.mkdir(parents=True)
    (nested / 'original.pt').write_bytes(b'feature')
    (extractor / 'exact.pth').write_bytes(b'direct')
    scan_counts = Counter()
    scandir = dataset_files.os.scandir
    def scan(path):
        scan_counts[Path(path)] += 1
        return scandir(path)
    monkeypatch.setattr(dataset_files.os, 'scandir', scan)
    inventory = DatasetFiles(lambda: None)
    for i in range(100):
        slide = SimpleNamespace(wsi_id=f'uuid-{i}', wsi_path=str(root / f'{i}.jpg'), original_filename='original.jpg', associated_files={})
        assert {p.name for p in inventory.label_tables(root)} == {'labels.csv', 'train.csv', 'source-labels.tsv'}
        assert inventory.features(slide, Path(slide.wsi_path), [extractor.parent]) == {'uni': str(nested / 'original.pt')}
    assert max(scan_counts.values()) == 1
    slide = SimpleNamespace(wsi_id='exact', wsi_path=str(root / 'original.jpg'), original_filename='original.jpg', associated_files={})
    assert inventory.features(slide, Path(slide.wsi_path), [extractor.parent]) == {'uni': str(extractor / 'exact.pth')}


def test_registered_features_win_and_new_preparations_see_new_files(tmp_path):
    root = tmp_path / 'features'
    (root / 'uni').mkdir(parents=True)
    registered = tmp_path / 'registered.pt'
    registered.write_bytes(b'registered')
    slide = SimpleNamespace(wsi_id='slide', wsi_path=str(tmp_path / 'slide.jpg'), original_filename=None,
                            associated_files={'autoresearch_features': {'one': {'feature_path':str(registered),'extractor_name':'uni'}}})
    inventory = DatasetFiles(lambda: None)
    assert inventory.features(slide, Path(slide.wsi_path), [root]) == {'uni':str(registered)}
    slide.associated_files = {}
    assert inventory.features(slide, Path(slide.wsi_path), [root]) == {}
    (root / 'uni' / 'slide.pt').write_bytes(b'new')
    assert DatasetFiles(lambda: None).features(slide, Path(slide.wsi_path), [root]) == {'uni':str(root / 'uni' / 'slide.pt')}


def test_feature_alias_and_tcga_source_layout(tmp_path):
    source = tmp_path / 'original_data' / 'TCGA' / 'brca' / 'slide.svs'
    source.parent.mkdir(parents=True)
    feature = tmp_path / 'Patches' / 'TCGA' / 'TCGA-BRCA' / 'pt_files' / 'uni' / 'original.pt'
    feature.parent.mkdir(parents=True)
    feature.touch()
    slide = SimpleNamespace(wsi_id='uuid', wsi_path=str(source), original_filename='prefix__original.svs', associated_files={})
    assert DatasetFiles(lambda: None).features(slide, source, []) == {'uni':str(feature)}


def test_long_directory_scan_obeys_preparation_deadline(tmp_path):
    for i in range(300):
        (tmp_path / f'{i}.jpg').touch()
    calls = 0
    def check():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise TimeoutError('deadline')
    with pytest.raises(TimeoutError, match='deadline'):
        DatasetFiles(check).label_tables(tmp_path)


async def test_preparation_preserves_splits_cases_labels_and_input_mounts(preparation):
    import json
    feature = preparation.root / 'features' / 'uni' / 'parameters' / 'uuid-1.pt'
    feature.parent.mkdir(parents=True)
    feature.write_bytes(b'features')
    info = await preparation.module.prepare_dataset('session', 'cohort')
    manifest = json.loads(Path(info['manifest_path']).read_text())
    assert [(item['label'], item['case_id'], item['split']) for item in manifest['items']] == [
        ('Benign','case-0','train'), ('Benign','case-1','val'), ('Malignant','case-2','test')]
    assert info['feature_extractors'] == ['uni']
    inputs = preparation.root / 'private' / 'inputs' / 'cohort'
    for index, item in enumerate(manifest['items']):
        assert (inputs / item['path'].split('/research-data/cohort/')[1]).read_bytes() == f'image-{index}'.encode()
    assert (inputs / 'features/uni/uuid-1.pt').read_bytes() == b'features'
    assert preparation.attach.call_args.args[2] == {str(inputs):'/research-data/cohort'}
    assert not list(Path(info['manifest_path']).parent.glob('*.tmp'))


async def test_preparation_timeout_preserves_last_manifest_without_attaching(preparation, monkeypatch):
    target = Path(preparation.session.workspace_path) / 'datasets' / 'cohort'
    target.mkdir(parents=True)
    (target / 'manifest.json').write_text('previous completed manifest')
    monkeypatch.setattr(preparation.module, 'PREPARATION_SECONDS', -1)
    with pytest.raises(TimeoutError, match='checking input files'):
        await preparation.module.prepare_dataset('session', 'cohort')
    assert (target / 'manifest.json').read_text() == 'previous completed manifest'
    preparation.attach.assert_not_awaited()
    assert not list(target.glob('*.tmp'))


async def test_same_dataset_duplicate_is_bounded_and_cancellation_releases_lock(preparation, monkeypatch):
    import asyncio
    import threading
    entered, release = threading.Event(), threading.Event()
    original = DatasetFiles.label_tables
    def blocked(self, directory):
        entered.set()
        assert release.wait(5)
        self.check()
        return original(self, directory)
    monkeypatch.setattr(DatasetFiles, 'label_tables', blocked)
    first = asyncio.create_task(preparation.module.prepare_dataset('session', 'cohort'))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        with pytest.raises(RuntimeError, match='already being prepared'):
            await preparation.module.prepare_dataset('session', 'cohort')
        first.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        preparation.attach.assert_not_awaited()
        assert not (Path(preparation.session.workspace_path) / 'datasets/cohort/manifest.json').exists()
        info = await preparation.module.prepare_dataset('session', 'cohort')
        assert info['file_count'] == 3
        preparation.attach.assert_awaited_once()
    finally:
        release.set()
        if not first.done():
            first.cancel()
        await asyncio.gather(first, return_exceptions=True)


def test_source_resolution_caches_parents_but_follows_each_file_symlink(tmp_path, monkeypatch):
    actual = tmp_path / 'actual'; actual.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(actual, target_is_directory=True)
    (actual / 'image').write_bytes(b'image')
    (actual / 'relative').symlink_to('image')
    (actual / 'absolute').symlink_to(actual / 'image')
    counts = Counter()
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        counts[path] += 1
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    inventory = DatasetFiles(lambda: None)
    for _ in range(10):
        for name in ['image', 'relative', 'absolute']:
            assert inventory.resolve_source(alias / name) == actual / 'image'
    assert counts[alias] == 1 and counts[actual] == 1
    assert inventory.resolve_source(alias / 'missing') == actual / 'missing'
    (actual / 'loop').symlink_to('loop')
    with pytest.raises(RuntimeError, match='Symlink loop'):
        inventory.resolve_source(alias / 'loop')


async def test_resume_reuses_prepared_inputs_and_prepares_only_missing_dataset(preparation, monkeypatch):
    from backend.autoresearch.engine import datasets
    info = await datasets.prepare_dataset('session', 'cohort')
    inputs = preparation.root / 'private/inputs/cohort'
    preparation.session.session_id = 'session'
    preparation.session.recovery_metadata = {'dataset_ids': ['cohort', 'new'], 'datasets': [info],
        'data_mounts': {str(inputs): '/research-data/cohort'}}
    prepare = AsyncMock()
    monkeypatch.setattr(datasets, 'prepare_dataset', prepare)
    await datasets.prepare_pending_datasets(preparation.session)
    prepare.assert_awaited_once_with('session', 'new')
    prepare.reset_mock()
    Path(info['manifest_path']).unlink()
    await datasets.prepare_pending_datasets(preparation.session)
    assert [c.args[1] for c in prepare.await_args_list] == ['cohort', 'new']
