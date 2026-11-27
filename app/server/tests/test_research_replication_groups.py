"""Independent repeat evidence can be linked without rewriting candidate lineage."""
# ruff: noqa: PLC0414 -- exported pytest fixtures

import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_scientific_study import api as api
from test_scientific_study import scientific_case as scientific_case
from test_scientific_study import write

from backend.autoresearch.engine import store, study, tools
from backend.autoresearch.engine.research_progress import protocol_execution
from backend.autoresearch.engine.study_contract import measured_scale_progress
from backend.database.models import AutoResearchExperiment


@pytest.fixture
async def independent_repeats(scientific_case):
    api, root, protocol, review = scientific_case
    protocol['steps'][1]['scale']['repeats'] = 3
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    session = await store.get('alice')
    async with api.sessions() as db:
        old = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'method'))
        previous = old.hyperparams['config']
        config = study.experiment_config(session, {'study_step': 'method', 'candidate_id': 'method', 'operation': 'draft'})
        first = {**previous['study_measurement'], 'replicate_ids': ['seed-1', 'seed-2'],
                 'primary_by_replicate': {'seed-1': 0.0, 'seed-2': 0.002}}
        old.hyperparams = {'config': {**config, 'study_measurement': first}}
        other = deepcopy(old.hyperparams)
        other['config'].update(candidate_id='method-seed-3', operation='improve', parent_run_id='baseline')
        other['config']['study_measurement'].update(replicate_ids=['seed-3'], primary_by_replicate={'seed-3': -0.002})
        db.add(AutoResearchExperiment(session_id='alice', training_task_id='repeat', experiment_name='Second seed',
                                     status='completed', iteration=8, metrics={'delta': -.01}, hyperparams=other))
        await db.commit()
    decision = json.loads((root/'decision.json').read_text())
    decision.update(id='measured-repeats', run_ids=['method', 'repeat'])
    write(root, 'decision-repeats.json', decision)
    await study.record_decision(await store.get('alice'), 'decision-repeats.json')
    review = {**review, 'completed_steps': {'baseline': ['baseline'], 'method': ['method', 'repeat']}}
    write(root, 'review.json', review)
    (root/'repeat-evidence.md').write_text('Same fixed method, data and evaluator; seeds 1-3 are independent training runs.')
    link = {'id': 'method-repeats', 'step_id': 'method', 'run_ids': ['method', 'repeat'],
            'rationale': 'Method and input manifests verified; only independent training seed differs.',
            'evidence_files': ['repeat-evidence.md']}
    write(root, 'link.json', link)
    return api, root, protocol, review, link


async def test_link_releases_current_comparison_preserving_runs_and_authorization(independent_repeats):
    before = await store.experiments('alice')
    session = await store.get('alice')
    state = protocol_execution(session.recovery_metadata['study'], before)
    assert state['required_steps_below_planned_scale'] == ['method']
    with pytest.raises(ValueError, match='method has 2/3 eligible repeats'):
        await study.record_review(session, 'review.json')
    result = await tools.call('alice', 'record_replication_group', {'path': 'link.json'})
    assert result['recorded'] and result['complete'] and result['eligible_repeats'] == 3
    assert await tools.call('alice', 'record_replication_group', {'path': 'link.json'}) == result
    session = await store.get('alice')
    assert (session.current_iteration, session.max_iterations) == (6, 8)
    assert len(session.recovery_metadata['replication_groups']) == 1
    assert await store.experiments('alice') == before
    state = protocol_execution(session.recovery_metadata['study'], before, session.recovery_metadata['replication_groups'])
    assert state['required_steps_below_planned_scale'] == []
    assert state['measured_repeats_by_step']['method']['eligible_repeats'] == 3
    assert (await tools.call('alice', 'record_study_review', {'path': 'review.json'}))['ready_to_write']
    evidence = await study.writing_evidence(await store.get('alice'))
    assert 'repeat-evidence.md' in evidence['sources']
    assert set(evidence['run_ids']) == {'baseline', 'method', 'repeat'}
    assert len(evidence['review']['replication_groups']) == 1


@pytest.mark.parametrize('mutation', ['failed', 'comparison', 'step', 'sample', 'unit', 'unknown', 'duplicate'])
async def test_bad_link_cannot_bypass_comparison_or_sample_checks(independent_repeats, mutation):
    api, root, _, _, link = independent_repeats
    if mutation in {'unknown', 'duplicate'}:
        link['run_ids'] = ['method', 'other-session-run' if mutation == 'unknown' else 'method']
        write(root, 'link.json', link)
    else:
        async with api.sessions() as db:
            run = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'repeat'))
            config = deepcopy(run.hyperparams)
            if mutation == 'failed':
                run.status = 'failed'
            elif mutation == 'comparison':
                config['config']['study_step_revision'] = 'another-method-fingerprint'
            elif mutation == 'step':
                config['config']['study_step'] = 'baseline'
            elif mutation == 'sample':
                config['config']['study_measurement']['evaluation_units'] = 99
            else:
                config['config']['study_measurement']['unit'] = 'patch'
            run.hyperparams = config
            await db.commit()
    with pytest.raises(ValueError):
        await study.record_replication_group(await store.get('alice'), 'link.json')
    assert not (await store.get('alice')).recovery_metadata.get('replication_groups')


async def test_recovered_duplicate_seed_does_not_count_twice(independent_repeats):
    api, _, _, _, _ = independent_repeats
    async with api.sessions() as db:
        run = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'repeat'))
        config = deepcopy(run.hyperparams)
        config['config']['study_measurement'].update(replicate_ids=['seed-1'], primary_by_replicate={'seed-1': 0.0})
        config['config']['operation'] = 'debug'
        run.hyperparams = config
        await db.commit()
    result = await study.record_replication_group(await store.get('alice'), 'link.json')
    assert result['eligible_repeats'] == 2 and not result['complete']


async def test_direction_assessment_uses_linked_evidence_and_checks_sources(independent_repeats):
    _, root, _, _, _ = independent_repeats
    decision = json.loads((root/'decision-repeats.json').read_text())
    decision.update(id='direction-result', scope='direction')
    write(root, 'direction.json', decision)
    with pytest.raises(ValueError, match='target-scale'):
        await study.record_decision(await store.get('alice'), 'direction.json')
    await study.record_replication_group(await store.get('alice'), 'link.json')
    assert (await study.record_decision(await store.get('alice'), 'direction.json'))['recorded']
    (root/'repeat-evidence.md').write_text('Source changed')
    decision['id'] = 'changed-direction-result'
    write(root, 'direction.json', decision)
    with pytest.raises(ValueError, match='evidence changed'):
        await study.record_decision(await store.get('alice'), 'direction.json')


@pytest.mark.parametrize('mutation', ['run', 'source', 'missing_selection', 'protocol'])
async def test_linked_review_rejects_changed_or_omitted_evidence(independent_repeats, mutation):
    api, root, protocol, review, _ = independent_repeats
    await study.record_replication_group(await store.get('alice'), 'link.json')
    await study.record_review(await store.get('alice'), 'review.json')
    if mutation == 'source':
        (root/'repeat-evidence.md').write_text('Changed scientific justification')
    elif mutation == 'run':
        async with api.sessions() as db:
            run = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'repeat'))
            run.metrics = {'delta': .9}
            await db.commit()
    elif mutation == 'protocol':
        protocol['evaluation']['metric'] = 'new_metric'
        write(root, 'protocol.json', protocol)
        await study.record_protocol(await store.get('alice'), 'protocol.json')
    else:
        review['completed_steps']['method'] = ['method']
        write(root, 'review.json', review)
    with pytest.raises(ValueError):
        await study.record_review(await store.get('alice'), 'review.json')
    if mutation != 'missing_selection':
        with pytest.raises(ValueError):
            await study.writing_evidence(await store.get('alice'))


async def test_links_are_immutable_and_new_links_invalidate_review(independent_repeats):
    _, root, _, _, link = independent_repeats
    await study.record_replication_group(await store.get('alice'), 'link.json')
    await study.record_review(await store.get('alice'), 'review.json')
    link['rationale'] = 'Updated explanation'
    write(root, 'link.json', link)
    with pytest.raises(ValueError, match='immutable'):
        await study.record_replication_group(await store.get('alice'), 'link.json')
    link['id'] = 'new-link'
    write(root, 'link.json', link)
    await study.record_replication_group(await store.get('alice'), 'link.json')
    session = await store.get('alice')
    assert len(session.recovery_metadata['replication_groups']) == 2
    assert session.recovery_metadata['study']['review'] is None
    schema = await tools.call('alice', 'get_study_schema', {})
    assert set(schema['replication_group']['required']) == {'id', 'step_id', 'run_ids', 'rationale', 'evidence_files'}


def test_same_candidate_different_comparisons_are_not_pooled():
    from test_research_design import measured_run, stage
    runs = [measured_run('same', ['seed-1']), measured_run('same', ['seed-2'])]
    for index, run in enumerate(runs):
        run['config']['config']['study_step_revision'] = f'different-{index}'
    assert not measured_scale_progress(stage('confirm', 'confirmation', 2), runs)['complete']
