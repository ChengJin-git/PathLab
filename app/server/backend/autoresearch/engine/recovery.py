"""Recoverable interruptions retain work and describe useful next actions."""

from __future__ import annotations

import httpx

from . import store
from .dataset_files import DatasetPreparationTimeout

REASONS = [
    "missing_data",
    "data_access",
    "data_preparation",
    "code_error",
    "service",
    "budget",
    "needs_input",
    "direction",
    "other",
]


# Frames (evaluation, data, baselines) that must each fail before the agent may hand the choice of
# direction to the user. The user's question, not one dataset, is the scope.
FRAMES_BEFORE_DIRECTION_HELP = 2


def assess_help(session, arguments: dict, jobs: list[dict]) -> dict:
    """Escalate current, evidenced blockers rather than the first tool failure."""
    attempts = arguments['attempts']
    if arguments['reason'] == 'code_error' and arguments['blocker'] != 'repair_exhausted':
        raise ValueError('Ordinary code errors are yours to repair. Inspect, edit and rerun before reporting exhausted repairs; code editing does not require user approval.')
    if not arguments['why_user'].strip() or any(
        not attempt['action'].strip() or not attempt['result'].strip() for attempt in attempts
    ):
        raise ValueError('Describe actual checks/repairs, their observed results, and why user action is necessary.')
    if arguments['blocker'] == 'repair_exhausted':
        actions = {' '.join(attempt['action'].casefold().split()) for attempt in attempts}
        if len(actions) < 2:
            raise ValueError('Continue autonomously: inspect the actual error, apply a targeted repair and verify it. Try a different evidence-based approach before escalating; repeating the same failed action is not a repair.')
        if any(job['status'] in store.ACTIVE_JOBS for job in jobs):
            raise ValueError('A background job is still pending. End the turn and inspect its result before declaring repair attempts exhausted.')
    job_ids = arguments.get('job_ids', [])
    by_id = {job['job_id']: job for job in jobs}
    checked_after = (session.recovery_metadata or {}).get('recovery_check_after', 0)
    for identity in job_ids:
        job = by_id.get(identity)
        if job is None or job['status'] != 'failed':
            raise ValueError('Blocker evidence must reference a failed job in this session. Check get_job and the current result.')
        if checked_after and job['updated_at'] < checked_after:
            raise ValueError('This failure predates the current continuation. Recheck the repaired environment and retry the original operation once; historical failure logs do not prove a current blocker.')
    detail = '\n'.join(f'{index}. {attempt["action"]}: {attempt["result"]}' for index, attempt in enumerate(attempts, 1))
    meta = session.recovery_metadata or {}
    if arguments['reason'] == 'direction' and meta.get('research_standard') == 'scientific' and meta.get('study'):
        from .study import exhausted_frame_count

        if exhausted_frame_count(meta) < FRAMES_BEFORE_DIRECTION_HELP:
            raise ValueError(
                'Choosing a new frame is your job while it still answers the user\'s question: change the data, '
                'endpoint, evaluation or baselines (search PathTrove and the Data Repo for cohorts and endpoints with '
                'room above the closest baseline), record the new protocol and continue. Ask the user for a direction '
                f'only after {FRAMES_BEFORE_DIRECTION_HELP} frames are exhausted. If no accessible data fits the question, '
                "request_help(reason='missing_data') with what you searched; if the question itself must change, "
                "reason='needs_input'.")
    if (meta.get('research_standard') == 'scientific' and meta.get('study')
            and arguments['reason'] in {'missing_data', 'data_access', 'needs_input'}):
        directions = {d['id'] for d in meta['study']['protocol']['directions']}
        alternatives = arguments.get('alternatives', [])
        if (len(alternatives) != len(directions)
                or {a['direction_id'] for a in alternatives} != directions
                or any(not a['reason'].strip() for a in alternatives)):
            raise ValueError('A route-specific dependency is not a task blocker: assess each current direction in alternatives and continue any useful authorized route')
        detail += '\n' + '\n'.join(f'{a["direction_id"]}: {a["reason"]}' for a in alternatives)
    return {
        'reason': arguments['reason'], 'summary': arguments['summary'],
        'next_steps': arguments['next_steps'],
        'detail': f'{detail}\n{arguments["why_user"]}',
    }


def classify_error(error: Exception) -> str:
    if isinstance(error, DatasetPreparationTimeout):
        return 'data_preparation'
    text = str(error).lower()
    if (
        isinstance(error, FileNotFoundError)
        or "no such file" in text
        or "not found" in text
        and "dataset" in text
    ):
        return "missing_data"
    if isinstance(error, PermissionError) or any(
        word in text
        for word in ["403", "401", "permission", "access denied", "restricted"]
    ):
        return "data_access"
    if "budget" in text or "time limit" in text:
        return "budget"
    if isinstance(error, (httpx.HTTPError, TimeoutError)) or any(
        word in text
        for word in ["429", "rate_limit", "connection", "model unavailable", "endpoint", "timed out", "timeout", "sandbox exited", "sandbox startup", "pathlab mcp"]
    ):
        return "service"
    if any(
        word in text
        for word in ["traceback", "syntaxerror", "runtimeerror", "exit code"]
    ):
        return "code_error"
    return "other"


async def block(
    session_id: str,
    *,
    reason: str,
    summary: str = "",
    next_steps: list[str] | None = None,
    detail: str = "",
):
    issue = {
        "reason": reason,
        "summary": summary,
        "next_steps": next_steps or [],
        "detail": detail[:12000],
    }
    await store.update(
        session_id,
        status="blocked",
        expected_statuses={"running", "waiting", "preparing"},
        meta={"recovery": issue, "recovery_requested": None, "error": ""},
        event={"kind": "state", "status": "blocked", "recovery": issue},
    )
