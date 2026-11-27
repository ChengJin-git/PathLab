"""Measured activity and strategy reminders, not an automated scientific verdict."""

import json
from collections import Counter

from .study_contract import (
    REFRAME_AFTER,
    baseline_reproduction,
    exploration_streaks,
    frame,
    frame_capacity,
    measured_scale_progress,
    publication_gain,
    stage_budget,
)


def protocol_execution(study, runs, replication_groups=()):
    """Report current step evidence using the same identity rules as study review."""
    protocol = study.get('protocol')
    if not protocol:
        return None
    fingerprints = study.get('step_revisions', {})
    completed = set()
    matched = {}
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        step = config.get('study_step')
        if (run['status'] == 'completed' and step in fingerprints
                and config.get('study_step_revision') == fingerprints[step]):
            completed.add(step)
            matched.setdefault(step, []).append(run)
    required = [step for step in protocol['steps'] if step['required']]
    progress = {step['id']: measured_scale_progress(step, matched.get(step['id'], []), replication_groups)
                for step in required}
    planned = Counter(step['role'] for step in required)
    executed = Counter(step['role'] for step in required if step['id'] in completed)
    return {
        'required_steps_by_role': dict(planned),
        'executed_required_steps_by_role': dict(executed),
        'required_steps_without_current_evidence': [step['id'] for step in required if step['id'] not in completed],
        'required_steps_below_planned_scale': [step['id'] for step in required if not progress[step['id']]['complete']],
        'measured_repeats_by_step': progress,
        'note': 'Execution coverage only: a completed step does not establish adequate sample size, optimization, replication or scientific merit. Retire superseded steps from the active protocol; retain their evidence in the ledger.',
    }


def strategy_checkpoint(session, runs, jobs):
    meta = session.recovery_metadata or {}
    if meta.get('research_standard') != 'scientific':
        return None
    decisions = meta.get('research_decisions', [])
    recent = decisions[-6:]
    settled = [run for run in runs if run['status'] in {'completed', 'failed'}]
    completed = [run for run in settled if run['status'] == 'completed']
    maintenance = []
    for job in sorted(jobs, key=lambda j: j.get('updated_at', 0), reverse=True):
        if job['kind'] == 'experiment' and job['status'] == 'completed':
            break
        if job['kind'] == 'computation' and job['status'] == 'completed':
            maintenance.append(job['job_id'])
    directions = {d['direction_id'] for d in recent}
    same_route_repairs = (len(recent) >= 4 and len(directions) == 1
                         and sum(d['action'] in {'repair', 'discard'} for d in recent) >= 3
                         and not any(d['action'] == 'pivot' for d in recent))
    concerns = []
    evidence = evidence_progress(runs)
    if evidence['repeated_scale_windows']:
        concerns.append('Several completed comparisons reuse the same sample-count scale across candidate changes. Choose whether precision, input support or optimization limits the decision before another local variant; consider a larger development comparison or replication. Counts alone do not establish repeated use of the same cases or scientific stagnation.')
    if same_route_repairs:
        concerns.append('Repeated repair/discard decisions on one route: compare a structurally different explanation before another local tweak.')
    if len(maintenance) >= 3:
        concerns.append('Several computation jobs since the last completed experiment: explain which uncertainty changes the next research decision; reuse unchanged verified outputs.')
    if len(settled) >= 4:
        concerns.append('Reassess the primary comparison and strongest simple baseline, not only training fit or validation completeness.')
    comparators = comparator_progress(meta.get('study') or {}, runs)
    if comparators and comparators['method_runs'] >= 3 and comparators['missing_closest_steps']:
        concerns.append('Several method trials precede current closest-method evidence. Reproduce the strongest relevant comparator before another family of local variants; a gain over a weak baseline cannot establish the proposed contribution. Reuse compatible historical evidence when appropriate.')
    study = meta.get('study') or {}
    publication = None
    if study.get('protocol'):
        current = {}
        for run in completed:
            config = run.get('config', {}).get('config') or {}
            step = config.get('study_step')
            if step in study.get('step_revisions', {}) and config.get('study_step_revision') == study['step_revisions'][step]:
                current.setdefault(step, []).append(run)
        try:
            publication = publication_gain(study['protocol'], current)
        except ValueError as exc:
            publication = {'error': str(exc)}
        try:
            capacity = frame_capacity(study['protocol'], current)
        except ValueError:
            capacity = None
        if capacity and not capacity['sufficient']:
            concerns.append('This frame cannot show minimum_gain (' + '; '.join(capacity['problems']) + '). Change data, '
                            'endpoint or evaluation within the user\'s question before building methods.')
        closed = {d['direction_id'] for d in decisions if d['scope'] == 'direction' and d['assessment'] == 'contradicted'}
        reproduction = baseline_reproduction(study['protocol'], [
            {'config': run.get('config', {}).get('config') or {}, 'metrics': run.get('metrics') or {}} for run in completed])
        failed_in_frame = sorted(closed - set(study.get('frame_ruled_out', []))) if study.get('frame') == frame(study['protocol']) else []
        if reproduction and not any(item['reproduced'] for item in reproduction):
            concerns.append('The closest baseline has not reproduced its published number on the full data. Fix the pipeline '
                            '(input fidelity, features, tuning, split) before judging any method against it.')
        if len(failed_in_frame) >= REFRAME_AFTER:
            concerns.append(f'{len(failed_in_frame)} pitches failed under the current evaluation, data and baselines. Revisit '
                            "that frame yourself: new data, endpoint or evaluation that still answers the user's question.")
        publication = {'measured': publication,
                       'baseline_reproduction': reproduction,
                       'ruled_out_in_frame': failed_in_frame,
                       'frame_capacity': capacity,
                       'minimum_gain': study['protocol']['evaluation']['minimum_gain'],
                       'selected_pitch': study['protocol']['selected_direction'],
                       'untested_pitches': [d['id'] for d in study['protocol']['directions'] if d['id'] not in closed],
                       'exploration_runs_since_full_scale': exploration_streaks(jobs)}
        if not (publication['measured'] or {}).get('bar_met'):
            concerns.append('The publication bar is not met. Next batch: the selected pitch and the closest baseline on the full data with independent repeats, tuning or a substantive method improvement, or a pivot to the next pitch.')
    durations = Counter()
    for job in jobs:
        if job['status'] == 'completed':
            durations[job['kind']] += (job.get('result') or {}).get('duration_seconds', 0)
    return {
        'protocol_execution': protocol_execution(meta.get('study') or {}, runs, meta.get('replication_groups', [])),
        'stage_budget': stage_budget(session, jobs),
        'candidates': candidate_summary(runs),
        'evidence_progress': evidence,
        'comparator_progress': comparators,
        'completed_experiments': len(completed),
        'failed_experiments': len(settled) - len(completed),
        'recent_decision_actions': dict(Counter(d['action'] for d in recent)),
        'recent_directions': sorted(directions),
        'computations_since_completed_experiment': len(maintenance),
        'completed_job_seconds_by_kind': {key: round(value, 1) for key, value in durations.items()},
        'timing_note': 'Job duration sums can overlap and include validation/I/O; they are not elapsed time or GPU compute time.',
        'publication': publication,
        'concerns': concerns,
        'next_action': (
            'Write one research-log.md entry: bar, best full-scale gain and its standard error, next batch. Pick the batch most '
            'likely to raise the full-scale gain: tune or improve the method, run more repeats, or pivot to the next pitch. '
            'Ablate only after the bar is met. This is a planning reminder, not an audit or a reason to interrupt live jobs.'
        ),
    }


def comparator_progress(study, runs):
    """Expose comparator sequencing; execution coverage is not a novelty verdict."""
    protocol = study.get('protocol')
    if not protocol:
        return None
    closest = {b['id'] for b in protocol['baselines'] if b['role'] == 'closest'}
    steps = {s['id']: s for s in protocol['steps']
             if s['required'] and s['role'] == 'baseline' and s.get('baseline_id') in closest}
    matched, before, methods, first = set(), 0, 0, None
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        if run['status'] != 'completed':
            continue
        step = config.get('study_step')
        if step in steps and config.get('study_step_revision') == study.get('step_revisions', {}).get(step):
            matched.add(step)
            first = first or run['run_id']
        if config.get('study_role') in {'method', 'mechanism', 'ablation'}:
            methods += 1
            if first is None:
                before += 1
    return {'missing_closest_steps': sorted(set(steps) - matched), 'method_runs': methods,
            'method_runs_before_first_current_closest': before, 'first_current_closest_run': first,
            'note': 'Current comparison fingerprints only. Missing current evidence is not proof that a historical baseline was never run. Assess contribution, fair tuning and transfer separately from execution completion.'}


def evidence_progress(runs):
    """Track measured scale across route changes without treating job volume as evidence."""
    groups = {}
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        measurement = config.get('study_measurement')
        if run['status'] != 'completed' or not measurement:
            continue
        unit = measurement['unit']
        groups.setdefault(unit, []).append({
            'run_id': run['run_id'], 'train_units': measurement['train_units'],
            'evaluation_units': measurement['evaluation_units'],
            'candidate_id': config.get('candidate_id'), 'direction_id': config.get('study_direction'),
            'operation': config.get('operation'), 'stage_kind': config.get('study_stage_kind'),
            'replicate_count': len(set(measurement['replicate_ids'])),
        })
    windows, scales = [], []
    for unit, records in groups.items():
        recent = records[-6:]
        sizes = {r['evaluation_units'] for r in recent}
        scales.append({'unit': unit, 'completed_measured_runs': len(records),
                       'max_train_units_in_one_run': max(r['train_units'] for r in records),
                       'max_evaluation_units_in_one_run': max(r['evaluation_units'] for r in records),
                       'recent': recent})
        if len(recent) >= 5 and len(sizes) == 1 and len({r['candidate_id'] for r in recent}) >= 3:
            windows.append({'unit': unit, 'train_units_range': [min(r['train_units'] for r in recent), max(r['train_units'] for r in recent)],
                            'evaluation_units': recent[0]['evaluation_units'],
                            'run_ids': [r['run_id'] for r in recent]})
    return {'scales': scales, 'repeated_scale_windows': windows,
            'note': 'Sample counts are per run, never summed into independent sample size. Stage names do not certify adequate precision or held-out confirmation. Use data identity, uncertainty, convergence and information coverage to interpret these signals.'}


def decision_summary(decision):
    """Keep the next action visible without replaying large evidence snapshots."""
    return {key: decision[key] for key in (
        'id', 'direction_id', 'action', 'assessment', 'scope', 'next_operation', 'run_ids', 'observation', 'interpretation',
        'next_action', 'evidence_files', 'run_protocol_revisions',
    ) if key in decision}


def candidate_summary(runs):
    """Latest candidates with comparable measurements, not a cross-contract leaderboard."""
    candidates = {}
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        candidate = config.get('candidate_id')
        if not candidate:
            continue
        entry = candidates.pop(candidate, {'candidate_id': candidate, 'runs': []})
        candidates[candidate] = entry
        entry['runs'].append({
            'run_id': run['run_id'], 'status': run['status'],
            'parent_run_id': config['parent_run_id'], 'operation': config['operation'],
            'direction_id': config.get('study_direction'), 'stage_id': config['study_stage'],
            'comparison_revision': config['study_step_revision'],
            # Prose fields (coverage, optimization) live in the run config; keep wakeups small.
            'measurement': {key: value for key, value in (config.get('study_measurement') or {}).items()
                            if key not in {'unit', 'input_coverage', 'optimization'}},
            'metric': config['study_evaluation']['metric'],
            'value': (run.get('metrics') or {}).get(config['study_evaluation']['metric']),
        })
    return [{**entry, 'runs': entry['runs'][-3:]} for entry in list(candidates.values())[-8:]]


def completed_job_summary(job):
    result = job.get('result') or {}
    return {
        'job_id': job['job_id'], 'kind': job['kind'], 'status': job['status'],
        'name': job.get('payload', {}).get('name'),
        **metric_summary(result.get('metrics')), 'error': result.get('error'),
        'duration_seconds': result.get('duration_seconds'),
        'artifact_directory': result.get('artifact_directory'), 'log_path': result.get('log_path'),
    }


def headline_metrics(metrics, limit=8):
    """Aggregate scalars for run lists; per-replicate values and tables stay in get_job."""
    scalars = {key: value for key, value in (metrics or {}).items()
               if isinstance(value, (int, float)) and not isinstance(value, bool) and 'by_replicate' not in key}
    return {'metrics': dict(list(scalars.items())[:limit]),
            **({'metrics_truncated': True} if len(scalars) > limit or len(scalars) < len(metrics or {}) else {})}


def metric_summary(metrics):
    if len(json.dumps(metrics, ensure_ascii=False, default=str)) <= 4000:
        return {'metrics': metrics}
    # Nested case/trajectory tables belong in get_job/artifacts, not every wakeup.
    scalars = {key: value for key, value in metrics.items()
               if isinstance(value, (int, float, bool))}
    return {'metrics': dict(list(scalars.items())[:16]), 'metrics_truncated': True,
            'metric_sections': list(metrics)[:64],
            'metrics_instruction': 'Read get_job or the output metrics file for full measured results.'}
