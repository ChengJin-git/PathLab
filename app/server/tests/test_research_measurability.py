"""A study must be able to measure its bar: resolution, reproduced baselines, seed noise, reframing."""
# ruff: noqa: PLC0414 -- explicit exports for pytest's imported fixtures.

import json
from copy import deepcopy

import pytest
from backend.autoresearch.engine import recovery, store, study
from backend.autoresearch.engine.study_contract import (
    StudyMeasurement,
    frame_capacity,
    publication_gain,
)
from backend.database.models import AutoResearchExperiment
from pydantic import ValidationError
from sqlalchemy import select
from test_scientific_study import api as api
from test_scientific_study import pitch, write
from test_scientific_study import scientific_case as scientific_case


async def record(root, protocol):
    write(root, 'protocol.json', protocol)
    return await study.record_protocol(await store.get('alice'), 'protocol.json')


async def test_protocol_rejects_unmeasurable_bars(scientific_case):
    _, root, protocol, _ = scientific_case
    coarse = deepcopy(protocol)
    coarse['evaluation']['resolution'] = 1 / 32
    with pytest.raises(ValueError, match='below the metric resolution'):
        await record(root, coarse)
    single = deepcopy(protocol)
    single['steps'][1]['scale']['repeats'] = 1
    with pytest.raises(ValueError, match='at least 3 independent repeats'):
        await record(root, single)
    unanchored = deepcopy(protocol)
    del unanchored['baselines'][0]['reference']
    with pytest.raises(ValueError, match='published reference result'):
        await record(root, unanchored)


def test_publication_bar_requires_repeats_and_a_gain_above_seed_noise():
    protocol = {
        'evaluation': {'metric': 'auc', 'direction': 'maximize', 'minimum_gain': 0.02},
        'stages': [{'id': 'v', 'kind': 'validation'}], 'selected_direction': 'a',
        'baselines': [{'id': 'b', 'role': 'closest'}],
        'steps': [{'id': 'base', 'role': 'baseline', 'baseline_id': 'b', 'stage_id': 'v', 'scale': {'train_units': 9}},
                  {'id': 'm', 'role': 'method', 'direction_id': 'a', 'stage_id': 'v', 'scale': {'train_units': 9}}]}

    def run(identity, seeds):
        return {'run_id': identity, 'metrics': {}, 'config': {'config': {'study_measurement': {
            'replicate_ids': list(seeds), 'primary_by_replicate': seeds}}}}

    base = run('b', {'s1': 0.80, 's2': 0.90, 's3': 0.85})
    noisy = publication_gain(protocol, {'base': [base], 'm': [run('m', {'s1': 0.95, 's2': 0.82, 's3': 0.91})]})
    assert noisy['gain'] == pytest.approx(0.0433, abs=1e-3) and not noisy['bar_met']
    assert any('seed noise' in reason for reason in noisy['missing'])
    two = publication_gain(protocol, {'base': [base], 'm': [run('m', {'s1': 0.95, 's2': 0.96})]})
    assert not two['bar_met'] and any('repeats' in reason for reason in two['missing'])
    clear = publication_gain(protocol, {'base': [base], 'm': [run('m', {'s1': 0.94, 's2': 0.95, 's3': 0.96})]})
    assert clear['bar_met'] and clear['missing'] == []
    # One seed reported by two runs counts once.
    single = {'run_id': 'x', 'metrics': {'auc': 0.95}, 'config': {'config': {'study_measurement': {'replicate_ids': ['s1']}}}}
    assert publication_gain(protocol, {'base': [base], 'm': [single, deepcopy(single)]})['method_repeats'] == 1


def test_per_seed_metrics_must_match_the_declared_repeats():
    fields = {'unit': 'slide', 'train_units': 1, 'evaluation_units': 1, 'input_coverage': 'all', 'optimization': 'x'}
    with pytest.raises(ValidationError, match='exactly the replicate_ids'):
        StudyMeasurement(**fields, replicate_ids=['a', 'b'], primary_by_replicate={'a': 0.5})
    assert StudyMeasurement(**fields, replicate_ids=['a'], primary_by_replicate={'a': 0.5})


async def test_direction_is_ruled_out_only_after_tuning(scientific_case):
    api, root, _, _ = scientific_case
    decision = json.loads((root / 'decision.json').read_text())
    decision.update(id='no-headroom', direction_id='conditional', action='pivot', assessment='contradicted',
                    scope='direction', next_operation='draft', run_ids=['method'])
    write(root, 'contradicted.json', decision)
    with pytest.raises(ValueError, match='1 tried candidate'):
        await study.record_decision(await store.get('alice'), 'contradicted.json')
    session = await store.get('alice')
    async with api.sessions() as db:
        method = await db.scalar(select(AutoResearchExperiment).where(AutoResearchExperiment.training_task_id == 'method'))
        for candidate in ['tuned-lr', 'tuned-loss']:
            config = deepcopy(method.hyperparams)
            config['config'].update(study.experiment_config(session, {
                'study_step': 'method', 'candidate_id': candidate, 'operation': 'draft'}))
            db.add(AutoResearchExperiment(session_id='alice', training_task_id=candidate, experiment_name=candidate,
                                          status='completed', iteration=7, metrics=method.metrics, hyperparams=config))
        await db.commit()
    assert (await study.record_decision(await store.get('alice'), 'contradicted.json'))['recorded']


async def test_repeated_failures_require_a_new_frame_before_more_pitches(scientific_case):
    _, root, protocol, _ = scientific_case
    await record(root, protocol)
    await store.update('alice', meta={'research_decisions': [
        {'direction_id': d['id'], 'scope': 'direction', 'assessment': 'contradicted'} for d in protocol['directions']]})
    more = deepcopy(protocol)
    more['directions'].append(pitch('ensemble', 'Another local variant'))
    more['selected_direction'] = 'ensemble'
    more['steps'][1]['direction_id'] = 'ensemble'
    with pytest.raises(ValueError, match='3 pitches were ruled out'):
        await record(root, more)
    # Only switching among declared pitches stays possible within the frame.
    reframed = deepcopy(more)
    reframed['data'][0]['name'] = reframed['steps'][0]['scale']['dataset'] = 'cohort-cv'
    reframed['steps'][1]['scale']['dataset'] = 'cohort-cv'
    assert (await record(root, reframed))['revision']
    stored = (await store.get('alice')).recovery_metadata['study']
    assert sorted(stored['frame_ruled_out']) == sorted(d['id'] for d in protocol['directions'])
    assert len(stored['exhausted_frames']) == 1


def capacity_protocol(best=1.0):
    return {'evaluation': {'metric': 'auc', 'direction': 'maximize', 'minimum_gain': 0.02, 'best_possible': best},
            'stages': [{'id': 'v', 'kind': 'validation'}],
            'baselines': [{'id': 'b', 'role': 'closest'}],
            'directions': [{'id': 'a', 'premise': None},
                           {'id': 'p', 'premise': {'step_id': 'effect', 'metric': 'dilution_auc'}}],
            'steps': [{'id': 'base', 'role': 'baseline', 'baseline_id': 'b', 'stage_id': 'v', 'scale': {'train_units': 9}},
                      {'id': 'effect', 'role': 'mechanism', 'stage_id': 'v', 'scale': {'train_units': 9, 'repeats': 3}},
                      {'id': 'm', 'role': 'method', 'direction_id': 'a', 'stage_id': 'v',
                       'scale': {'train_units': 9, 'repeats': 3}},
                      {'id': 'mp', 'role': 'method', 'direction_id': 'p', 'stage_id': 'v',
                       'scale': {'train_units': 9, 'repeats': 3}}]}


def seeds_run(identity, seeds):
    return {'run_id': identity, 'metrics': {}, 'config': {'config': {'study_measurement': {
        'replicate_ids': list(seeds), 'primary_by_replicate': seeds}}}}


def test_frame_capacity_needs_headroom_and_resolvable_noise():
    protocol = capacity_protocol()
    assert frame_capacity(protocol, {'base': [seeds_run('b', {'s1': 0.95, 's2': 0.96})]}) is None
    # A saturated baseline (CAMELYON17-like 0.964) leaves less than 3 x 0.02 for any method.
    saturated = frame_capacity(protocol, {'base': [seeds_run('b', {'s1': 0.9538, 's2': 0.9741, 's3': 0.9626})]})
    assert not saturated['sufficient'] and 'best possible' in saturated['problems'][0]
    roomy = frame_capacity(protocol, {'base': [seeds_run('b', {'s1': 0.80, 's2': 0.81, 's3': 0.79})]})
    assert roomy['sufficient'] and roomy['required_repeats'] == 3
    noisy = frame_capacity(protocol, {'base': [seeds_run('b', {'s1': 0.70, 's2': 0.80, 's3': 0.75})]})
    assert not noisy['sufficient'] and 'repeats per arm' in noisy['problems'][0]
    unbounded = frame_capacity(capacity_protocol(best=None), {'base': [seeds_run('b', {'s1': 0.99, 's2': 0.99, 's3': 0.99})]})
    assert unbounded['sufficient'] and unbounded['headroom'] is None


def capacity_job(identity, step, metrics, seeds=None):
    config = {'study_step': step, 'study_step_revision': step}
    if seeds:
        config['study_measurement'] = {'replicate_ids': list(seeds), 'primary_by_replicate': seeds}
    return {'job_id': identity, 'kind': 'experiment', 'status': 'completed',
            'result': {'metrics': metrics}, 'payload': {'config': config}}


def test_method_runs_wait_for_a_frame_and_premise_that_can_clear_the_bar():
    record = {'protocol': capacity_protocol(), 'step_revisions': {s: s for s in ['base', 'effect', 'm', 'mp']}}
    saturated = [capacity_job('b', 'base', {}, {'s1': 0.96, 's2': 0.97, 's3': 0.965})]
    with pytest.raises(ValueError, match='cannot show minimum_gain'):
        study.check_frame_capacity(record, saturated, {'study_step': 'm', 'study_direction': 'a'})
    roomy = [capacity_job('b', 'base', {}, {'s1': 0.80, 's2': 0.81, 's3': 0.79})]
    study.check_frame_capacity(record, roomy, {'study_step': 'm', 'study_direction': 'a'})
    with pytest.raises(ValueError, match='Measure it on the full data'):
        study.check_frame_capacity(record, roomy, {'study_step': 'mp', 'study_direction': 'p'})
    small = [*roomy, capacity_job('e', 'effect', {'dilution_auc': -0.009})]
    with pytest.raises(ValueError, match='below minimum_gain'):
        study.check_frame_capacity(record, small, {'study_step': 'mp', 'study_direction': 'p'})
    large = [*roomy, capacity_job('e', 'effect', {'dilution_auc': -0.05})]
    study.check_frame_capacity(record, large, {'study_step': 'mp', 'study_direction': 'p'})


async def test_premise_must_name_a_mechanism_step(scientific_case):
    _, root, protocol, _ = scientific_case
    bad = deepcopy(protocol)
    bad['directions'][0]['premise'] = {'step_id': 'baseline', 'metric': 'effect'}
    with pytest.raises(ValueError, match='premise must name a mechanism step'):
        await record(root, bad)


def test_direction_help_waits_for_a_second_exhausted_frame():
    help_args = {'reason': 'direction', 'blocker': 'decision', 'summary': 'Pitches failed', 'next_steps': ['a'],
                 'why_user': 'Choose a route', 'attempts': [{'action': 'Ran 3 pitches', 'result': 'All below the bar'}]}
    ruled_out = [{'direction_id': d, 'scope': 'direction', 'assessment': 'contradicted'} for d in 'abc']
    meta = {'research_standard': 'scientific', 'research_decisions': ruled_out,
            'study': {'protocol': {'directions': []}, 'frame_ruled_out': [], 'exhausted_frames': []}}
    session = type('S', (), {'recovery_metadata': meta})()
    with pytest.raises(ValueError, match='Choosing a new frame is your job'):
        recovery.assess_help(session, help_args, [])
    meta['study']['exhausted_frames'] = ['first-frame']
    assert recovery.assess_help(session, help_args, [])['reason'] == 'direction'
