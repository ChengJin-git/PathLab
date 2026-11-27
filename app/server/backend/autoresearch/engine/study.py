"""Evidence-backed study decisions; successful code execution is not a discovery.

The agent/reviewer judges scientific merit. The service verifies the declared plan,
executed comparisons and source files, so an unfinished pilot cannot silently become
a completed scientific study. Ordinary analysis and reproduction remain lightweight.
"""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import store
from .research_progress import decision_summary
from .study_contract import (
    EXPLORATION_RUNS_PER_DIRECTION,
    FULL_SCALE,
    MIN_REPEATS,
    REFRAME_AFTER,
    REPRODUCE_WITHIN,
    TUNING_CANDIDATES,
    ExperimentDesign,
    StudyEvaluation,
    StudyMeasurement,
    StudyScale,
    StudyStage,
    baseline_reproduction,
    exploration_streaks,
    frame,
    frame_capacity,
    measured_scale_complete,
    measured_scale_progress,
    numeric,
    publication_gain,
    revision,
    stage_budget,
    stage_usage,
)


class PublishedResult(BaseModel):
    """A number the baseline's authors or a benchmark reported on comparable data."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    metric: str = Field(min_length=1, max_length=200)
    value: float
    direction: Literal["minimize", "maximize"]
    dataset: str = Field(min_length=1, max_length=500)
    citation: str = Field(min_length=1, max_length=1000)


class Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    role: Literal["sanity", "closest"]
    source: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    # Required for at least one closest baseline: its full-data run must reproduce this number
    # before method runs count, so gains are never measured against a degraded pipeline.
    reference: PublishedResult | None = None


class StudyStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    role: Literal[
        "sanity", "baseline", "method", "ablation", "replication", "mechanism"
    ]
    question: str = Field(min_length=1, max_length=4000)
    stage_id: str = Field(min_length=1, max_length=80)
    scale: StudyScale
    direction_id: str | None = None
    baseline_id: str | None = None
    required: bool = True


class Premise(BaseModel):
    """The measured effect a pitch exploits; a method cannot recover more than the effect itself."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    # A mechanism step that measures the effect on the full data.
    step_id: str = Field(min_length=1, max_length=80)
    # metrics.json key of that step: the effect in primary-metric units (for example the AUROC
    # lost when uninformative slides are added).
    metric: str = Field(min_length=1, max_length=200)


class ResearchDirection(BaseModel):
    """A paper-level pitch. Mechanisms are later ablations of a method that already wins."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    claim: str = Field(min_length=1, max_length=2000)
    headline_result: str = Field(min_length=1, max_length=4000)
    closest_work: str = Field(min_length=1, max_length=4000)
    novelty_check: str = Field(min_length=1, max_length=4000)
    expected_gain: str = Field(min_length=1, max_length=4000)
    cost: str = Field(min_length=1, max_length=2000)
    # Required key: the phenomenon the pitch rests on, or null when it rests on none.
    premise: Premise | None


class DatasetSize(BaseModel):
    """Verified full size of a dataset; validation compares methods on all of it."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=200)
    train_units: int = Field(ge=1)
    evaluation_units: int = Field(ge=1)


class StudyProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)
    hypothesis: str = Field(min_length=1, max_length=4000)
    falsification: str = Field(min_length=1, max_length=4000)
    contribution: str = Field(min_length=1, max_length=4000)
    baselines: list[Baseline] = Field(min_length=1, max_length=20)
    evaluation: StudyEvaluation
    stages: list[StudyStage] = Field(min_length=1, max_length=6)
    steps: list[StudyStep] = Field(min_length=1, max_length=100)
    budget_rationale: str = Field(min_length=1, max_length=4000)
    evidence_files: list[str] = Field(min_length=1, max_length=24)
    directions: list[ResearchDirection] = Field(min_length=3, max_length=12)
    selected_direction: str = Field(min_length=1, max_length=80)
    selection_reason: str = Field(min_length=1, max_length=4000)
    evaluation_files: list[str] = Field(min_length=1, max_length=12)
    data: list[DatasetSize] = Field(min_length=1, max_length=12)


class StudyReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["iterate", "pivot", "write", "blocked"]
    rationale: str = Field(min_length=1, max_length=8000)
    goal_met: bool
    conclusion: str = Field(min_length=1, max_length=8000)
    unresolved: list[str] = Field(max_length=30)
    completed_steps: dict[str, list[str]]
    evidence_files: list[str] = Field(min_length=1, max_length=24)
    figure_paths: list[str] = Field(default_factory=list, max_length=12)
    reviewer: str = Field(min_length=1, max_length=500)


class ResearchDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    direction_id: str = Field(min_length=1, max_length=80)
    action: Literal['keep', 'discard', 'repair', 'pivot']
    assessment: Literal['supported', 'contradicted', 'inconclusive', 'invalid']
    scope: Literal['candidate', 'direction']
    next_operation: Literal['draft', 'improve', 'debug', 'scale', 'replicate', 'analyze', 'finish']
    run_ids: list[str] = Field(min_length=1, max_length=100)
    observation: str = Field(min_length=1, max_length=8000)
    interpretation: str = Field(min_length=1, max_length=8000)
    next_action: str = Field(min_length=1, max_length=4000)
    evidence_files: list[str] = Field(min_length=1, max_length=24)


class ReplicationGroup(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=80)
    step_id: str = Field(min_length=1, max_length=80)
    run_ids: list[str] = Field(min_length=2, max_length=100)
    rationale: str = Field(min_length=1, max_length=8000)
    evidence_files: list[str] = Field(min_length=1, max_length=24)


def scientific(session) -> bool:
    return (session.recovery_metadata or {}).get("research_standard") == "scientific"


def evidence_path(root: Path, relative: str, limit: int) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Study evidence must be a workspace-relative file")
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Study evidence is missing or too large: {relative}")
    return path


def read_evidence(root: Path, relative: str, limit=100000) -> str:
    return evidence_path(root, relative, limit).read_text(encoding="utf-8")


def evidence_files(root, paths):
    result = {}
    for path in paths:
        result[path] = read_evidence(root, path)
    if sum(len(value) for value in result.values()) > 180000:
        raise ValueError(
            "Study evidence exceeds 180,000 characters; select focused protocol/results sources"
        )
    return result


def source_hashes(files):
    return {name: revision(value) for name, value in files.items()}


def figure_hashes(root, paths):
    result = {}
    for relative in paths:
        target = evidence_path(root, relative, 20_000_000)
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Review figure must be an existing workspace image")
        result[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result


def current_protocol(session):
    meta = session.recovery_metadata or {}
    study = meta.get("study") or {}
    if not study.get("protocol"):
        raise ValueError("Record a scientific study protocol before training or review")
    if study["goal"] != meta.get("current_goal"):
        raise ValueError("The research goal changed; record an updated study protocol")
    root = Path(session.workspace_path)
    current = StudyProtocol.model_validate_json(
        read_evidence(root, study["protocol_path"])
    )
    if current.model_dump() != study["protocol"]:
        raise ValueError("Protocol changed; record an updated study protocol")
    files = evidence_files(
        Path(session.workspace_path), study["protocol"]["evidence_files"] + study['protocol']['evaluation_files']
    )
    if source_hashes(files) != study["source_hashes"]:
        raise ValueError("Protocol sources changed; record an updated study protocol")
    return study, files


async def save_study(session, record, event):
    meta = session.recovery_metadata or {}
    await store.update(
        session.session_id,
        meta={"study": record},
        event=event,
        expected_metadata={
            key: meta.get(key)
            for key in ["current_goal", "research_standard", "study", "commands", "research_decisions", "replication_groups"]
        },
        expected_iteration=session.current_iteration,
    )


async def record_protocol(session, path):
    if not scientific(session) or not (session.recovery_metadata or {}).get(
        "current_goal"
    ):
        raise ValueError("Set the scientific research scope and current goal first")
    root = Path(session.workspace_path)
    protocol = StudyProtocol.model_validate_json(read_evidence(root, path))
    ids = [step.id for step in protocol.steps]
    baselines = {baseline.id: baseline for baseline in protocol.baselines}
    if len(ids) != len(set(ids)) or len(baselines) != len(protocol.baselines):
        raise ValueError("Study step and baseline IDs must be unique")
    if any(
        step.baseline_id and step.baseline_id not in baselines
        for step in protocol.steps
    ):
        raise ValueError("Unknown baseline_id in study step")
    if not any(
        step.required and step.role in {"method", "mechanism"}
        for step in protocol.steps
    ):
        raise ValueError(
            "Include a required method or mechanism test of the scientific hypothesis"
        )
    directions = {direction.id for direction in protocol.directions}
    if len(directions) != len(protocol.directions) or protocol.selected_direction not in directions:
        raise ValueError('Select one uniquely identified research direction from the candidate portfolio')
    roles = {step.id: step.role for step in protocol.steps}
    for direction in protocol.directions:
        if direction.premise and roles.get(direction.premise.step_id) != 'mechanism':
            raise ValueError(f'Direction {direction.id} premise must name a mechanism step that measures the effect')
    stages = {stage.id: stage for stage in protocol.stages}
    if len(stages) != len(protocol.stages):
        raise ValueError('Stage IDs must be unique')
    order = {'exploration': 0, 'validation': 1, 'confirmation': 2}
    if [order[s.kind] for s in protocol.stages] != sorted(order[s.kind] for s in protocol.stages):
        raise ValueError('Order stages as exploration, validation, confirmation')
    for step in protocol.steps:
        if step.stage_id not in stages or (step.direction_id and step.direction_id not in directions):
            raise ValueError('Study steps must reference declared stages and directions')
        if stages[step.stage_id].kind != 'exploration' and not step.scale.evaluation_units:
            raise ValueError('Validation and confirmation comparisons require independent evaluation units')
        if step.role not in {'baseline', 'sanity'} and not step.direction_id:
            raise ValueError('Method, mechanism, ablation and replication steps need direction_id')
    if set(stages) != {step.stage_id for step in protocol.steps}:
        raise ValueError('Every stage needs an executable study step')
    if not any(step.required and step.role in {'method', 'mechanism'}
               and stages[step.stage_id].kind in {'validation', 'confirmation'} for step in protocol.steps):
        raise ValueError('Include an adequate-scale validation or confirmation step for the primary question')
    sizes = {item.name: item for item in protocol.data}
    if len(sizes) != len(protocol.data):
        raise ValueError('Dataset names in data must be unique')
    for step in protocol.steps:
        size, scale, kind = sizes.get(step.scale.dataset), step.scale, stages[step.stage_id].kind
        if size is None or size.unit != scale.unit:
            raise ValueError(f'Step {step.id} must use a dataset declared in data, with its unit')
        if kind == 'validation' and (scale.train_units not in {0, size.train_units}
                                     or scale.evaluation_units != size.evaluation_units):
            raise ValueError(f'Validation step {step.id} must use the full {size.name} data '
                             f'({size.train_units} train / {size.evaluation_units} evaluation {size.unit}); '
                             'subsets belong to exploration smoke tests')
        if kind == 'confirmation' and scale.evaluation_units != size.evaluation_units:
            raise ValueError(f'Confirmation step {step.id} must evaluate all {size.evaluation_units} {size.unit} of {size.name}')
    if not any(step.required and step.role == 'baseline' and step.baseline_id in baselines
               and baselines[step.baseline_id].role == 'closest' and stages[step.stage_id].kind == 'validation'
               for step in protocol.steps):
        raise ValueError('Run the closest published method on the full data: add a required validation-stage baseline step')
    evaluation = protocol.evaluation
    if evaluation.minimum_gain < evaluation.resolution:
        raise ValueError(
            f'minimum_gain {evaluation.minimum_gain} is below the metric resolution {evaluation.resolution}: '
            'one evaluation unit already moves the metric more than the bar, so the comparison cannot be measured. '
            'Evaluate on more units (for example cross-validation over all labelled cases) or use a finer metric.')
    if not any(b.role == 'closest' and b.reference for b in protocol.baselines):
        raise ValueError('Give at least one closest baseline a published reference result (metric, value, dataset, citation). '
                         'Method runs count only after a step running that baseline reproduces it; for new data, add a '
                         'step on the public benchmark the number comes from.')
    closest = {b.id for b in protocol.baselines if b.role == 'closest'}
    for step in protocol.steps:
        compared = step.role == 'method' or (step.role == 'baseline' and step.baseline_id in closest)
        trained = step.scale.train_units > 0
        if compared and trained and stages[step.stage_id].kind == 'validation' and step.scale.repeats < MIN_REPEATS:
            raise ValueError(f'Validation step {step.id} needs at least {MIN_REPEATS} independent repeats: one seed cannot '
                             'separate a method from seed noise. One job may train several seeds (report primary_by_replicate).')
    previous_stages = {s['id']: s['kind'] for s in (session.recovery_metadata.get('study') or {}).get('protocol', {}).get('stages', [])}
    if any(stage.id in previous_stages and previous_stages[stage.id] != stage.kind for stage in protocol.stages):
        raise ValueError('Stage kind is immutable; use a new ID for a different stage')
    previous = (session.recovery_metadata.get('study') or {})
    ruled_out = contradicted_directions(session.recovery_metadata)
    dumped = protocol.model_dump()
    same_frame = previous.get('frame') == frame(dumped)
    frame_start = previous.get('frame_ruled_out', []) if same_frame else sorted(ruled_out)
    failed_in_frame = ruled_out - set(frame_start)
    added = directions - {d['id'] for d in previous.get('protocol', {}).get('directions', [])}
    if same_frame and added and len(failed_in_frame) >= REFRAME_AFTER:
        raise ValueError(
            f'{len(failed_in_frame)} pitches were ruled out under this evaluation, data and baselines. Before adding '
            'pitches, revisit the frame: does the closest baseline reproduce its published number, does the metric resolve '
            'minimum_gain above seed noise, does the baseline leave room for it, do the inputs keep the signal the task '
            "needs? Change evaluation, data or baselines within the user's question (PathTrove, Data Repo) and continue.")
    exhausted = list(previous.get('exhausted_frames', []))
    if previous and not same_frame and len(ruled_out - set(previous.get('frame_ruled_out', []))) >= REFRAME_AFTER:
        exhausted.append(previous['frame'])
    files = evidence_files(root, protocol.evidence_files + protocol.evaluation_files)
    record = {
        "protocol": dumped,
        "protocol_path": path,
        "goal": session.recovery_metadata["current_goal"],
        "source_hashes": source_hashes(files),
        "frame": frame(dumped),
        "frame_ruled_out": frame_start,
        "exhausted_frames": exhausted,
    }
    record.update(revision=revision(record), review=None)
    # Step fingerprints permit deliberate reuse of an unchanged comparison after
    # adding another hypothesis/ablation. Evaluation or step changes invalidate it.
    evaluation = source_hashes({name: files[name] for name in protocol.evaluation_files})
    record['step_revisions'] = {step.id: revision({
        'evaluation': protocol.evaluation.model_dump(),
        'evaluation_files': evaluation, 'step': step.model_dump(),
        'stage_kind': stages[step.stage_id].kind,
        'baseline': baselines[step.baseline_id].model_dump() if step.baseline_id else None,
        'direction': next(d.model_dump() for d in protocol.directions if d.id == step.direction_id)
                     if step.direction_id else None,
    }) for step in protocol.steps}
    await save_study(
        session,
        record,
        {"kind": "study", "decision": "plan", "question": protocol.question},
    )
    budget = stage_budget(SimpleNamespace(recovery_metadata={'study': record},
        max_iterations=session.max_iterations, current_iteration=session.current_iteration),
        await store.jobs(session.session_id))
    return {
        "revision": record["revision"],
        **budget,
        "instruction": "Smoke-test the selected pitch briefly. Run the closest baseline on the full data first and check it reproduces its published number, then run the pitch with independent repeats. Tune and improve until the measured gain clears minimum_gain above seed noise, or pivot. If the plan needs more time or attempts, request the extension now with request_help(reason='budget').",
    }


def experiment_config(session, config):
    if not scientific(session):
        return config
    study, _ = current_protocol(session)
    if config.get("study_revision") and config["study_revision"] != study["revision"]:
        raise ValueError(
            "Study protocol changed during submission; resubmit against the current protocol"
        )
    step = next(
        (
            step
            for step in study["protocol"]["steps"]
            if step["id"] == config.get("study_step")
        ),
        None,
    )
    if step is None:
        raise ValueError(
            "Scientific experiments require config.study_step from the recorded protocol"
        )
    design = ExperimentDesign.model_validate({key: config[key] for key in
        ('candidate_id', 'operation', 'parent_run_id') if key in config})
    stage = next(s for s in study['protocol']['stages'] if s['id'] == step['stage_id'])
    return {**{k: v for k, v in config.items() if not k.startswith('study_')},
            **design.model_dump(), 'study_step': step['id'],
            "study_revision": study["revision"], "study_role": step["role"],
             'study_step_revision': study['step_revisions'][step['id']],
            'study_direction': step['direction_id'], 'study_stage': stage['id'],
             'study_stage_kind': stage['kind'], 'study_scale': step['scale'],
            'study_evaluation': study['protocol']['evaluation']}


def validate_submission(session, payload, jobs):
    """Called under the session lock so parallel submissions share reservations."""
    if not scientific(session):
        return
    config = payload['config']
    stages = session.recovery_metadata['study']['protocol']['stages']
    stage = next(s for s in stages if s['id'] == config['study_stage'])
    used = stage_usage(jobs)
    if used[stage['id']] >= stage['max_experiments']:
        raise ValueError('Stage attempt allocation reached; assess results and advance or explicitly revise the plan within the authorized budget')
    # Protect planned later validation/confirmation attempts, including queued work.
    position = stages.index(stage)
    reserved = sum(max(0, s['max_experiments'] - used[s['id']]) for s in stages[position+1:]
                   if s['kind'] in {'validation', 'confirmation'})
    if session.max_iterations - session.current_iteration - 1 < reserved:
        raise ValueError('This submission would consume reserved validation/confirmation attempts; advance, reallocate the plan or request the measured shortfall')
    if payload['timeout'] > stage['max_job_seconds']:
        raise ValueError('Job timeout exceeds the stage allocation; profile and revise its resource plan before submission')
    by_id = {job['job_id']: job for job in jobs if job['kind'] == 'experiment'}
    design = ExperimentDesign.model_validate({key: config[key] for key in ('candidate_id', 'operation', 'parent_run_id')})
    parent = by_id.get(design.parent_run_id)
    if design.parent_run_id:
        expected = {'failed', 'cancelled'} if design.operation == 'debug' else {'completed'}
        if not parent or parent['status'] not in expected:
            raise ValueError('Parent must be a settled experiment from this session: failed/cancelled for debug, completed for improve/scale/replicate')
        pc = parent['payload']['config']
        same = pc.get('candidate_id') == design.candidate_id
        if (design.operation == 'improve') == same:
            raise ValueError('Improve creates a new candidate; debug/scale/replicate retain the parent candidate_id')
        if design.operation != 'improve' and pc.get('study_direction') != config['study_direction']:
            raise ValueError('Debug/scale/replicate retain the parent direction; improve forks a new candidate')
        if design.operation == 'replicate' and pc.get('study_step_revision') != config['study_step_revision']:
            raise ValueError('Replication requires the same comparison and scale as its parent')
    if design.operation in {'draft', 'improve'} and any(
            job['payload'].get('config', {}).get('candidate_id') == design.candidate_id for job in by_id.values()):
        raise ValueError('A new candidate_id must be unique within the session')
    direction = config.get('study_direction')
    if (stage['kind'] == 'exploration' and direction and design.operation != 'debug'
            and exploration_streaks(jobs).get(direction, 0) >= EXPLORATION_RUNS_PER_DIRECTION):
        raise ValueError(f'Direction {direction} already has {EXPLORATION_RUNS_PER_DIRECTION} exploration runs since its last '
                         'full-scale run. Subsets cannot decide whether a pitch works: submit its validation step on the full data, or pivot.')
    if stage['kind'] in FULL_SCALE and config.get('study_role') in {'method', 'ablation', 'mechanism', 'replication'}:
        protocol = session.recovery_metadata['study']['protocol']
        completed = [{'config': job['payload'].get('config') or {}, 'metrics': (job.get('result') or {}).get('metrics') or {}}
                     for job in by_id.values() if job['status'] == 'completed']
        checks = baseline_reproduction(protocol, completed)
        if not any(check['reproduced'] for check in checks):
            measured = '; '.join(f"{c['baseline_id']}: {c['metric']} {c['measured'] if c['measured'] is not None else 'not run'} "
                                 f"vs published {c['published']} (needs {c['required']:.4g})" for c in checks)
            raise ValueError(
                f'The pipeline has not reproduced the closest baseline\'s published result ({measured}). A pipeline more than '
                f'{REPRODUCE_WITHIN:.0%} off a known result cannot verify a new one. Find why first: degraded or reduced '
                'inputs, missing features, untuned training, a different split or metric. Fix it and rerun the baseline, '
                'on the reference\'s own benchmark if the study data are new.')
        if config.get('study_role') != 'mechanism':
            check_frame_capacity(session.recovery_metadata['study'], by_id.values(), config)


def completed_runs_by_step(study, jobs):
    """Completed runs of the current protocol revision, keyed by step, in the shape publication_gain reads."""
    runs = {}
    for job in jobs:
        config = job['payload'].get('config') or {}
        step = config.get('study_step')
        if (job['kind'] == 'experiment' and job['status'] == 'completed'
                and config.get('study_step_revision') == study.get('step_revisions', {}).get(step)):
            runs.setdefault(step, []).append({'run_id': job['job_id'], 'config': job['payload'],
                                              'metrics': (job.get('result') or {}).get('metrics') or {}})
    return runs


def check_frame_capacity(study, jobs, config):
    """Before a method is built: can this frame show minimum_gain, and is the pitch's premise big enough?"""
    protocol = study['protocol']
    runs = completed_runs_by_step(study, jobs)
    capacity = frame_capacity(protocol, runs)
    if capacity and not capacity['sufficient']:
        raise ValueError(
            'This frame cannot show minimum_gain: ' + '; '.join(capacity['problems']) + '. No method can clear the bar '
            'here. Change the frame within the user\'s question: a harder endpoint, larger or different data '
            '(PathTrove, Data Repo), or a different evaluation; record the new protocol, reproduce its baseline and '
            'check again.')
    step = next(s for s in protocol['steps'] if s['id'] == config['study_step'])
    if capacity and step['scale']['repeats'] < capacity['required_repeats']:
        raise ValueError(f"Seed spread of the closest baseline needs {capacity['required_repeats']} repeats per arm to "
                         f"resolve minimum_gain; step {step['id']} plans {step['scale']['repeats']}. Raise repeats for "
                         'this step and the closest baseline in the protocol.')
    direction = next((d for d in protocol['directions'] if d['id'] == config.get('study_direction')), None)
    premise = (direction or {}).get('premise')
    if not premise:
        return
    values = [run['metrics'][premise['metric']] for run in runs.get(premise['step_id'], [])
              if numeric(run['metrics'].get(premise['metric']))]
    if not values:
        raise ValueError(f"Direction {direction['id']} rests on the effect measured by step {premise['step_id']} "
                         f"({premise['metric']}). Measure it on the full data before building the method.")
    effect = abs(sum(values) / len(values))
    gain = protocol['evaluation']['minimum_gain']
    if effect < gain:
        raise ValueError(f"The effect direction {direction['id']} exploits measures {effect:.4g} "
                         f"({premise['metric']}), below minimum_gain {gain}: removing it entirely cannot clear the bar. "
                         'Record the direction as contradicted with this measurement and move to a pitch or frame '
                         'where the effect is large enough.')


def exhausted_frame_count(meta) -> int:
    """Frames given up after REFRAME_AFTER ruled-out pitches, the current one included."""
    study = (meta or {}).get('study') or {}
    if not study:
        return 0
    current = contradicted_directions(meta) - set(study.get('frame_ruled_out', []))
    return len(study.get('exhausted_frames', [])) + (len(current) >= REFRAME_AFTER)


def read_measurement(output, config, metrics):
    measurement = StudyMeasurement.model_validate_json(read_evidence(output, 'study-result.json'))
    if measurement.unit != config['study_scale']['unit']:
        raise ValueError('Measured unit must match the study stage')
    if config['study_stage_kind'] != 'exploration' and not metrics:
        raise ValueError('Validation experiments must emit measured finite numeric metrics')
    if (config['study_stage_kind'] != 'exploration' and config.get('study_role') != 'sanity'
            and config['study_evaluation']['metric'] not in metrics):
        raise ValueError('Scientific experiment must emit its declared primary metric in metrics.json')
    return measurement.model_dump()


async def record_decision(session, path):
    root = Path(session.workspace_path)
    decision = ResearchDecision.model_validate_json(read_evidence(root, path))
    # A steering instruction may change the goal before the previous route's
    # results are assessed. Bind its decision to those frozen runs, not a new plan.
    runs = {run['run_id']: run for run in await store.experiments(session.session_id)}
    selected = []
    for identity in decision.run_ids:
        run = runs.get(identity)
        if not run or run['status'] not in {'completed', 'failed', 'cancelled'}:
            raise ValueError('Research decisions need actual settled experiments from this session')
        config = run.get('config', {}).get('config', {})
        if config.get('study_direction') and config['study_direction'] != decision.direction_id:
            raise ValueError('Decision runs must belong to the selected direction')
        selected.append(run)
    meta = session.recovery_metadata or {}
    declared = {d['id'] for d in (meta.get('study') or {}).get('protocol', {}).get('directions', [])}
    declared.update((run.get('config', {}).get('config') or {}).get('study_direction') for run in selected)
    if scientific(session) and decision.direction_id not in declared:
        raise ValueError('Decision direction must be declared by the protocol or its frozen runs')
    if decision.assessment != 'invalid' and not any(run['status'] == 'completed' for run in selected):
        raise ValueError('Failed execution is invalid evidence, not a negative scientific result')
    if decision.assessment == 'inconclusive' and decision.scope == 'direction' and decision.action == 'discard':
        raise ValueError('Inconclusive evidence cannot discard an entire direction; scale, replicate, diagnose or defer it with a pivot')
    if decision.scope == 'direction' and decision.assessment in {'supported', 'contradicted'}:
        by_step = {}
        for run in selected:
            c = run.get('config', {}).get('config') or {}
            if c.get('study_stage_kind') in {'validation', 'confirmation'} and c.get('study_direction') == decision.direction_id:
                by_step.setdefault(c['study_step_revision'], []).append(run)
        groups = meta.get('replication_groups', [])
        progress = [measured_scale_progress({'scale': group[0]['config']['config']['study_scale']}, group, groups)
                    for group in by_step.values()]
        complete = next((item for item in progress if item['complete']), None)
        if complete is None:
            raise ValueError('Direction-level conclusions need measured target-scale evidence; assess the candidate or record inconclusive')
        if decision.assessment == 'contradicted':
            candidates = {(run.get('config', {}).get('config') or {}).get('candidate_id') for run in runs.values()
                          if run['status'] == 'completed'
                          and (run.get('config', {}).get('config') or {}).get('study_direction') == decision.direction_id}
            candidates.discard(None)
            if len(candidates) < TUNING_CANDIDATES:
                raise ValueError(
                    f'Direction {decision.direction_id} has {len(candidates)} tried candidate(s); ruling it out needs at least '
                    f'{TUNING_CANDIDATES}. Tuning hyperparameters, loss weights and architecture on the development data is '
                    'normal method development, not selection bias; only the held-out test is locked. Improve the method, then decide.')
        replication_sources(root, [g for g in groups if g['id'] in complete['linked_group_ids']])
    files = evidence_files(root, decision.evidence_files)
    record = {**decision.model_dump(), 'source_hashes': source_hashes(files),
              'run_hashes': {run['run_id']: revision(run) for run in selected},
              'run_protocol_revisions': sorted({run['config']['config']['study_revision'] for run in selected
                                               if (run.get('config', {}).get('config') or {}).get('study_revision')})}
    decisions = meta.get('research_decisions', [])
    existing = next((item for item in decisions if item['id'] == decision.id), None)
    if existing:
        if existing != record:
            raise ValueError('Decision IDs are immutable; record a new decision for new evidence')
        return {'recorded': True, 'decision': decision_summary(existing)}
    update = {'research_decisions': [*decisions, record],
              'assessed_runs': {**meta.get('assessed_runs', {}), **record['run_hashes']}}
    if meta.get('study'):
        update['study'] = {**meta['study'], 'review': None}
    await store.update(session.session_id, meta=update,
        expected_metadata={key: meta.get(key) for key in ['study', 'commands', 'research_decisions', 'current_goal', 'research_standard', 'replication_groups']},
        event={'kind': 'research_decision', 'decision': record})
    return {'recorded': True, 'decision': decision_summary(record),
            'instruction': 'Execute the recorded next action within the live budget; this decision is not a request for routine approval.'}


async def record_replication_group(session, path):
    """Link independently named repeats; never change a completed run's lineage."""
    root = Path(session.workspace_path)
    link = ReplicationGroup.model_validate_json(read_evidence(root, path))
    if len(set(link.run_ids)) != len(link.run_ids):
        raise ValueError('Replication group run IDs must be distinct')
    study, _ = current_protocol(session)
    step = next((s for s in study['protocol']['steps'] if s['id'] == link.step_id), None)
    if step is None:
        raise ValueError('Replication group must reference a current study step')
    runs = {r['run_id']: r for r in await store.experiments(session.session_id)}
    selected = []
    for identity in link.run_ids:
        run = runs.get(identity)
        config = (run or {}).get('config', {}).get('config', {})
        if (not run or run['status'] != 'completed' or config.get('study_step') != step['id']
                or config.get('study_step_revision') != study['step_revisions'][step['id']]):
            raise ValueError('Link only completed runs from this session and the same current comparison fingerprint')
        single = {**step, 'scale': {**step['scale'], 'repeats': 1}}
        if not measured_scale_complete(single, [run]):
            raise ValueError('Every linked run must meet the full per-run sample target; do not sum sample counts')
        selected.append(run)
    files = evidence_files(root, link.evidence_files)
    record = {**link.model_dump(), 'comparison_revision': study['step_revisions'][step['id']],
              'run_hashes': {r['run_id']: revision(r) for r in selected}, 'source_hashes': source_hashes(files)}
    meta = session.recovery_metadata or {}
    groups = meta.get('replication_groups', [])
    existing = next((g for g in groups if g['id'] == link.id), None)
    if existing and existing != record:
        raise ValueError('Replication group IDs are immutable; append a new link for new evidence')
    if not existing:
        await store.update(session.session_id,
            meta={'replication_groups': [*groups, record], 'study': {**study, 'review': None}},
            expected_metadata={k: meta.get(k) for k in ['study', 'replication_groups', 'commands', 'current_goal', 'research_standard']},
            expected_iteration=session.current_iteration,
            event={'kind': 'study', 'decision': 'link_repeats', 'step_id': link.step_id, 'group_id': link.id, 'run_ids': link.run_ids})
    return {'recorded': True, 'group_id': link.id, **measured_scale_progress(step, selected, [record])}


def replication_sources(root, groups):
    files = {}
    for group in groups:
        sources = evidence_files(root, group['evidence_files'])
        if source_hashes(sources) != group['source_hashes']:
            raise ValueError('Replication link evidence changed; append an updated link before review')
        files.update(sources)
    return files


async def record_review(session, path):
    root = Path(session.workspace_path)
    review = StudyReview.model_validate_json(read_evidence(root, path))
    study, _ = current_protocol(session)
    files = evidence_files(root, review.evidence_files)
    runs = {run["run_id"]: run for run in await store.experiments(session.session_id)}
    used = {}
    linked_ids = set()
    groups = (session.recovery_metadata or {}).get('replication_groups', [])
    for step_id, run_ids in review.completed_steps.items():
        if step_id not in {step["id"] for step in study["protocol"]["steps"]}:
            raise ValueError("Review references an unknown study step")
        for run_id in run_ids:
            run = runs.get(run_id)
            config = (run or {}).get("config", {}).get("config", {})
            if (
                not run
                or run["status"] != "completed"
                or config.get("study_step") != step_id
                or config.get('study_step_revision') != study['step_revisions'][step_id]
            ):
                raise ValueError(
                    "Review evidence must reference completed runs from this protocol and step"
                )
            used[run_id] = run
    gain = publication_gain(study['protocol'], {
        step_id: [used[run_id] for run_id in run_ids] for step_id, run_ids in review.completed_steps.items()})
    if review.decision == "write":
        if not gain or not gain['bar_met']:
            measured = f"{gain['gain']:.4f}" if gain else 'not measured'
            raise ValueError(
                f"Not publishable yet: full-scale gain of the selected pitch over the strongest closest baseline is {measured}; "
                f"the protocol bar is minimum_gain={study['protocol']['evaluation']['minimum_gain']}. "
                'Improve the method or pivot to the next pitch; record iterate or pivot.')
        missing = [
            step["id"]
            for step in study["protocol"]["steps"]
            if step["required"] and not review.completed_steps.get(step["id"])
        ]
        if not review.goal_met or review.unresolved or missing:
            raise ValueError(
                "Study is not ready to write: resolve claim-critical gaps or record iterate/pivot/blocked"
            )
        for step in study['protocol']['steps']:
            if not step['required']:
                continue
            progress = measured_scale_progress(step, [runs[r] for r in review.completed_steps[step['id']]], groups)
            if not progress['complete']:
                raise ValueError(f'Required comparisons need measured sample size and independent repeats at their planned scale: '
                                 f'{step["id"]} has {progress["eligible_repeats"]}/{progress["required_repeats"]} eligible repeats. '
                                 'For equivalent repeats with different candidate IDs, record_replication_group with matching-method evidence; do not retrain or rewrite runs.')
            linked_ids.update(progress['linked_group_ids'])
        decided = {identity for identity, fingerprint in (session.recovery_metadata or {}).get('assessed_runs', {}).items()
                    if identity in used and revision(used[identity]) == fingerprint}
        if any(identity not in decided for identity in used):
            raise ValueError('Record measured research decisions for the selected runs before final review')
    linked = [g for g in groups if g['id'] in linked_ids]
    replication_sources(root, linked)
    record = {
        **review.model_dump(),
        'replication_groups': linked,
        "protocol_revision": study["revision"],
        "runs_hash": revision(list(used.values())),
        "source_hashes": source_hashes(files),
        "figure_hashes": figure_hashes(root, review.figure_paths),
        "run_ids": list(used),
        "publication_gain": gain,
    }
    await save_study(
        session,
        {**study, "review": record},
        {"kind": "study", "decision": review.decision, "conclusion": review.conclusion},
    )
    return {
        "recorded": True,
        "decision": review.decision,
        "ready_to_write": review.decision == "write",
        "publication_gain": gain,
    }


def contradicted_directions(meta) -> set[str]:
    return {d['direction_id'] for d in (meta or {}).get('research_decisions', [])
            if d['scope'] == 'direction' and d['assessment'] == 'contradicted'}


def untested_pitches(session) -> list[str]:
    """Pitches without a full-scale contradiction."""
    meta = session.recovery_metadata or {}
    protocol = (meta.get('study') or {}).get('protocol')
    if not protocol:
        return ['(no study protocol recorded)']
    closed = contradicted_directions(meta)
    return [d['id'] for d in protocol['directions'] if d['id'] not in closed]


async def writing_evidence(session):
    if not scientific(session):
        return None
    study, protocol_files = current_protocol(session)
    review = study.get("review") or {}
    if review.get("decision") != "write" or review.get(
        "protocol_revision"
    ) != study.get("revision"):
        raise ValueError(
            "Scientific study requires a current write decision backed by executed comparisons. Continue research or record a blocker instead of drafting a final paper."
        )
    runs = {run["run_id"]: run for run in await store.experiments(session.session_id)}
    selected = [runs[run_id] for run_id in review["run_ids"] if run_id in runs]
    if revision(selected) != review["runs_hash"]:
        raise ValueError("Reviewed runs changed; review the study evidence again")
    files = evidence_files(Path(session.workspace_path), review["evidence_files"])
    if source_hashes(files) != review["source_hashes"]:
        raise ValueError("Reviewed sources changed; review the study evidence again")
    if (
        figure_hashes(Path(session.workspace_path), review["figure_paths"])
        != review["figure_hashes"]
    ):
        raise ValueError("Reviewed figures changed; review the study evidence again")
    files.update(replication_sources(Path(session.workspace_path), review.get('replication_groups', [])))
    return {
        "protocol": study["protocol"],
        "review": review,
        "sources": {**protocol_files, **files},
        "run_ids": review["run_ids"],
        "figure_paths": review["figure_paths"],
    }
