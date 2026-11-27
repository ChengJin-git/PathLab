"""Transactional research state; PostgreSQL serializes per-session event writers."""

from __future__ import annotations

from copy import deepcopy
import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import timezone
from typing import Any

from sqlalchemy import String, case, cast, func, select

from backend.database.database import safe_session
from backend.database.models import (
    AutoResearchEvent,
    AutoResearchExperiment,
    AutoResearchSession,
    ResearchJob,
    utc_now,
)

ACTIVE = {"preparing", "queued", "running", "waiting", "pausing", "stopping"}
ACTIVE_JOBS = {"queued", "running", "cancelling"}


logger = logging.getLogger(__name__)

def invalidate_study_review(meta):
    if meta.get('study'):
        meta['study'] = {**meta['study'], 'review': None}


def summary(row: AutoResearchSession) -> dict[str, Any]:
    meta = row.recovery_metadata or {}
    return {
        "session_id": row.session_id,
        "conversation_id": row.conversation_id,
        "chat_conversation_id": row.chat_conversation_id,
        "question": row.research_question,
        "title": meta["title"],
        'task_kind': meta.get('task_kind','auto'),
        'report_policy': meta.get('report_policy','auto'),
        'research_standard': meta.get('research_standard'),
        'current_goal': meta.get('current_goal'),
        "user_id": row.user_id,
        "model": meta.get("model", {}).get("model", ""),
        "status": row.status,
        "sequence": row.event_sequence,
        "outcome": meta.get(
            "outcome", "completed" if row.status == "completed" else ""
        ),
        "recovery": meta.get("recovery"),
        "stage": row.phase,
        "workspace_path": row.workspace_path,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).timestamp(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).timestamp(),
        "max_iterations": row.max_iterations,
        "current_iteration": row.current_iteration,
        "resume_available": row.status
        in {"paused", "interrupted", "failed", "blocked"},
        "error": meta.get("error", ""),
    }


async def get(session_id: str) -> AutoResearchSession:
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession).where(
                AutoResearchSession.session_id == session_id
            )
        )
        if row is None:
            raise KeyError(session_id)
        return row


async def merge_metadata_items(
    session_id: str, field: str, items: list[dict], key: str, *, maximum: int | None = None
):
    """Atomically merge concurrently published dataset/artifact entries."""
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if row is None or (row.recovery_metadata or {}).get('delete_requested'):
            raise ValueError('Research is unavailable')
        meta = dict(row.recovery_metadata or {})
        entries = {item[key]: item for item in meta.get(field, [])}
        entries.update({item[key]: item for item in items})
        if maximum is not None and len(entries) > maximum:
            raise ValueError(f'At most {maximum} {field} entries per session')
        meta[field] = list(entries.values())
        row.recovery_metadata = meta
        await db.commit()


async def attach_dataset(session_id: str, dataset: dict, mounts: dict):
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        meta = dict(row.recovery_metadata or {})
        items = {item["dataset_id"]: item for item in meta.get("datasets", [])}
        items[dataset["dataset_id"]] = dataset
        prefix = f'/research-data/{dataset["dataset_id"]}'
        retained_mounts = {
            source: target for source, target in meta.get('data_mounts', {}).items()
            if target != prefix and not target.startswith(prefix + '/')
        }
        meta.update(
            {
                "datasets": list(items.values()),
                "data_mounts": {**retained_mounts, **mounts},
                "mounts_changed": True,
            }
        )
        row.recovery_metadata = meta
        await db.commit()
    await update(session_id, event={"kind": "dataset", "dataset": dataset})


async def update(
    session_id: str,
    *,
    meta: dict | None = None,
    event: dict | None = None,
    expected_statuses: set[str] | None = None,
    expected_metadata: dict | None = None,
    expected_iteration: int | None = None,
    **fields,
) -> dict:
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(session_id)
        if expected_statuses is not None and row.status not in expected_statuses:
            return {}
        state = dict(row.recovery_metadata or {})
        if expected_metadata is not None and (
            any(state.get(key) != value for key, value in expected_metadata.items())
            or (expected_iteration is not None and row.current_iteration != expected_iteration)
        ):
            raise ValueError('Research changed while recording the study; reload its goal, protocol and runs')
        if state.get('delete_requested'):
            return {}
        if fields.get("status") == "completed" and state.get("commands"):
            return {}
        if meta:
            state.update(meta)
            row.recovery_metadata = state
        for key, value in fields.items():
            if (
                key == "status"
                and row.status in {"pausing", "stopping"}
                and value in {"preparing", "queued", "running", "waiting"}
            ):
                if event and event.get("kind") == "state":
                    event = {**event, "status": row.status}
                continue
            setattr(row, key, value)
        row.updated_at = utc_now()
        payload = {}
        if event is not None:
            row.event_sequence = seq = row.event_sequence + 1
            active_step = next(
                (
                    step
                    for step in (row.experiment_plan or [])
                    if step.get("status") == "running"
                ),
                {},
            )
            payload = {
                "phase": state.get("research_phase", "ideation"),
                "step_id": active_step.get("id"),
                **event,
                "seq": seq,
                "ts": time.time(),
                "session_id": session_id,
            }
            db.add(
                AutoResearchEvent(
                    session_id=session_id,
                    sequence=seq,
                    event_type=payload.get("kind", "state"),
                    event_data=payload,
                )
            )
        await db.commit()
        return payload


async def events(session_id: str, after: int = 0, limit: int = 500, *, latest: bool = False) -> list[dict]:
    async with safe_session() as db:
        rows = (
            await db.scalars(
                select(AutoResearchEvent)
                .where(
                    AutoResearchEvent.session_id == session_id,
                    AutoResearchEvent.sequence > after,
                )
                .order_by(AutoResearchEvent.sequence.desc() if latest else AutoResearchEvent.sequence)
                .limit(limit)
            )
        ).all()
        if latest:
            rows = list(reversed(rows))
        result = []
        for row in rows:
            event = row.event_data
            message = event.get("message")
            # User-facing instructions have durable command events. Native user
            # messages include historical supervisor prompts without metadata.
            if (
                event.get("kind") == "message"
                and isinstance(message, dict)
                and (
                    message.get("type") in {"user", "synthetic", "system"}
                    or message.get("metadata", {}).get("pathlabInternal")
                )
            ):
                event = {"kind": "internal", "seq": event["seq"], "ts": event.get("ts")}
            result.append(event)
        return result


async def recent_instructions(session_id: str, limit: int = 8) -> list[dict]:
    """Original command text, not agent-authored goal summaries or native prompts."""
    payload = AutoResearchEvent.event_data
    async with safe_session() as db:
        rows = (await db.scalars(select(AutoResearchEvent).where(
            AutoResearchEvent.session_id == session_id,
            AutoResearchEvent.event_type == 'command',
            func.coalesce(payload['text'].as_string(), '') != '',
        ).order_by(AutoResearchEvent.sequence.desc()).limit(limit))).all()
    return [{key: row.event_data[key] for key in ('seq', 'command_id', 'action', 'text')
             if key in row.event_data} for row in reversed(rows)]


ACTIVITY_KINDS = frozenset({'message', 'command', 'job', 'dataset', 'literature', 'error', 'report', 'study',
                            'research_decision', 'native_work'})
ANCHOR_KINDS = frozenset({'command', 'report', 'study', 'research_decision'})
ACTIVITY_INDEX_SESSIONS = 64
# Events are append-only and sequenced under the session row lock, so the logical activity
# items of a session can be extended from the events after the last indexed sequence instead
# of decoding every historical message snapshot on each page load.
_activity_index: OrderedDict[str, dict] = OrderedDict()
_activity_locks: dict[str, asyncio.Lock] = {}


def _activity_scan(session_id: str, after: int):
    """(event id, kind, logical key, sequence, anchor) for eligible events after a sequence."""
    payload, kind = AutoResearchEvent.event_data, AutoResearchEvent.event_type
    identity = case(
        (kind == 'message', payload['message']['id'].as_string()),
        (kind == 'command', payload['command_id'].as_string()),
        (kind == 'job', payload['job_id'].as_string()),
        (kind == 'native_work', 'native'),
        else_=None,
    )
    # event_type is part of the key so unrelated resource IDs never collide.
    key = func.coalesce(identity, cast(AutoResearchEvent.sequence, String))
    # Anchors keep recent prose and user instructions visible after refresh even when
    # hundreds of distinct tool messages occupy the recent page.
    anchor = payload['kind'].as_string().in_(ANCHOR_KINDS) | ((payload['kind'].as_string() == 'message') & (
        (func.coalesce(payload['message']['text'].as_string(), '') != '')
        | cast(payload['message']['content'], String).like('%"text"%')))
    return select(AutoResearchEvent.id, kind, key, AutoResearchEvent.sequence, anchor).where(
        AutoResearchEvent.session_id == session_id,
        AutoResearchEvent.sequence > after,
        kind.in_(ACTIVITY_KINDS),
        (kind != 'message') | (
            (payload['message']['type'].as_string() == 'assistant')
            & func.coalesce(payload['message']['metadata']['pathlabInternal'].as_boolean(), False).is_(False)),
    ).order_by(AutoResearchEvent.sequence)


async def _activity_groups(db, session_id: str) -> list[list]:
    """[first_seq, last_seq, anchor] per logical activity item, newest first."""
    async with _activity_locks.setdefault(session_id, asyncio.Lock()):
        entry = _activity_index.pop(session_id, None)
        if entry and await db.scalar(select(AutoResearchEvent.id).where(
                AutoResearchEvent.session_id == session_id,
                AutoResearchEvent.sequence == entry['through'])) != entry['through_id']:
            entry = None  # The session's history was replaced; rebuild from its first event.
        entry = entry or {'through': 0, 'through_id': None, 'groups': {}}
        for event_id, kind, key, sequence, anchor in (await db.execute(_activity_scan(session_id, entry['through']))).all():
            group = entry['groups'].setdefault((kind, key), [sequence, sequence, anchor])
            group[1], group[2] = sequence, anchor
            entry['through'], entry['through_id'] = sequence, event_id
        _activity_index[session_id] = entry
        while len(_activity_index) > ACTIVITY_INDEX_SESSIONS:
            _activity_locks.pop(_activity_index.popitem(last=False)[0], None)
        return sorted(entry['groups'].values(), key=lambda group: -group[0])


def _payload(value):
    return json.loads(value) if isinstance(value, str) else value


async def activity(session_id: str, before: int = 0, limit: int = 100, *, context: bool = False) -> dict:
    """Page logical activity, not token snapshots; order remains stable on updates."""
    async with safe_session() as db:
        groups = [group for group in await _activity_groups(db, session_id) if not before or group[0] < before]
        selected = {first: last for first, last, _ in groups[:limit]}
        if context and len(groups) > limit:
            selected.update({first: last for first, last, _ in [group for group in groups if group[2]][:20]})
        payloads = dict((await db.execute(select(AutoResearchEvent.sequence, AutoResearchEvent.event_data).where(
            AutoResearchEvent.session_id == session_id,
            AutoResearchEvent.sequence.in_(set(selected) | set(selected.values()))))).all())
    return {
        'items': [{**_payload(payloads[first]), **_payload(payloads[last]), 'activity_seq': first}
                  for first, last in sorted(selected.items())],
        'next_before': groups[limit - 1][0] if len(groups) > limit else None,
    }


async def warm_activity(sessions: int = 20) -> None:
    """Index recently active sessions at startup so their pages open without a full scan."""
    try:
        async with safe_session() as db:
            identities = (await db.scalars(select(AutoResearchSession.session_id)
                                           .order_by(AutoResearchSession.updated_at.desc()).limit(sessions))).all()
        for session_id in identities:
            await activity(session_id, limit=1)
    except Exception:  # Warming is an optimisation; pages build their index on demand.
        logger.warning('Research activity warm-up failed', exc_info=True)


async def latest_job_progress(session_id: str) -> list[dict]:
    """The newest progress event of every job; the workbench draws one progress bar per job."""
    payload = AutoResearchEvent.event_data
    job = func.coalesce(payload['job_id'].as_string(), payload['run_id'].as_string())
    latest = select(func.max(AutoResearchEvent.sequence)).where(
        AutoResearchEvent.session_id == session_id,
        AutoResearchEvent.event_type.in_({'progress', 'download_progress'}),
    ).group_by(job)
    async with safe_session() as db:
        rows = (await db.scalars(select(payload).where(
            AutoResearchEvent.session_id == session_id, AutoResearchEvent.sequence.in_(latest)))).all()
    return [_payload(row) for row in rows]


async def continue_session(
    session_id: str,
    *,
    text: str = "",
    dataset_ids: list[str] | None = None,
    additional_experiments: int = 0,
    replace_datasets: bool = False,
    baseline_run_id: str | None = None,
    additional_time_seconds: int = 0,
    references: list[dict] | None = None,
) -> str:
    """Atomically queue user context and resume; cannot race an agent admission."""
    from uuid import uuid4

    command_id = uuid4().hex
    async with safe_session() as db:
        from .admission import lock_admission
        await lock_admission(db)
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(session_id)
        if row.status not in {"blocked", "failed", "paused", "interrupted", "completed"}:
            raise ValueError(
                "This session is already active. Refresh its status before continuing."
            )
        from .admission import check_capacity
        await check_capacity(db, row.user_id)
        refining = row.status == "completed"
        if (refining or baseline_run_id) and not text.strip():
            raise ValueError("Describe how you want to improve the existing results.")
        baseline = None
        if baseline_run_id:
            experiment = await db.scalar(
                select(AutoResearchExperiment).where(
                    AutoResearchExperiment.session_id == session_id,
                    AutoResearchExperiment.training_task_id == baseline_run_id,
                    AutoResearchExperiment.status == "completed",
                )
            )
            if experiment is None:
                raise ValueError("Select a completed experiment from this session.")
            baseline = {
                "run_id": baseline_run_id,
                "name": experiment.experiment_name,
                "config": deepcopy(experiment.hyperparams or {}),
                "metrics": deepcopy(experiment.metrics or {}),
                "path": f"runs/{baseline_run_id}",
            }
        meta = dict(row.recovery_metadata or {})
        if references:
            from .references import merge_pending_references
            merge_pending_references(meta, references)
        if text.strip() or dataset_ids or references:
            invalidate_study_review(meta)
        if additional_time_seconds:
            if not 60 <= additional_time_seconds <= 259200:
                raise ValueError("Choose a continuation time allowance between 1 minute and 72 hours.")
            meta["time_budget_seconds"] = additional_time_seconds
        if meta.get("budget_shutdown") or (meta.get("recovery") or {}).get("reason") == "budget":
            meta["budget_resume"] = {
                "phase": meta.get("research_phase"), "draft_id": meta.get("report_draft_id"),
                "checkpoint": "budget-checkpoint.json",
            }
        continuation = None
        if refining or baseline:
            continuation = {
                "command_id": command_id,
                "baseline": baseline,
                "instructions": text.strip(),
                "created_at": time.time(),
                "previous_report": row.final_report or "",
            }
            meta["continuation"] = continuation
        if refining:
            meta["manuscript_id"] = None
            meta["report_generation_id"] = None
            meta["report_start_iteration"] = row.current_iteration
            meta["report_history"] = [
                *meta.get("report_history", []),
                {
                    "report": row.final_report or "",
                    "outcome": meta.get("outcome", "completed"),
                    "iteration": row.current_iteration,
                    "plan": deepcopy(row.experiment_plan or []),
                    "saved_at": time.time(),
                },
            ]
            meta["research_phase"] = "planning"
            row.phase = "planning"
            # Keep the last visible result/plan until the new round replaces it.
            # Historical outputs are not evidence that the continuation is done.
        from .effort import MAX_EXPERIMENTS
        if row.max_iterations + additional_experiments > MAX_EXPERIMENTS:
            raise ValueError(f"The total experiment budget cannot exceed {MAX_EXPERIMENTS} attempts.")
        row.max_iterations += additional_experiments
        if dataset_ids:
            meta["dataset_ids"] = list(dict.fromkeys([*([] if replace_datasets else meta.get("dataset_ids", [])), *dataset_ids]))
            if replace_datasets:
                meta.update({"datasets": [], "data_mounts": {}, "mounts_changed": True})
        meta.update(
            {
                "finish_requested": False,
                "recovery_requested": None,
                "recovery": None,
                "error": "",
                "outcome": "",
                "datasets_prepared": False,
                "started_at": None,
                "recovery_check_after": time.time(),
                "queue_entered_at": time.time(),
                "queue_submitted_at": time.time(),
                "last_active_at": None,
                "budget_shutdown": None,
                "budget_stop_requested": None,
                "budget_warning_sent": False,
                "gpu_wait_started_at": None,
            }
        )
        # Pause/stop commands from a previous interruption must not stop the resume.
        commands = [
            c
            for c in meta.get("commands", [])
            if c["kind"] not in {"pause", "stop", "resume"}
        ]
        if text.strip():
            command = {"id": command_id, "kind": "message", "text": text.strip()}
            if continuation:
                command["continuation"] = continuation
            commands.append(command)
        meta["commands"] = commands
        row.status = "queued"
        row.updated_at = utc_now()
        events = [{"kind": "state", "status": "queued", "phase": meta.get("research_phase", "ideation")}]
        if text.strip():
            events.append(
                {
                    "kind": "command",
                    "action": "message",
                    "command_id": command_id,
                    "text": text.strip(),
                    "status": "queued",
                    **({"baseline": baseline} if baseline else {}),
                }
            )
        for event in events:
            row.event_sequence += 1
            db.add(
                AutoResearchEvent(
                    session_id=session_id,
                    sequence=row.event_sequence,
                    event_type=event["kind"],
                    event_data={
                        **event,
                        "seq": row.event_sequence,
                        "ts": time.time(),
                        "session_id": session_id,
                    },
                )
            )
        row.recovery_metadata = meta
        await db.commit()
    return command_id


def _experiment(row) -> dict:
    return {**row.to_dict(), "run_id": row.training_task_id, "config": row.hyperparams or {}, "dataset_id": row.dataset_id}


async def experiment(session_id: str, run_id: str) -> dict | None:
    async with safe_session() as db:
        row = await db.scalar(select(AutoResearchExperiment).where(
            AutoResearchExperiment.session_id == session_id, AutoResearchExperiment.training_task_id == run_id))
    return _experiment(row) if row else None


async def experiments(session_id: str) -> list[dict]:
    async with safe_session() as db:
        rows = (
            await db.scalars(
                select(AutoResearchExperiment)
                .where(
                    AutoResearchExperiment.session_id == session_id,
                    ~select(ResearchJob.job_id).where(
                        ResearchJob.job_id == AutoResearchExperiment.training_task_id,
                        ResearchJob.kind != "experiment",
                    ).exists(),
                )
                .order_by(AutoResearchExperiment.id)
            )
        ).all()
        return [_experiment(row) for row in rows]


async def experiment_update(session_id: str, run_id: str, **fields) -> None:
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchExperiment)
            .where(
                AutoResearchExperiment.session_id == session_id,
                AutoResearchExperiment.training_task_id == run_id,
            )
            .with_for_update()
        )
        if row is None:
            raise KeyError(run_id)
        if row.status in {"cancelled", "cancelling"} and fields.get("status") not in {
            None,
            "cancelled",
            "cancelling",
        }:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        if row.status == "completed":
            from backend.services.result_analysis.sources import index_experiment
            session = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.session_id == session_id))
            await index_experiment(db, session, row)
        await db.commit()
    await update(session_id, event={"kind": "experiment", "run_id": run_id, **fields})


async def command(session_id: str, kind: str, text: str = "", *, references: list[dict] | None = None) -> str:
    from uuid import uuid4

    command_id = uuid4().hex
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError(session_id)
        meta = dict(row.recovery_metadata or {})
        if meta.get('delete_requested'):
            raise ValueError('Research is being deleted')
        if references:
            from .references import merge_pending_references
            merge_pending_references(meta, references)
        if kind == 'message' and len(meta.get('commands') or []) >= 32:
            from fastapi import HTTPException
            raise HTTPException(429, 'This research has too many pending instructions. Wait for delivery before sending more.')
        meta["commands"] = [
            *(meta.get("commands") or []),
            {"id": command_id, "kind": kind, "text": text},
        ]
        if kind == "message":
            invalidate_study_review(meta)
            meta["finish_requested"] = False
            meta["recovery_requested"] = None
        if kind == 'resume':
            meta['recovery_check_after'] = time.time()
        row.recovery_metadata = meta
        if kind == "resume":
            row.status = "queued"
        elif kind == "stop":
            row.status = "stopping"
        elif kind == "pause":
            row.status = "pausing"
        row.updated_at = utc_now()
        await db.commit()
    await update(
        session_id,
        event={
            "kind": "command",
            "command_id": command_id,
            "action": kind,
            "text": text,
            "status": "queued",
        },
    )
    if kind in {"resume", "pause", "stop"}:
        status = {"resume": "queued", "pause": "pausing", "stop": "stopping"}[kind]
        await update(session_id, event={"kind": "state", "status": status})
    return command_id


async def take_commands(session_id: str) -> list[dict]:
    row = await get(session_id)
    return list((row.recovery_metadata or {}).get("commands", []))


async def acknowledge_command(session_id: str, command_id: str):
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        meta = dict(row.recovery_metadata or {})
        meta["commands"] = [
            command
            for command in meta.get("commands", [])
            if command["id"] != command_id
        ]
        row.recovery_metadata = meta
        await db.commit()


async def jobs(session_id: str, *, compact: bool = False) -> list[dict]:
    from backend.common.task_runtime import get_runtime_status
    runtime = await get_runtime_status() or {}
    scheduling = {item['task_id']: item for item in runtime.get('gpu_stage_details', {}).values()}
    async with safe_session() as db:
        rows = (
            await db.scalars(
                select(ResearchJob)
                .where(ResearchJob.session_id == session_id)
                .order_by(ResearchJob.created_at.desc() if compact else ResearchJob.created_at)
                .limit(100 if compact else None)
            )
        ).all()
        return [
            {
                "job_id": r.job_id,
                "kind": r.kind,
                "status": r.status,
                "updated_at": r.updated_at.replace(tzinfo=timezone.utc).timestamp(),
                "payload": {k: v for k, v in r.payload.items() if k in {'name', 'device', 'gpu_estimate'}} if compact else r.payload,
                "result": {**r.result, 'artifacts': r.result.get('artifacts', [])[:20]} if compact else r.result,
                "scheduling": scheduling.get(r.job_id) if r.status in ACTIVE_JOBS else None,
            }
            for r in rows
        ]


async def job_update(job_id: str, status: str, result: dict | None = None):
    async with safe_session() as db:
        row = await db.get(ResearchJob, job_id, with_for_update=True)
        if row is None:
            raise KeyError(job_id)
        if row.status in {"cancelled", "cancelling"} and status not in {
            "cancelled",
            "cancelling",
        }:
            return
        row.status = status
        if result is not None:
            row.result = result
        row.updated_at = utc_now()
        sid, kind = row.session_id, row.kind
        await db.commit()
    await update(
        sid,
        event={
            "kind": "job",
            "job_id": job_id,
            "job_kind": kind,
            "status": status,
            "result": result or {},
        },
    )
