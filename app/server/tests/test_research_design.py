"""Cross-task decision and scheduling behavior, independent of any research dataset."""
# ruff: noqa: PLC0414 -- explicit exports for pytest's imported fixtures.

import json
import os
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_scientific_study import api as api
from test_scientific_study import record_review, write
from test_scientific_study import scientific_case as scientific_case

from backend.autoresearch.engine import jobs, store, study, tools
from backend.autoresearch.engine.recovery import assess_help
from backend.autoresearch.engine.research_progress import (
    candidate_summary,
    comparator_progress,
    evidence_progress,
)
from backend.autoresearch.engine.study_contract import (
    measured_scale_complete,
    stage_budget,
)
from backend.database.models import AutoResearchExperiment, ResearchJob


def stage(identity, kind, attempts, repeats=2):
    return {'id': identity, 'kind': kind, 'max_experiments': attempts, 'max_job_seconds': 600,
            'scale': {'unit': 'subject', 'train_units': 200, 'evaluation_units': 100,
                      'repeats': repeats, 'input_coverage': 'Complete sequence', 'optimization': 'Converged'},
            'advance_when': 'The planned comparison resolves the question',
            'stop_when': 'Useful effects excluded or resource plan revised'}


def measured_run(candidate, repeats, n=100):
    return {'status': 'completed', 'config': {'config': {'candidate_id': candidate,
        'study_measurement': {'unit': 'subject', 'train_units': 200,
                              'evaluation_units': n, 'replicate_ids': repeats}}}}


@pytest.mark.parametrize('unit', ['patient', 'time_series', 'query', 'simulation'])
def test_target_scale_requires_same_candidate_independent_repeats_and_full_units(unit):
    target = stage('confirm', 'confirmation', 4)
    target['scale']['unit'] = unit
    runs = [measured_run('a', ['seed-1']), measured_run('a', ['seed-1']),
            measured_run('b', ['seed-2']), measured_run('a', ['seed-2'], n=20)]
    for run in runs:
        run['config']['config']['study_measurement']['unit'] = unit
    assert not measured_scale_complete(target, runs)
    runs[-1]['config']['config']['study_measurement']['evaluation_units'] = 100
    assert measured_scale_complete(target, runs)
    runs[-1]['status'] = 'failed'
    assert not measured_scale_complete(target, runs)


def test_stage_budget_counts_failures_queued_work_and_revisions():
    session = SimpleNamespace(max_iterations=9, current_iteration=5, recovery_metadata={'research_standard': 'scientific', 'study': {
        'protocol': {'stages': [stage('pilot', 'exploration', 3), stage('confirm', 'confirmation', 4)], 'steps': []}}})
    previous = [{'job_id': str(i), 'kind': 'experiment', 'status': status,
                 'payload': {'config': {'study_stage': 'pilot', 'study_revision': str(i)}}}
                for i, status in enumerate(['completed', 'failed', 'queued'])]
    state = stage_budget(session, previous)
    assert state['stages'][0]['remaining'] == 0
    assert state['additional_experiments_needed'] == 4
    assert state['budget_sufficient']
    payload = {'timeout': 100, 'config': {'study_stage': 'pilot'}}
    with pytest.raises(ValueError, match='Stage attempt allocation'):
        study.validate_submission(session, payload, previous)
    session.recovery_metadata['study']['protocol']['stages'][0]['max_experiments'] = 4
    with pytest.raises(ValueError, match='reserved validation'):
        study.validate_submission(session, payload, previous)


def test_revisited_candidate_is_visible_and_scores_keep_their_contract():
    runs = []
    for i in [*range(10), 0]:
        runs.append({'run_id': f'run-{len(runs)}', 'status': 'completed', 'metrics': {'loss': i},
            'config': {'config': {'candidate_id': f'candidate-{i}', 'parent_run_id': None,
                'operation': 'draft', 'study_stage': 'validation', 'study_step_revision': f'comparison-{i}',
                'study_evaluation': {'metric': 'loss'}}}})
    summary = candidate_summary(runs)
    assert len(summary) == 8
    assert summary[-1]['candidate_id'] == 'candidate-0'
    assert [r['run_id'] for r in summary[-1]['runs']] == ['run-0', 'run-10']
    assert summary[-1]['runs'][-1]['comparison_revision'] == 'comparison-0'


def test_comparator_progress_exposes_late_strong_control_without_requiring_success():
    protocol = {'baselines':[{'id':'published','role':'closest'}],
                'steps':[{'id':'control','role':'baseline','required':True,'baseline_id':'published'}]}
    study_state = {'protocol':protocol,'step_revisions':{'control':'current'}}
    runs = [{'run_id':f'm{i}','status':'completed','config':{'config':{'study_role':'method'}}} for i in range(3)]
    runs.insert(0, {'run_id':'old','status':'completed','config':{'config':{'study_step':'control','study_step_revision':'old'}}})
    assert comparator_progress(study_state,runs)['missing_closest_steps'] == ['control']
    runs.append({'run_id':'baseline','status':'completed','config':{'config':{'study_step':'control','study_step_revision':'current'}}})
    result=comparator_progress(study_state,runs)
    assert result['missing_closest_steps'] == []
    assert result['method_runs_before_first_current_closest'] == 3
    assert result['first_current_closest_run'] == 'baseline'


async def test_stage_and_lineage_are_enforced_at_actual_submission(scientific_case, monkeypatch):
    api, root, protocol, _ = scientific_case
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', AsyncMock())
    await store.update('alice', max_iterations=10)
    protocol['stages'][0]['max_experiments'] = 2
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    payload = {'command': ['python', 'train.py'], 'device': 'cpu', 'timeout': 300,
               'config': {'study_step': 'method', 'candidate_id': 'candidate-a', 'operation': 'draft'}}
    with pytest.raises(ValueError, match='closest baseline'):
        await jobs.submit('alice', 'experiment', payload)
    baseline = await jobs.submit('alice', 'experiment', {**payload, 'config': {
        'study_step': 'baseline', 'candidate_id': 'baseline-a', 'operation': 'draft'}})
    async with api.sessions() as db:
        job = await db.get(ResearchJob, baseline['job_id'])
        job.status, job.result = 'completed', {'metrics': {'delta': 0.051}}
        await db.commit()
    first = await jobs.submit('alice', 'experiment', payload)
    with pytest.raises(ValueError, match='Stage attempt allocation'):
        await jobs.submit('alice', 'experiment', {**payload, 'config': {
            **payload['config'], 'candidate_id': 'candidate-b'}})
    assert (await store.get('alice')).current_iteration == 8
    assert len(await store.jobs('alice')) == 2
    protocol['stages'][0]['max_experiments'] = 3
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    with pytest.raises(ValueError, match='Parent must be a settled'):
        await jobs.submit('alice', 'experiment', {**payload, 'config': {
            **payload['config'], 'operation': 'replicate', 'parent_run_id': first['job_id']}})


async def test_direction_switch_and_budget_reallocation_preserve_unrelated_evidence(scientific_case):
    _, root, protocol, _ = scientific_case
    before = (await store.get('alice')).recovery_metadata['study']['step_revisions']
    protocol['selected_direction'] = 'representation'
    protocol['selection_reason'] = 'Investigate a distinct rival without discarding prior evidence'
    protocol['stages'][0]['max_experiments'] = 5
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    assert (await store.get('alice')).recovery_metadata['study']['step_revisions'] == before
    with pytest.raises(ValueError, match='Not publishable yet'):
        await record_review(scientific_case)


async def test_deterministic_baseline_has_its_own_training_and_repeat_target(scientific_case):
    api, root, protocol, _ = scientific_case
    protocol['steps'][0]['scale'].update(train_units=0, repeats=1)
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    session = await store.get('alice')
    async with api.sessions() as db:
        for identity, repeats in [('baseline', {'deterministic': 0.05}), ('method', {'seed-1': 0.0, 'seed-2': 0.001, 'seed-3': -0.001})]:
            row = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == identity))
            config = study.experiment_config(session, {'study_step': identity, 'candidate_id': identity, 'operation': 'draft'})
            config['study_measurement'] = {'unit': 'subject', 'train_units': 0 if identity == 'baseline' else 200,
                'evaluation_units': 100, 'replicate_ids': list(repeats), 'primary_by_replicate': repeats,
                'input_coverage': 'All available inputs',
                'optimization': 'Deterministic' if identity == 'baseline' else 'Converged'}
            row.hyperparams = {'config': config}
        await db.commit()
    decision = json.loads((root / 'decision.json').read_text())
    decision['id'] = 'independent-targets'
    write(root, 'decision-new.json', decision)
    await study.record_decision(await store.get('alice'), 'decision-new.json')
    assert (await record_review(scientific_case))['ready_to_write']


async def test_exploration_only_protocol_cannot_replace_validation_plan(scientific_case):
    _, root, protocol, _ = scientific_case
    protocol['stages'][0]['kind'] = 'exploration'
    write(root, 'protocol.json', protocol)
    with pytest.raises(ValueError, match='adequate-scale'):
        await study.record_protocol(await store.get('alice'), 'protocol.json')


async def test_inconclusive_result_can_scale_but_cannot_discard_direction(scientific_case):
    _, root, _, _ = scientific_case
    decision = json.loads((root / 'decision.json').read_text())
    decision.update(id='uncertain', action='discard', assessment='inconclusive', scope='direction',
                    next_operation='scale', next_action='Increase independent units to the planned validation target')
    write(root, 'uncertain.json', decision)
    with pytest.raises(ValueError, match='Inconclusive evidence'):
        await study.record_decision(await store.get('alice'), 'uncertain.json')
    decision['action'] = 'keep'
    write(root, 'uncertain.json', decision)
    assert (await study.record_decision(await store.get('alice'), 'uncertain.json'))['recorded']


async def test_pilot_cannot_be_promoted_to_direction_conclusion(scientific_case):
    api, root, _, _ = scientific_case
    async with api.sessions() as db:
        row = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'method'))
        config = deepcopy(row.hyperparams)
        config['config']['study_measurement']['evaluation_units'] = 10
        row.hyperparams = config
        await db.commit()
    decision = json.loads((root / 'decision.json').read_text())
    decision.update(id='route-exit', scope='direction')
    write(root, 'decision-new.json', decision)
    with pytest.raises(ValueError, match='target-scale'):
        await study.record_decision(await store.get('alice'), 'decision-new.json')
    decision.update(scope='candidate')
    write(root, 'decision-new.json', decision)
    assert (await study.record_decision(await store.get('alice'), 'decision-new.json'))['recorded']
    with pytest.raises(ValueError, match='measured sample size'):
        await record_review(scientific_case)


def test_failed_execution_cannot_fake_measurement_and_metric(tmp_path):
    config = {'study_scale': {'unit': 'sample'}, 'study_evaluation': {'metric': 'loss'}, 'study_stage_kind': 'validation'}
    write(tmp_path, 'study-result.json', {'unit': 'sample', 'train_units': 40, 'evaluation_units': 20,
          'replicate_ids': ['a', 'a'], 'input_coverage': 'full', 'optimization': '10 epochs'})
    with pytest.raises(ValidationError, match='distinct'):
        study.read_measurement(tmp_path, config, {'loss': .2})
    result = json.loads((tmp_path / 'study-result.json').read_text())
    result['replicate_ids'] = ['a']
    write(tmp_path, 'study-result.json', result)
    with pytest.raises(ValueError, match='primary metric'):
        study.read_measurement(tmp_path, config, {'unrelated': .2})
    assert study.read_measurement(tmp_path, config, {'loss': .2})['evaluation_units'] == 20
    config['study_role'] = 'baseline'
    with pytest.raises(ValueError, match='primary metric'):
        study.read_measurement(tmp_path, config, {'baseline_auc': .8})
    config['study_role'] = 'sanity'
    assert study.read_measurement(tmp_path, config, {'baseline_auc': .8})['evaluation_units'] == 20
    with pytest.raises(ValueError, match='finite numeric metrics'):
        study.read_measurement(tmp_path, config, {})
    config['study_stage_kind'] = 'exploration'
    result['evaluation_units'] = 0
    write(tmp_path, 'study-result.json', result)
    assert study.read_measurement(tmp_path, config, {'gradient_norm': .2})['evaluation_units'] == 0


def test_optional_input_gap_requires_considering_other_routes():
    session = SimpleNamespace(recovery_metadata={'research_standard': 'scientific', 'study': {
        'protocol': {'directions': [{'id': 'supervised'}, {'id': 'self_supervised'}]}}})
    request = {'reason': 'missing_data', 'blocker': 'external_dependency',
               'attempts': [{'action': 'Inspected annotations', 'result': 'No dense labels'}],
               'why_user': 'Need unavailable inputs', 'summary': 'Missing inputs', 'next_steps': ['Provide inputs']}
    with pytest.raises(ValueError, match='route-specific'):
        assess_help(session, request, [])
    request['alternatives'] = [{'direction_id': 'supervised', 'reason': 'No target labels'},
                               {'direction_id': 'self_supervised', 'reason': 'Raw inputs are also unavailable'}]
    assert 'Raw inputs' in assess_help(session, request, [])['detail']


async def test_protocol_schema_is_discoverable_and_rejects_old_contract(scientific_case):
    _, _, protocol, _ = scientific_case
    schemas = await tools.call('alice', 'get_study_schema', {})
    assert 'stages' in schemas['protocol']['required']
    assert 'assessment' in schemas['decision']['required']
    protocol['estimated_experiments'] = 10
    with pytest.raises(ValidationError, match='Extra inputs'):
        study.StudyProtocol.model_validate(protocol)


async def test_scope_update_keeps_plan_and_exposes_required_reconciliation(scientific_case):
    before = (await store.get('alice')).recovery_metadata['study']
    result = await tools.call('alice', 'set_task_scope', {'task_kind': 'experiment', 'report_policy': 'summary',
        'research_standard': 'scientific', 'current_goal': 'Validate the strongest existing candidate at larger scale'})
    after = (await store.get('alice')).recovery_metadata['study']
    assert after['protocol'] == before['protocol'] and after['review'] is None
    assert result['context']['protocol_needs_update']
    with pytest.raises(ValueError, match='goal changed'):
        study.current_protocol(await store.get('alice'))


def test_scale_progress_survives_route_changes_without_summing_samples():
    runs = []
    for i in range(6):
        run = measured_run(f'candidate-{i}', [f'seed-{i}'], n=30)
        run['run_id'] = str(i)
        run['config']['config'].update(study_direction=f'route-{i}', operation='improve')
        runs.append(run)
    state = evidence_progress(runs)
    assert len(state['repeated_scale_windows']) == 1
    assert state['scales'][0]['max_evaluation_units_in_one_run'] == 30
    larger = measured_run('larger', ['seed-1', 'seed-2'], n=500); larger['run_id'] = 'large'
    runs.append(larger)
    state = evidence_progress(runs)
    assert not state['repeated_scale_windows']
    assert state['scales'][0]['max_evaluation_units_in_one_run'] == 500
    assert state['scales'][0]['recent'][-1]['replicate_count'] == 2


def test_cancelled_checkpoint_is_a_valid_debug_parent():
    s = SimpleNamespace(current_iteration=1, max_iterations=5, recovery_metadata={'research_standard': 'scientific',
        'study': {'protocol': {'stages': [stage('pilot', 'exploration', 5)]}}})
    config = {'candidate_id': 'c', 'operation': 'debug', 'parent_run_id': 'cancelled',
              'study_stage': 'pilot', 'study_direction': 'd'}
    previous = [{'job_id': 'cancelled', 'status': 'cancelled', 'kind': 'experiment',
                 'payload': {'config': {'candidate_id': 'c', 'study_stage': 'pilot', 'study_direction': 'd'}}}]
    study.validate_submission(s, {'config': config, 'timeout': 100}, previous)


@pytest.mark.skipif(os.getenv('PATHLAB_TEST_APPTAINER') != '1', reason='Explicit real sandbox integration')
@pytest.mark.parametrize('task', ['tabular', 'sequence', 'retrieval'])
async def test_real_scientific_job_records_measured_evidence(scientific_case, monkeypatch, task):
    """Execute independent CPU workloads through the actual frozen-source sandbox path."""
    from backend.autoresearch.engine import file_catalog, processes
    api, root, protocol, _ = scientific_case
    @asynccontextmanager
    async def database():
        async with api.sessions() as db:
            yield db
    monkeypatch.setattr(processes, 'safe_session', database)
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', AsyncMock())
    monkeypatch.setattr(file_catalog, 'index_tree', AsyncMock(return_value={'items': [], 'count': 0, 'truncated': False}))
    scale = protocol['steps'][1]['scale']
    scale.update(unit=task, train_units=40, evaluation_units=20)
    write(root, 'protocol.json', protocol)
    await study.record_protocol(await store.get('alice'), 'protocol.json')
    # Small deterministic workloads verify execution/recording; they are not research-quality benchmarks.
    (root / 'trial.py').write_text('''import json, os, random
from pathlib import Path
import numpy as np
task = TASK_VALUE
rng = random.Random(17)
train = [(rng.random(), rng.random()) for _ in range(40)]
test = [(rng.random(), rng.random()) for _ in range(20)]
if task == 'tabular':
    x = np.array([[1., a, b] for a,b in train]); y = np.array([2*a-b for a,b in train])
    w = np.linalg.lstsq(x,y,rcond=None)[0]
    loss = float(np.mean([(np.array([1.,a,b])@w-(2*a-b))**2 for a,b in test]))
elif task == 'sequence':
    bias = sum(b-a for a,b in train)/len(train)
    loss = sum((a+bias-b)**2 for a,b in test)/len(test)
else:
    reference = np.array(train)
    loss = float(np.mean([np.square(reference-np.array(q)).sum(1).min() for q in test]))
out = Path(os.environ['OUTPUT_DIR'])
(out/'metrics.json').write_text(json.dumps({'delta':loss}))
(out/'study-result.json').write_text(json.dumps({'unit':task,'train_units':len(train),
 'evaluation_units':len(test),'replicate_ids':['deterministic-17'],
 'input_coverage':'Both measured dimensions', 'optimization':'Deterministic closed-form estimator'}))
'''.replace('TASK_VALUE', repr(task)))
    submitted = await jobs.submit('alice', 'experiment', {'command': ['python', 'trial.py'],
        'device': 'cpu', 'timeout': 120,
        'config': {'study_step': 'method', 'candidate_id': task, 'operation': 'draft'}})
    (root / 'trial.py').write_text('raise RuntimeError("live workspace must not execute")')
    async with api.sessions() as db:
        job = await db.get(ResearchJob, submitted['job_id'])
        job.status = 'running'
        await db.commit()
    result = await jobs.execute_experiment(await store.get('alice'), job, 'cpu')
    assert result['metrics']['delta'] >= 0
    run = next(r for r in await store.experiments('alice') if r['run_id'] == job.job_id)
    assert run['status'] == 'completed'
    assert run['config']['config']['study_measurement']['evaluation_units'] == 20
    assert run['config']['config']['study_measurement']['replicate_ids'] == ['deterministic-17']


def gate_session(jobs_used=0):
    protocol = {
        'stages': [{'id': 'explore', 'kind': 'exploration', 'max_experiments': 20, 'max_job_seconds': 600},
                   {'id': 'full', 'kind': 'validation', 'max_experiments': 20, 'max_job_seconds': 600}],
        'baselines': [{'id': 'published', 'role': 'closest', 'reference': {
            'metric': 'auc', 'value': 0.9, 'direction': 'maximize', 'dataset': 'cohort', 'citation': 'Paper'}}],
        'evaluation': {'metric': 'auc', 'direction': 'maximize', 'minimum_gain': 0.02, 'best_possible': 1.0},
        'directions': [{'id': 'pitch-a', 'premise': None}],
        'steps': [{'id': 'baseline', 'role': 'baseline', 'baseline_id': 'published', 'stage_id': 'full'},
                  {'id': 'method', 'role': 'method', 'direction_id': 'pitch-a', 'stage_id': 'full',
                   'scale': {'repeats': 3}}]}
    return SimpleNamespace(max_iterations=50, current_iteration=jobs_used, recovery_metadata={
        'research_standard': 'scientific', 'study': {'protocol': protocol}})


def gate_job(identity, stage, kind, status='completed', step='method', role='method', operation='draft', auc=None):
    return {'job_id': identity, 'kind': 'experiment', 'status': status,
            'result': {'metrics': {} if auc is None else {'auc': auc}}, 'payload': {'config': {
        'study_stage': stage, 'study_stage_kind': kind, 'study_direction': 'pitch-a', 'study_step': step,
        'study_role': role, 'candidate_id': identity, 'operation': operation, 'parent_run_id': None}}}


def test_subsets_cannot_stand_in_for_a_full_data_comparison():
    session = gate_session()
    payload = {'timeout': 60, 'config': gate_job('next', 'explore', 'exploration')['payload']['config']}
    history = [gate_job(f'pilot-{i}', 'explore', 'exploration') for i in range(3)]
    with pytest.raises(ValueError, match='exploration runs since its last full-scale run'):
        study.validate_submission(session, payload, history)
    debug = gate_job('crash', 'explore', 'exploration', status='failed', operation='debug')
    assert study.exploration_streaks([*history, debug]) == {'pitch-a': 3}
    full = {'timeout': 60, 'config': gate_job('full-a', 'full', 'validation')['payload']['config']}
    with pytest.raises(ValueError, match='closest baseline'):
        study.validate_submission(session, full, history)
    failed_baseline = gate_job('b0', 'full', 'validation', status='failed', step='baseline', role='baseline')
    with pytest.raises(ValueError, match='closest baseline'):
        study.validate_submission(session, full, [*history, failed_baseline])
    queued_baseline = gate_job('b1', 'full', 'validation', status='queued', step='baseline', role='baseline')
    with pytest.raises(ValueError, match='not reproduced'):
        study.validate_submission(session, full, [*history, queued_baseline])
    weak_baseline = gate_job('b2', 'full', 'validation', step='baseline', role='baseline', auc=0.8)
    with pytest.raises(ValueError, match=r'auc 0.8 vs published 0.9'):
        study.validate_submission(session, full, [*history, weak_baseline])
    baseline = gate_job('b3', 'full', 'validation', step='baseline', role='baseline', auc=0.87)
    study.validate_submission(session, full, [*history, weak_baseline, baseline])
    history += [weak_baseline, baseline, gate_job('full-a', 'full', 'validation')]
    study.validate_submission(session, payload, history)


async def test_protocol_validation_runs_on_the_full_declared_data(scientific_case):
    _, root, protocol, _ = scientific_case
    protocol['steps'][1]['scale']['train_units'] = 120
    write(root, 'protocol.json', protocol)
    with pytest.raises(ValueError, match='must use the full cohort data'):
        await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    protocol['steps'][1]['scale']['train_units'] = 200
    protocol['steps'][0]['stage_id'] = 'pilot'
    protocol['stages'].insert(0, {'id': 'pilot', 'kind': 'exploration', 'max_experiments': 2, 'max_job_seconds': 600,
                                  'advance_when': 'Code runs', 'stop_when': 'Never decides a pitch'})
    write(root, 'protocol.json', protocol)
    with pytest.raises(ValueError, match='closest published method on the full data'):
        await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    protocol['directions'] = protocol['directions'][:2]
    write(root, 'protocol.json', protocol)
    with pytest.raises(ValidationError):
        await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})


async def set_method_seeds(api, seeds):
    async with api.sessions() as db:
        run = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'method'))
        config = deepcopy(run.hyperparams)
        config['config']['study_measurement'].update(replicate_ids=list(seeds), primary_by_replicate=seeds)
        run.hyperparams = config
        await db.commit()


async def test_write_requires_the_measured_publication_gain(scientific_case, api):
    await set_method_seeds(api, {'seed-1': 0.04, 'seed-2': 0.041, 'seed-3': 0.039})
    with pytest.raises(ValueError, match='Not publishable yet'):
        await record_review(scientific_case)
    result = await record_review(scientific_case, decision='iterate', goal_met=False,
                                 unresolved=['Gain below the bar'])
    assert result['publication_gain']['bar_met'] is False
    assert result['publication_gain']['gain'] == pytest.approx(0.01)


async def test_scientific_study_cannot_stop_on_an_unpublishable_result(scientific_case):
    with pytest.raises(ValueError, match='Untested pitches'):
        await tools.call('alice', 'finish_research', {'summary': 'Inconclusive', 'outcome': 'partial'})
    meta = (await store.get('alice')).recovery_metadata
    await store.update('alice', meta={'research_decisions': [
        {'direction_id': d['id'], 'scope': 'direction', 'assessment': 'contradicted'} for d in meta['study']['protocol']['directions']]})
    with pytest.raises(ValueError, match="Every pitch is ruled out.*reason='direction'"):
        await tools.call('alice', 'finish_research', {'summary': 'Nothing worked', 'outcome': 'no_result'})
    with pytest.raises(ValueError, match='publication bar'):
        await tools.call('alice', 'finish_research', {'summary': 'Inconclusive', 'outcome': 'no_result',
                                                      'user_stop': 'the user wants to stop'})
    await store.command('alice', 'message', '结果先这样，  请停在这里并总结')
    assert (await tools.call('alice', 'finish_research', {
        'summary': 'Stopped at the user request', 'outcome': 'partial', 'user_stop': '请停在这里'}))['finished']


def test_portfolio_is_exhausted_only_by_full_scale_contradictions():
    def session(decisions):
        return SimpleNamespace(recovery_metadata={'study': {'protocol': {'directions': [
            {'id': 'a'}, {'id': 'b'}, {'id': 'c'}]}}, 'research_decisions': decisions})
    contradicted = [{'direction_id': d, 'scope': 'direction', 'assessment': 'contradicted'} for d in 'ab']
    candidate = [{'direction_id': 'c', 'scope': 'candidate', 'assessment': 'contradicted'}]
    assert study.untested_pitches(session(contradicted + candidate)) == ['c']
    assert study.untested_pitches(session(contradicted + [{**candidate[0], 'scope': 'direction'}])) == []
    assert study.untested_pitches(SimpleNamespace(recovery_metadata={})) == ['(no study protocol recorded)']


def test_scientific_studies_get_multi_day_ceilings():
    from backend.autoresearch.engine.effort import effort_budget
    assert effort_budget('medium', 'scientific') == (120, 172800)
    assert effort_budget('medium', None) == effort_budget('medium', 'standard') == (8, 14400)


async def test_scientific_study_cannot_downgrade_itself_to_finish(scientific_case):
    standard = {'task_kind': 'document', 'report_policy': 'summary', 'research_standard': 'standard',
                'current_goal': 'Write up the data screen'}
    with pytest.raises(ValueError, match='keep research_standard=scientific'):
        await tools.call('alice', 'set_task_scope', standard)
    assert (await store.get('alice')).recovery_metadata['research_standard'] == 'scientific'
    # Sub-steps change task_kind and goal, not the standard.
    await tools.call('alice', 'set_task_scope', {**standard, 'research_standard': 'scientific'})
    with pytest.raises(ValueError, match='keep research_standard=scientific'):
        await tools.call('alice', 'set_task_scope', {**standard, 'user_request': 'just summarize'})
    await store.command('alice', 'message', 'Forget the paper, just summarize the data screen')
    await tools.call('alice', 'set_task_scope', {**standard, 'user_request': 'just summarize the data screen'})
    assert (await store.get('alice')).recovery_metadata['research_standard'] == 'standard'
