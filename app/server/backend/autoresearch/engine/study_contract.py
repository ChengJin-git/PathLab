"""Domain-independent research design and measured execution contracts."""

import hashlib
import json
import math
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .effort import MAX_EXPERIMENTS


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class StudyScale(Contract):
    dataset: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=200)
    train_units: int = Field(ge=0)
    evaluation_units: int = Field(ge=0)
    repeats: int = Field(ge=1)
    input_coverage: str = Field(min_length=1, max_length=2000)
    optimization: str = Field(min_length=1, max_length=2000)


class StudyStage(Contract):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal['exploration', 'validation', 'confirmation']
    max_experiments: int = Field(ge=1, le=MAX_EXPERIMENTS)
    max_job_seconds: int = Field(ge=1, le=259200)
    advance_when: str = Field(min_length=1, max_length=2000)
    stop_when: str = Field(min_length=1, max_length=2000)


class StudyEvaluation(Contract):
    metric: str = Field(min_length=1, max_length=200)
    direction: Literal['minimize', 'maximize']
    primary_contrast: str = Field(min_length=1, max_length=4000)
    success_rule: str = Field(min_length=1, max_length=4000)
    uncertainty: str = Field(min_length=1, max_length=4000)
    split_policy: str = Field(min_length=1, max_length=4000)
    # Smallest primary-metric improvement over the strongest closest baseline worth publishing.
    minimum_gain: float = Field(gt=0)
    # Smallest nonzero change one evaluation unit can make to the primary metric (for example
    # 1/32 for a rate over 32 negative slides). A bar below it cannot be measured.
    resolution: float = Field(gt=0)
    # Best value the metric can take (1 for AUROC/accuracy, 0 for an error rate); null when
    # unbounded. A closest baseline already near it leaves no room for minimum_gain.
    best_possible: float | None


class ExperimentDesign(Contract):
    candidate_id: str = Field(min_length=1, max_length=80)
    operation: Literal['draft', 'improve', 'debug', 'scale', 'replicate']
    parent_run_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def parent_required(self):
        if (self.operation == 'draft') != (self.parent_run_id is None):
            raise ValueError('Draft starts a candidate; improve/debug/scale/replicate require parent_run_id')
        return self


class StudyMeasurement(Contract):
    unit: str = Field(min_length=1, max_length=200)
    train_units: int = Field(ge=0)
    evaluation_units: int = Field(ge=0)
    replicate_ids: list[str] = Field(min_length=1, max_length=100)
    input_coverage: str = Field(min_length=1, max_length=2000)
    optimization: str = Field(min_length=1, max_length=2000)
    # Primary metric of each independent repeat when one job trains several seeds.
    primary_by_replicate: dict[str, float] = Field(default_factory=dict, max_length=100)

    @model_validator(mode='after')
    def distinct_replicates(self):
        self.replicate_ids = [item.strip() for item in self.replicate_ids]
        if any(not item.strip() for item in self.replicate_ids) or len(set(self.replicate_ids)) != len(self.replicate_ids):
            raise ValueError('replicate_ids must identify distinct nonempty independent training repeats')
        if self.primary_by_replicate and set(self.primary_by_replicate) != set(self.replicate_ids):
            raise ValueError('primary_by_replicate must give the primary metric for exactly the replicate_ids')
        if any(not math.isfinite(value) for value in self.primary_by_replicate.values()):
            raise ValueError('primary_by_replicate values must be finite')
        return self


EXPLORATION_RUNS_PER_DIRECTION = 3
FULL_SCALE = {'validation', 'confirmation'}
# Independent repeats per arm before a full-scale comparison can clear the bar.
MIN_REPEATS = 3
# Distinct candidates (tuned variants) a direction needs before it can be ruled out.
TUNING_CANDIDATES = 3
# Directions ruled out under one evaluation/data frame before the frame itself must be revisited.
REFRAME_AFTER = 3
# Relative distance from a published number within which a baseline counts as reproduced.
REPRODUCE_WITHIN = 0.05
# Room the closest baseline must leave below best_possible, in multiples of minimum_gain: a method
# has to remove a third of the remaining error even when it only just clears the bar.
HEADROOM_FACTOR = 3
# Most repeats per arm a frame may need before its seed noise alone rules out resolving the bar.
MAX_USEFUL_REPEATS = 10


def exploration_streaks(jobs):
    """Non-debug exploration submissions per direction since its last full-scale submission."""
    streaks = Counter()
    for job in jobs:
        config = (job.get('payload') or {}).get('config') or {}
        direction = config.get('study_direction')
        if job['kind'] != 'experiment' or not direction:
            continue
        if config.get('study_stage_kind') in FULL_SCALE:
            streaks[direction] = 0
        elif config.get('operation') != 'debug':
            streaks[direction] += 1
    return dict(streaks)


def closest_baseline_steps(protocol):
    """Required full-data steps that run the closest published method."""
    closest = {b['id'] for b in protocol['baselines'] if b['role'] == 'closest'}
    kinds = {s['id']: s['kind'] for s in protocol['stages']}
    return {s['id'] for s in protocol['steps'] if s['role'] == 'baseline'
            and s.get('baseline_id') in closest and kinds[s['stage_id']] in FULL_SCALE}


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def frame(protocol):
    """What a pitch is judged by; adding pitches does not change it."""
    return revision({'evaluation': protocol['evaluation'], 'data': protocol['data'],
                     'baselines': protocol['baselines']})


def replicate_values(runs, metric):
    """Primary metric per independent repeat; a seed measured twice counts once."""
    values = {}
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        measurement = config.get('study_measurement') or {}
        per_seed = measurement.get('primary_by_replicate') or {}
        if per_seed:
            values.update(per_seed)
            continue
        value = (run.get('metrics') or {}).get(metric)
        if not numeric(value):
            raise ValueError(f"Run {run['run_id']} has no numeric primary metric {metric}")
        ids = measurement.get('replicate_ids') or [run['run_id']]
        if len(ids) > 1:
            raise ValueError(f"Run {run['run_id']} trained {len(ids)} repeats; report primary_by_replicate in study-result.json")
        values[ids[0]] = float(value)
    return list(values.values())


def _summary(values):
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1) if len(values) > 1 else 0.0
    return mean, variance


def frame_capacity(protocol, runs_by_step):
    """Whether this frame can show minimum_gain at all, from the closest baseline's full-scale repeats.

    Two limits, both measured before any method is built: the room left between the baseline and
    the metric's best possible value, and the repeats per arm its seed spread needs for a
    minimum_gain difference to exceed twice its standard error. None until the baseline has
    MIN_REPEATS repeats.
    """
    evaluation = protocol['evaluation']
    metric, maximize = evaluation['metric'], evaluation['direction'] == 'maximize'
    gain = evaluation['minimum_gain']
    arms = [values for step in sorted(closest_baseline_steps(protocol))
            if len(values := replicate_values(runs_by_step.get(step, []), metric)) >= MIN_REPEATS]
    if not arms:
        return None
    mean, variance = (max if maximize else min)((_summary(values) for values in arms), key=lambda arm: arm[0])
    best = evaluation.get('best_possible')
    headroom = None if best is None else (best - mean if maximize else mean - best)
    # Two arms with the baseline's seed variance: 2 * sqrt(2 * variance / n) <= minimum_gain.
    repeats = max(MIN_REPEATS, math.ceil(8 * variance / gain ** 2))
    problems = []
    if headroom is not None and headroom < HEADROOM_FACTOR * gain:
        problems.append(f'the closest baseline reaches {mean:.4g}, leaving {headroom:.4g} to the best possible '
                        f'{best:.4g}; the frame needs at least {HEADROOM_FACTOR} x minimum_gain = {HEADROOM_FACTOR * gain:.4g}')
    if repeats > MAX_USEFUL_REPEATS:
        problems.append(f'seed spread (SD {math.sqrt(variance):.4g}) needs {repeats} repeats per arm to resolve '
                        f'minimum_gain {gain}, more than {MAX_USEFUL_REPEATS}')
    return {'baseline': mean, 'baseline_sd': math.sqrt(variance), 'headroom': headroom,
            'required_repeats': repeats, 'sufficient': not problems, 'problems': problems}


def publication_gain(protocol, runs_by_step):
    """Selected pitch against the strongest closest baseline, measured over independent repeats.

    The bar is met only when both arms have MIN_REPEATS repeats, the mean gain reaches
    minimum_gain and it exceeds twice its standard error, so seed noise cannot clear it.
    """
    evaluation = protocol['evaluation']
    metric, maximize = evaluation['metric'], evaluation['direction'] == 'maximize'
    kinds = {s['id']: s['kind'] for s in protocol['stages']}

    def best(steps):
        arms = []
        for step in steps:
            values = replicate_values(runs_by_step.get(step['id'], []), metric)
            if values:
                mean, variance = _summary(values)
                # An inference-only arm (nothing trained) has no seed variance to sample.
                needed = MIN_REPEATS if step['scale']['train_units'] else 1
                arms.append({'step': step['id'], 'mean': mean, 'variance': variance,
                             'repeats': len(values), 'needed': needed})
        if not arms:
            return None
        return (max if maximize else min)(arms, key=lambda arm: arm['mean'])

    baselines = closest_baseline_steps(protocol)
    baseline = best([s for s in protocol['steps'] if s['id'] in baselines])
    method = best([s for s in protocol['steps'] if s['role'] == 'method'
                   and kinds[s['stage_id']] in FULL_SCALE
                   and s.get('direction_id') == protocol['selected_direction']])
    if baseline is None or method is None:
        return None
    gain = method['mean'] - baseline['mean'] if maximize else baseline['mean'] - method['mean']
    error = math.sqrt(method['variance'] / method['repeats'] + baseline['variance'] / baseline['repeats'])
    missing = []
    if method['repeats'] < method['needed'] or baseline['repeats'] < baseline['needed']:
        missing.append(f'{MIN_REPEATS} independent repeats per trained arm '
                       f"(method {method['repeats']}, baseline {baseline['repeats']})")
    if gain < evaluation['minimum_gain']:
        missing.append(f"gain {gain:.4f} below minimum_gain {evaluation['minimum_gain']}")
    if gain <= 2 * error:
        missing.append(f'gain {gain:.4f} within seed noise (2 x standard error = {2 * error:.4f})')
    return {'metric': metric, 'method_step': method['step'], 'method': method['mean'],
            'method_repeats': method['repeats'], 'baseline_step': baseline['step'],
            'baseline': baseline['mean'], 'baseline_repeats': baseline['repeats'], 'gain': gain,
            'standard_error': error, 'minimum_gain': evaluation['minimum_gain'],
            'bar_met': not missing, 'missing': missing}


def baseline_reproduction(protocol, runs):
    """Whether the pipeline reproduces a published result of each closest baseline.

    runs: completed experiments as {'config': study config, 'metrics': {...}}. Any step running
    the baseline counts, so a study on new data can verify its pipeline on the public benchmark
    the number comes from. Each candidate (setup) is averaged separately: fixing a broken setup
    is the point. A pipeline that cannot reproduce known results cannot verify a new one.
    """
    steps = {s['id']: s.get('baseline_id') for s in protocol['steps'] if s.get('baseline_id')}
    result = []
    for baseline in protocol['baselines']:
        reference = baseline.get('reference')
        if baseline['role'] != 'closest' or not reference:
            continue
        setups = {}
        for run in runs:
            value = (run.get('metrics') or {}).get(reference['metric'])
            if steps.get(run['config'].get('study_step')) == baseline['id'] and numeric(value):
                setups.setdefault(run['config'].get('candidate_id'), []).append(float(value))
        maximize = reference['direction'] == 'maximize'
        means = [sum(values) / len(values) for values in setups.values()]
        measured = (max if maximize else min)(means) if means else None
        slack = REPRODUCE_WITHIN * abs(reference['value'])
        target = reference['value'] - slack if maximize else reference['value'] + slack
        reproduced = measured is not None and (measured >= target if maximize else measured <= target)
        result.append({'baseline_id': baseline['id'], 'metric': reference['metric'],
                       'published': reference['value'], 'required': target, 'measured': measured,
                       'runs': sum(len(values) for values in setups.values()), 'reproduced': reproduced})
    return result


def stage_usage(jobs):
    # A failed/cancelled submission consumed an attempt too. Revisions do not reset it.
    return Counter(job['payload']['config']['study_stage'] for job in jobs
                   if job['kind'] == 'experiment' and (job.get('payload', {}).get('config') or {}).get('study_stage'))


def stage_budget(session, jobs):
    study = (session.recovery_metadata or {}).get('study')
    if not study:
        return None
    used = stage_usage(jobs)
    stages = [{
        'id': stage['id'], 'kind': stage['kind'],
        # Step scales are in the protocol itself; repeating them here doubled every wakeup.
        'step_ids': [step['id'] for step in study['protocol']['steps'] if step['stage_id'] == stage['id']],
        'attempt_limit': stage['max_experiments'], 'used': used[stage['id']],
        'remaining': max(0, stage['max_experiments'] - used[stage['id']]),
        'max_job_seconds': stage['max_job_seconds'],
    } for stage in study['protocol']['stages']]
    needed = sum(stage['remaining'] for stage in stages)
    available = max(0, session.max_iterations - session.current_iteration)
    return {'stages': stages, 'additional_experiments_needed': needed,
            'remaining_experiments': available, 'budget_sufficient': needed <= available}


def revision(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def measured_scale_progress(comparison, runs, replication_groups=()):
    """Count full-scale repeats within candidates or explicitly linked comparisons.

    A comparison fingerprint alone does not establish candidate equivalence. An
    append-only link binds actual runs and its rationale without rewriting lineage.
    Duplicate seeds/debug resumes count once; sample sizes are never added.
    """
    target = comparison['scale']
    candidates = {}
    eligible = {}
    for run in runs:
        config = run.get('config', {}).get('config') or {}
        measurement = config.get('study_measurement')
        if (run['status'] != 'completed' or not measurement
                or measurement['unit'] != target['unit']
                or measurement['train_units'] < target['train_units']
                or measurement['evaluation_units'] < target['evaluation_units']):
            continue
        key = (config['candidate_id'], config.get('study_step_revision'))
        candidates.setdefault(key, set()).update(measurement['replicate_ids'])
        if run.get('run_id'):
            eligible[run['run_id']] = run
    linked = {}
    for group in replication_groups:
        if comparison.get('id') and group['step_id'] != comparison['id']:
            continue
        # Every linked run must be selected, unchanged, complete and full-scale.
        if not all(identity in eligible and revision(eligible[identity]) == fingerprint
                   and eligible[identity]['config']['config'].get('study_step') == group['step_id']
                   and eligible[identity]['config']['config'].get('study_step_revision') == group['comparison_revision']
                   for identity, fingerprint in group['run_hashes'].items()):
            continue
        repeats = set()
        for identity in group['run_hashes']:
            repeats.update(eligible[identity]['config']['config']['study_measurement']['replicate_ids'])
        linked[group['id']] = repeats
    count = max((len(repeats) for repeats in [*candidates.values(), *linked.values()]), default=0)
    return {'complete': count >= target['repeats'], 'required_repeats': target['repeats'],
            'eligible_repeats': count, 'linked_group_ids': sorted(linked)}


def measured_scale_complete(comparison, runs, replication_groups=()):
    return measured_scale_progress(comparison, runs, replication_groups)['complete']
