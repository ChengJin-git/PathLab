"""Durable research-loop context and evidence-based progress detection.

Native conversation turns are not research iterations. A useful iteration changes
code, executes an experiment or records a decision; waiting on owned work is normal.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from dataclasses import dataclass, field

from . import store
from .budget import expired
from .research_progress import decision_summary, headline_metrics, strategy_checkpoint


async def context(session) -> dict:
    meta = session.recovery_metadata or {}
    now = time.time()
    elapsed = max(0, now - meta['started_at']) if meta.get('started_at') else 0
    if meta.get('gpu_wait_started_at'):
        elapsed = max(0, elapsed - max(0, now - meta['gpu_wait_started_at']))
    study = meta.get('study') or {}
    runs = await store.experiments(session.session_id)
    jobs = await store.jobs(session.session_id)
    from backend.common.task_runtime import get_runtime_status

    runtime = await get_runtime_status()
    decisions = meta.get('research_decisions', [])
    from .study import revision
    recorded = {run['run_id'] for run in runs
                if meta.get('assessed_runs', {}).get(run['run_id']) == revision(run)}
    return {
        'original_request': session.research_question,
        'working_goal': meta.get('current_goal'),
        'recent_instructions': await store.recent_instructions(session.session_id),
        'goal_provenance': 'working_goal is an agent-authored interpretation. Original request and subsequent command instructions determine scope; agent summaries cannot introduce user requirements. Commands may include platform maintenance instructions.',
        'output_language': meta.get('language', 'en-US'),
        'research_standard': meta.get('research_standard'),
        'task_kind': meta.get('task_kind'), 'report_policy': meta.get('report_policy'),
        'enabled_connectors': meta.get('enabled_connectors', []),
        'resource_references': meta.get('resource_references', []),
        'compute': {'worker_available': bool(runtime and runtime.get('is_running')),
                    'gpus': (runtime or {}).get('gpu_capacity', []),
                    'assignment': 'Submit device=gpu and accurate resources; the scheduler selects a fitting GPU. Inside the job use PATHLAB_DEVICE (cuda:0), never a host GPU index. Prefer GPU for tensor-heavy work; reduce batch size or use a measured peak when appropriate, not CPU merely because GPU 0 is busy.'},
        'budget': {'experiment_limit': session.max_iterations, 'used': session.current_iteration,
                   'remaining': max(0, session.max_iterations - session.current_iteration),
                   'remaining_seconds': max(0, int(meta.get('time_budget_seconds', 14400) - elapsed)),
                   'expired': expired(session)},
        'protocol_revision': study.get('revision'),
        'protocol_needs_update': bool(study and study['goal'] != meta.get('current_goal')),
        'protocol': study.get('protocol'),
        'review': study.get('review'),
        'replication_groups': [{key: group[key] for key in ['id', 'step_id', 'run_ids', 'comparison_revision', 'evidence_files']}
                               for group in meta.get('replication_groups', [])],
        'study_history_path': meta.get('study_history_path'),
        'recent_decisions': [decision_summary(d) for d in decisions[-4:]],
        'strategy_checkpoint': strategy_checkpoint(session, runs, jobs),
        'unreviewed_runs': [r['run_id'] for r in runs if r['status'] in {'completed', 'failed'} and r['run_id'] not in recorded],
        'runs': [{'run_id': r['run_id'], 'name': r.get('experiment_name'), 'status': r['status'],
                  **headline_metrics(r.get('metrics')), 'study_step': (r.get('config', {}).get('config') or {}).get('study_step')} for r in runs[-12:]],
        'job_counts': dict(Counter(j['status'] for j in jobs)),
        'job_history_note': 'Active/recent jobs have scheduling details; older records retain IDs for get_job.',
        'jobs': [{'job_id': j['job_id'], 'kind': j['kind'], 'status': j['status'],
                  'device': j.get('payload', {}).get('device'), 'scheduling': j.get('scheduling'),
                  'failure_before_continuation': j['status'] == 'failed' and j.get('updated_at', 0) < meta.get('recovery_check_after', 0)}
                 if j['status'] in store.ACTIVE_JOBS or index >= len(jobs) - 12
                 else {'job_id': j['job_id'], 'kind': j['kind'], 'status': j['status']}
                 for index, j in enumerate(jobs)],
        'native_work': meta.get('native_work'),
        'pending_instructions': [{'id': c['id'], 'text': c.get('text', '')} for c in meta.get('commands', []) if c['kind'] == 'message'],
    }


async def continuation_prompt(session, *, stalled=False) -> str:
    state = await context(session)
    return (
        'Continue the current authorized task. Read this live state, then take a concrete next action. '
        'A text progress update is not completion. Address the latest user instruction first. '
        'Use output_language from the live state for user-facing prose, tool activity descriptions and delegated task titles; '
        'pass it explicitly to every child. Retrieval queries may use the source language. '
        'For experiment tasks, when a training run has ended inspect its measured outputs, '
        'record_research_decision with assessment, scope and next_operation, and execute the next evidence-bearing operation. '
        'For analysis tasks inspect actual computation outputs, finish the requested analysis and publish its results; '
        'do not invent training or an original-study requirement for a standard analysis. For document tasks create and verify the requested files; '
        'do not add experiments or formal-paper evidence gates. Scientific uncertainty, '
        'a missing final-test cohort, or unfinished paper-quality evidence does not prevent '
        'useful development experiments. Use the remaining budget to investigate informative '
        'mechanisms; select and implement a direction instead of repeatedly writing plans. '
        'For scientific experiments, use strategy_checkpoint to revisit the primary comparison after repeated local repairs. '
        'A new tool call, checkpoint audit, or training-fit improvement is not by itself progress on the hypothesis. '
        'Choose the next evidence-bearing batch toward the planned scale and replication milestone. '
        'An inconclusive pilot can require more data, input coverage or optimization; it is not a route-wide negative result. '
        'Keep the original request and subsequent instructions distinct from your working_goal and experimental design choices. '
        'Do not launch another review/audit cycle by default. '
        'Repair ordinary failures yourself: inspect current logs, change code/paths/dependencies/tool arguments or resource settings, '
        'rerun and verify. Try a materially different approach when a targeted fix fails; do not repeat an identical failing action. '
        'A failed historical job, especially failure_before_continuation, does not establish a current service outage. '
        'After continuation recheck the environment and perform one bounded retry of the original operation. '
        'Only request_help when no useful authorized next action remains, with actual attempts/results and a specific external dependency or exhausted repairs. '
        'If the requested goal is genuinely fulfilled, finish_research with evidence. '
        + ('Several turns produced no new executed tool or research result. Re-read the latest '
           'decision and source files, diagnose the exact impediment, and execute or report it; '
           'do not repeat a waiting message without a live dependency. ' if stalled else '')
        + '\nLive research state:\n' + json.dumps(state, ensure_ascii=False, default=str)
    )


@dataclass
class ProgressWatch:
    """New successful tool evidence resets idle retries; repeated reads do not."""
    seen: set[str] = field(default_factory=set)
    idle_turns: int = 0
    seeded: bool = False

    def observe(self, messages: list[dict]) -> bool:
        completed = set()
        for message in messages:
            for part in message.get('content', []):
                state = part.get('state', {})
                if part.get('type') != 'tool' or state.get('status') != 'completed':
                    continue
                if 'get_research_context' in part.get('name', ''):
                    continue
                evidence = [part.get('name'), state.get('input'), state.get('output')]
                completed.add(hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest())
        progress = self.seeded and bool(completed - self.seen)
        self.seen.update(completed)
        self.seeded = True
        if progress:
            self.idle_turns = 0
        return progress

    def resume(self) -> int:
        self.idle_turns += 1
        return self.idle_turns
