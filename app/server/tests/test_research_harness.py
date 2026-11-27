"""Research continuation is tied to measurements, not prose or stale plans."""
# ruff: noqa: PLC0414 -- explicit exports for pytest's imported fixtures.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_scientific_study import api as api
from test_scientific_study import record_review, write
from test_scientific_study import scientific_case as scientific_case

from backend.autoresearch.engine import harness, jobs, store, tools
from backend.autoresearch.engine.client import OpenCodeClient
from backend.autoresearch.engine.research_progress import (
    completed_job_summary,
    metric_summary,
    protocol_execution,
    strategy_checkpoint,
)


def test_prose_and_repeated_snapshots_do_not_reset_idle_progress():
    watch = harness.ProgressWatch()
    watch.observe([])
    watch.resume()
    assert not watch.observe([{'id': 'm1', 'content': [{'type': 'text', 'text': 'Working'}]}])
    assert watch.idle_turns == 1
    tool = {'id': 'm2', 'content': [{'id': 't1', 'type': 'tool', 'state': {'status': 'completed'}}]}
    assert watch.observe([tool]) and watch.idle_turns == 0
    watch.resume()
    assert not watch.observe([tool]) and watch.idle_turns == 1
    tool['id'], tool['content'][0]['id'] = 'new-message', 'same-read-again'
    assert not watch.observe([tool]) and watch.idle_turns == 1


async def test_live_context_has_budget_decisions_and_pending_instructions(scientific_case, monkeypatch):
    capacity = [{'device': 'cuda:6', 'total_mb': 24576, 'free_mb': 6928, 'available_mb': 6928}]
    monkeypatch.setattr('backend.common.task_runtime.get_runtime_status', AsyncMock(return_value={'is_running': True, 'gpu_capacity': capacity}))
    await store.command('alice', 'message', 'Investigate the representation route now')
    context = await tools.call('alice', 'get_research_context', {})
    assert context['budget']['remaining'] == 2
    assert context['compute']['worker_available']
    assert context['compute']['gpus'] == capacity
    assert 'scheduler selects a fitting GPU' in context['compute']['assignment']
    assert context['recent_decisions'][0]['action'] == 'keep'
    assert 'sources' not in context['recent_decisions'][0]
    assert 'source_hashes' not in context['recent_decisions'][0]
    assert context['pending_instructions'][0]['text'] == 'Investigate the representation route now'
    assert context['recent_instructions'][-1]['text'] == 'Investigate the representation route now'
    assert context['working_goal'] == 'Explain conditional errors beyond the closest method'
    assert context['original_request'] == (await store.get('alice')).research_question
    assert 'goal' not in context
    assert 'method' not in context['unreviewed_runs']
    prompt = await harness.continuation_prompt(await store.get('alice'), stalled=True)
    assert 'record_research_decision' in prompt and 'Investigate the representation route' in prompt


async def test_instruction_history_survives_delivery_without_promoting_agent_text(scientific_case):
    await store.command('alice', 'message', 'Compare forecasting methods on future periods')
    await store.update('alice', event={'kind': 'command', 'status': 'delivered', 'command_id': 'delivered'})
    await store.update('alice', event={'kind': 'scope', 'current_goal': 'Only compare exactly equal residual counts'})
    await store.update('alice', event={'kind': 'message', 'message': {'type': 'user', 'text': 'Synthetic supervisor prompt'}})
    await store.command('alice', 'message', 'Use grouped validation and finish the comparison')
    await store.update('alice', meta={'commands': []})
    instructions = await store.recent_instructions('alice', limit=2)
    assert [item['text'] for item in instructions] == [
        'Compare forecasting methods on future periods', 'Use grouped validation and finish the comparison']
    assert instructions[0]['seq'] < instructions[1]['seq']
    assert await store.recent_instructions('absent') == []


def test_execution_coverage_ignores_stale_failed_and_unplanned_evidence():
    scale = {'unit': 'sample', 'train_units': 10, 'evaluation_units': 5, 'repeats': 2}
    study = {'protocol': {'steps': [
        {'id': 'baseline', 'role': 'baseline', 'required': True, 'stage_id': 'validation', 'scale': scale},
        {'id': 'method', 'role': 'method', 'required': True, 'stage_id': 'validation', 'scale': scale},
        {'id': 'repeat', 'role': 'replication', 'required': True, 'stage_id': 'validation', 'scale': scale},
        {'id': 'optional', 'role': 'ablation', 'required': False, 'stage_id': 'validation', 'scale': scale},
    ], 'stages': [{'id': 'validation'}]},
        'step_revisions': {'baseline': 'b', 'method': 'm', 'repeat': 'r', 'optional': 'a'}}
    def run(step, fingerprint, status='completed'):
        return {'status': status, 'config': {'config': {'study_step': step, 'study_step_revision': fingerprint}}}
    runs = [run('baseline', 'b'), run('baseline', 'b'), run('method', 'old'),
            run('method', 'm', 'failed'), run('repeat', 'r', 'running'),
            run('optional', 'a'), run('retired', 'x'), {'status': 'completed'}]
    state = protocol_execution(study, runs)
    assert state['required_steps_by_role'] == {'baseline': 1, 'method': 1, 'replication': 1}
    assert state['executed_required_steps_by_role'] == {'baseline': 1}
    assert state['required_steps_without_current_evidence'] == ['method', 'repeat']
    runs.append(run('method', 'm'))
    assert protocol_execution(study, runs)['required_steps_without_current_evidence'] == ['repeat']
    assert protocol_execution({}, runs) is None


async def test_new_ablation_reuses_only_unchanged_step_fingerprints(scientific_case):
    _, root, protocol, _ = scientific_case
    before = (await store.get('alice')).recovery_metadata['study']['step_revisions']
    protocol['steps'].append({'id': 'ablation', 'role': 'ablation', 'question': 'Remove residual input',
                             'stage_id': 'validation', 'direction_id': 'conditional', 'required': False,
                             'scale': protocol['steps'][1]['scale']})
    write(root, 'protocol.json', protocol)
    await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    after = (await store.get('alice')).recovery_metadata['study']['step_revisions']
    assert before.items() <= after.items()
    assert (await record_review(scientific_case))['ready_to_write']
    protocol['directions'][0]['claim'] = 'An entirely different method'
    write(root, 'protocol.json', protocol)
    await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    changed = (await store.get('alice')).recovery_metadata['study']['step_revisions']
    assert changed['baseline'] == before['baseline']
    assert changed['method'] != before['method']
    with pytest.raises(ValueError, match='completed runs'):
        await record_review(scientific_case)


async def test_stage_plan_compares_unspent_allocations_with_remaining_authorization(scientific_case):
    _, root, protocol, _ = scientific_case
    protocol['stages'][0]['max_experiments'] = 2
    write(root, 'protocol.json', protocol)
    result = await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    assert result['budget_sufficient']
    assert result['additional_experiments_needed'] == result['remaining_experiments'] == 2
    protocol['stages'][0]['max_experiments'] = 3
    write(root, 'protocol.json', protocol)
    result = await tools.call('alice', 'record_study_protocol', {'path': 'protocol.json'})
    assert not result['budget_sufficient']
    assert result['additional_experiments_needed'] == 3


async def test_decision_response_keeps_evidence_in_store_not_every_tool_result(scientific_case):
    result = await tools.call('alice', 'record_research_decision', {'path': 'decision.json'})
    assert result['recorded']
    assert 'sources' not in result['decision'] and 'source_hashes' not in result['decision']
    assert result['decision']['next_action']
    stored = (await store.get('alice')).recovery_metadata['research_decisions'][0]
    assert stored['source_hashes'] and 'sources' not in stored


def test_strategy_checkpoint_detects_busy_repair_loop_without_claiming_scientific_failure():
    session = SimpleNamespace(recovery_metadata={
        'task_kind': 'experiment', 'research_standard': 'scientific',
        'research_decisions': [{'action': action, 'direction_id': 'one'}
                               for action in ['keep', 'repair', 'repair', 'discard']],
    })
    runs = [{'status': 'completed'}] * 4
    jobs = [{'job_id': 'trial', 'kind': 'experiment', 'status': 'completed', 'updated_at': 1,
             'result': {'duration_seconds': 100}}]
    jobs += [{'job_id': f'analysis-{i}', 'kind': 'computation', 'status': 'completed',
              'updated_at': i + 2, 'result': {'duration_seconds': 200}} for i in range(3)]
    jobs += [{'job_id': 'live', 'kind': 'experiment', 'status': 'running'}]
    state = strategy_checkpoint(session, runs, jobs)
    assert state['completed_experiments'] == 4
    assert state['computations_since_completed_experiment'] == 3
    assert len(state['concerns']) == 3
    assert state['completed_job_seconds_by_kind'] == {'experiment': 100, 'computation': 600}
    assert 'not an audit' in state['next_action'] and 'interrupt live jobs' in state['next_action']
    session.recovery_metadata['research_decisions'][-1]['action'] = 'pivot'
    assert not any('Repeated repair/discard' in c for c in strategy_checkpoint(session, runs, jobs)['concerns'])
    # An older-submitted experiment finishes last; completion order is decisive.
    jobs.insert(0, {'job_id': 'new-result', 'kind': 'experiment', 'status': 'completed', 'updated_at': 5})
    assert strategy_checkpoint(session, runs, jobs)['computations_since_completed_experiment'] == 0
    # A scientific study keeps its checkpoint through analysis sub-steps; standard work has none.
    session.recovery_metadata['task_kind'] = 'analysis'
    assert strategy_checkpoint(session, runs, jobs) is not None
    session.recovery_metadata['research_standard'] = 'standard'
    assert strategy_checkpoint(session, runs, jobs) is None


def test_job_notification_is_compact_but_keeps_failure_and_output_locations():
    job = {'job_id': 'one', 'kind': 'experiment', 'status': 'failed',
           'payload': {'name': 'Trial', 'config': {'large_source': 'x' * 100000}},
           'result': {'error': 'Timed out', 'log_path': 'runs/one/run.log',
                      'artifact_directory': 'runs/one/output', 'artifacts': [{'path': 'x'}] * 1000}}
    summary = completed_job_summary(job)
    assert summary['error'] == 'Timed out' and summary['log_path'] == 'runs/one/run.log'
    assert summary['artifact_directory'] == 'runs/one/output'
    assert len(json.dumps(summary)) < 500


def test_large_metric_tables_do_not_crowd_out_the_research_goal():
    small = {'auc': .75, 'comparison': {'delta': .02}}
    assert metric_summary(small) == {'metrics': small}
    large = {**small, 'cases': [{'id': i, 'predictions': [0.2] * 100} for i in range(100)]}
    summary = metric_summary(large)
    assert summary['metrics'] == {'auc': .75}
    assert summary['metrics_truncated'] and 'cases' in summary['metric_sections']
    assert len(json.dumps(summary)) < 500


async def test_context_keeps_older_active_jobs_but_summarizes_settled_history(scientific_case, monkeypatch):
    records = [{'job_id': str(i), 'kind': 'computation', 'status': 'completed', 'payload': {}}
               for i in range(30)]
    records[0]['status'] = 'running'
    monkeypatch.setattr(store, 'jobs', AsyncMock(return_value=records))
    state = await harness.context(await store.get('alice'))
    assert state['job_counts'] == {'running': 1, 'completed': 29}
    assert [j['job_id'] for j in state['jobs']] == list(map(str, range(30)))
    assert 'scheduling' in state['jobs'][0] and 'scheduling' in state['jobs'][18]
    assert 'scheduling' not in state['jobs'][1]


@pytest.mark.parametrize('change', ['unknown_run', 'wrong_direction', 'rewrite'])
async def test_decision_ledger_rejects_unmeasured_or_mutated_decisions(scientific_case, change):
    _, root, _, _ = scientific_case
    decision = json.loads((root / 'decision.json').read_text())
    if change == 'unknown_run':
        decision.update(id='new', run_ids=['not-executed'])
    elif change == 'wrong_direction':
        decision.update(id='new', direction_id='representation')
    else:
        decision['interpretation'] = 'Changed without a new ID'
    write(root, 'decision.json', decision)
    with pytest.raises(ValueError):
        await tools.call('alice', 'record_research_decision', {'path': 'decision.json'})
    assert len((await store.get('alice')).recovery_metadata['research_decisions']) == 1


async def test_final_review_requires_a_measured_decision(scientific_case):
    await store.update('alice', meta={'research_decisions': [], 'assessed_runs': {}})
    with pytest.raises(ValueError, match='measured research decisions'):
        await record_review(scientific_case)


async def test_user_goal_change_still_allows_assessing_the_previous_route(scientific_case):
    _, root, _, _ = scientific_case
    await tools.call('alice', 'set_task_scope', {'task_kind': 'experiment', 'report_policy': 'summary',
        'research_standard': 'scientific', 'current_goal': 'Now investigate representation learning'})
    decision = json.loads((root / 'decision.json').read_text())
    decision.update(id='pivot-after-steer', action='pivot', next_action='Implement the new encoder route')
    write(root, 'decision.json', decision)
    result = await tools.call('alice', 'record_research_decision', {'path': 'decision.json'})
    assert result['recorded'] and result['decision']['run_protocol_revisions']


async def test_development_computation_does_not_require_final_scientific_protocol(scientific_case, monkeypatch):
    await store.update('alice', meta={'study': None})
    monkeypatch.setattr(jobs, 'enqueue_task_descriptor', AsyncMock())
    result = await jobs.submit('alice', 'computation', {'name':'Data diagnostic', 'command':['python','diagnose.py'], 'device':'cpu'})
    assert result['status'] == 'queued'
    assert (await store.get('alice')).current_iteration == 6


async def test_native_shell_and_queued_message_are_live_work():
    client = OpenCodeClient('http://test', 'test')
    async def request(method, path, **kwargs):
        if path == '/api/session/active': return {'data': {}}
        if path.endswith('/inbox'): return {'data': [{'id': 'pending'}]}
        if path == '/api/shell':
            assert kwargs['params'] == {'location[directory]': '/owned'}
            return {'data': [{'id': 'shell', 'status': 'running'}, {'id': 'old', 'status': 'exited'}]}
        return {'data': {'id': 'root', 'location': {'directory': '/owned'}}}
    client.request = AsyncMock(side_effect=request)
    try:
        state = await client.work_state('root')
        assert state == {'root_active': False, 'children': [], 'inbox': 1, 'shells': [{'id': 'shell', 'status': 'running'}]}
        assert await client.active('root')
    finally:
        await client.close()


async def test_recovery_finds_crashed_grandchildren_without_an_outcome_and_skips_live_work():
    client = OpenCodeClient('http://test', 'test')
    async def request(method, path, **kwargs):
        if path == '/api/session/active': return {'data': {'still-active': {}}}
        parent = kwargs['params']['parentID']
        if parent == 'root':
            return {'data': [{'id':'child','time':{'busy':1,'idle':2},'outcome':'succeeded'},
                             {'id':'still-active','time':{'busy':10}}]}
        if parent == 'child':
            return {'data': [{'id':'grandchild','title':'unfinished audit','time':{'busy':10,'idle':4}},
                             {'id':'failed','time':{'busy':1,'idle':2},'outcome':'failed'}]}
        return {'data': []}
    client.request = AsyncMock(side_effect=request)
    try:
        assert await client.interrupted_children('root') == [
            {'id':'grandchild','title':'unfinished audit','outcome':'interrupted'},
            {'id':'failed','title':None,'outcome':'failed'},
        ]
    finally:
        await client.close()
