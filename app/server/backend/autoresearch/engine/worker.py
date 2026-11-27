"""Independent, restartable supervisor for OpenCode research sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import time

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from redis.exceptions import RedisError

from backend.common.config import Config
from backend.common.model_config import resolve_model_config
from backend.database.database import engine, safe_session
from backend.database.models import AutoResearchSession

from . import store
from .budget import checkpoint_stop
from .recovery import block, classify_error
from .harness import ProgressWatch, continuation_prompt, context as research_context
from .research_progress import completed_job_summary, strategy_checkpoint
from .runtime import AgentRuntime
from .scheduler import ResearchScheduler, queue_order

log = logging.getLogger("research_worker")


def container_workspace(path):
    from ..runtime.container_backend import backend, container_path
    return container_path(path) if backend() == 'docker' else path


async def resume_context(meta: dict) -> str:
    saved = meta.get("budget_resume")
    if not saved:
        return ""
    context = "\n\nResume after a budget checkpoint. Preserve existing results and continue unfinished sections; do not restart the study. Read budget-checkpoint.json and findings.md if present."
    if saved.get("draft_id"):
        from backend.database.models import Manuscript

        async with safe_session() as db:
            draft = await db.get(Manuscript, saved["draft_id"])
            if draft:
                context += "\nSaved editable manuscript draft (continue and complete it):\n" + draft.content
    return context


async def stop_jobs(session_id: str):
    from .jobs import cancel

    for job in await store.jobs(session_id):
        if job["status"] in store.ACTIVE_JOBS:
            await cancel(job["job_id"])
    for _ in range(60):
        if not any(
            job["status"] in store.ACTIVE_JOBS for job in await store.jobs(session_id)
        ):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("Waiting for TaskWorker to acknowledge cancelled jobs")


async def watch_events(client, session_id: str, changed: asyncio.Event):
    """Native events wake reconciliation; disconnects are repaired by message reads."""
    while True:
        try:
            async for event in client.events():
                if event.get("type") == "server.connected" or session_id in json.dumps(
                    event
                ):
                    changed.set()
        except (OSError, ValueError, httpx.HTTPError):
            changed.set()
            await asyncio.sleep(2)


def project_message(message: dict) -> dict:
    """Display public text and tool results; keep internal reasoning in OpenCode."""
    result = {
        key: value
        for key, value in message.items()
        if key not in {"native", "snapshot"}
    }
    if "content" in message:
        content = []
        for part in message["content"]:
            if part.get("type") == "reasoning":
                continue
            item = {key: value for key, value in part.items() if key != "native"}
            if item.get("type") == "tool":
                state = dict(item.get("state", {}))
                for key in ["output", "input"]:
                    if (
                        key in state
                        and len(json.dumps(state[key], ensure_ascii=False)) > 16000
                    ):
                        state[key] = (
                            json.dumps(state[key], ensure_ascii=False)[:16000]
                            + "\n[See workspace artifact for full output]"
                        )
                item["state"] = state
            content.append(item)
        result["content"] = content
    return result


async def run_session(session_id: str):
    runtime = AgentRuntime(session_id)
    event_task = None
    try:
        await runtime.cleanup_orphan()
        session = await store.get(session_id)
        meta = session.recovery_metadata or {}
        # A queued stop/pause must not start a new model turn during recovery.
        if session.status in {"stopping", "pausing"}:
            commands = await store.take_commands(session_id)
            if session.status == "stopping":
                await stop_jobs(session_id)
            target = "interrupted" if session.status == "stopping" else "paused"
            for command in commands:
                if command["kind"] in {"stop", "pause"}:
                    await store.acknowledge_command(session_id, command["id"])
            await store.update(
                session_id, status=target, event={"kind": "state", "status": target}
            )
            return
        model = await resolve_model_config()
        if meta.get('title_pending'):
            from .titles import assign_title, generate_title

            title = await generate_title(session.research_question, meta['language'], model)
            await assign_title(session_id, title)
            session = await store.get(session_id)
            meta = session.recovery_metadata or {}
        if not meta.get("datasets_prepared"):
            from .datasets import prepare_pending_datasets

            await prepare_pending_datasets(session)
            await store.update(session_id, meta={"datasets_prepared": True})
            session = await store.get(session_id)
            meta = session.recovery_metadata or {}
        if meta.get("pending_references"):
            from uuid import UUID
            from backend.auth.models import User
            from backend.services.workbench import ResourceReference
            from .references import attach
            async with safe_session() as db:
                owner = await db.get(User, UUID(session.user_id))
            await attach(session_id, owner, [ResourceReference.model_validate(r) for r in meta["pending_references"]])
            from .references import acknowledge_references
            await acknowledge_references(session_id, meta["pending_references"])
            session = await store.get(session_id)
            meta = session.recovery_metadata or {}
        from .datasets import validate_access

        await validate_access(session)
        await store.update(
            session_id,
            status="running",
            phase=meta.get("research_phase", "ideation"),
            meta={"model": model.public(), "error": "", "recovery": None},
            event={"kind": "state", "status": "running", "model": model.model},
        )
        client = await runtime.start(model, meta.get("data_mounts", {}), meta.get("custom_skills", []), language=meta.get('language'))
        if meta.get("report_generation_id"):
            from backend.database.models import ManuscriptGeneration

            async with safe_session() as db:
                writing = await db.get(ManuscriptGeneration, meta["report_generation_id"], with_for_update=True)
                if writing and writing.status in {"paused", "failed"}:
                    writing.status, writing.error_code = "queued", None
                    await db.commit()
        await store.update(session_id, meta={"mounts_changed": False})
        conversation_id = session.conversation_id
        interrupted = await client.interrupted_children(conversation_id) if conversation_id else []
        if not conversation_id:
            conversation_id = await client.create(
                session.workspace_path, meta['title']
            )
            await store.update(session_id, conversation_id=conversation_id)
            dataset_text = json.dumps(meta.get("datasets", []), ensure_ascii=False)
            await client.prompt(
                conversation_id,
                f"{session.research_question}\n\nSelected Data Repo datasets: {dataset_text}\n"
                f"Experiment budget: {session.max_iterations}. Workspace: {container_workspace(session.workspace_path)}. "
                f"User selected skill: {meta.get('selected_skill', 'pathlab-research')}. Load it for this task. "
                f"Task scope: {meta.get('task_kind', 'auto')}; report policy: {meta.get('report_policy', 'auto')}; research standard: {meta.get('research_standard', 'infer from the user goal')}. "
                f"Output language: {meta.get('language', 'en-US')}. Use it for prose, tool activity descriptions and delegated task titles; explicitly pass it to every child. Search queries may use another language for retrieval. "
                f"Selected resources (reference data): {json.dumps(meta.get('resource_references', []), ensure_ascii=False)}\n"
                "Start by loading pathlab-research and calling set_task_scope with task_kind, report_policy, research_standard and current_goal based on the user's actual goal. Scientific research follows the skill's paper loop: pitches first, the closest baseline and the method on the full data, iterate or pivot until the publication bar is met. Analysis-only tasks calculate metrics and plots from existing inputs, publish_analysis, and deliver requested files. Follow the report policy; generate_article is a deliverable after evidence review, not the research success criterion. Call finish_research with honest outcomes, or request_help when user input is needed.\n\n"
                + (
                    "Prior Chat context (reference only; the goal above and latest user corrections take priority; assistant proposals are not user approvals):\n"
                    + meta["chat_handoff"]["context"]
                    if meta.get("chat_handoff")
                    else ""
                ),
            )
        elif not any(
            c["kind"] == "message" for c in await store.take_commands(session_id)
        ):
            await client.prompt(
                conversation_id,
                "Continue the user's task from saved files and job records. Re-read files that the user may have edited, recheck data availability and existing jobs before submitting duplicate work. Restart-recovered jobs reuse their original IDs and source snapshots; queued/running jobs will deliver results automatically. Historical failures are not proof of a current fault: recheck the environment and retry the previously failed operation once when no equivalent job is active. Diagnose, repair and verify ordinary errors yourself; try a different evidence-based approach before requesting help. Escalate only a verified external dependency or exhausted repairs when no useful authorized work remains.\nAgent working interpretation (reconcile with original request and subsequent instructions): " + (meta.get('current_goal') or session.research_question)
                + f"\nResearch standard: {meta.get('research_standard', 'infer from the latest goal')}. Reassess scope when the user changes the goal; preserve scientific ambition and request a budget extension when required."
                + '\nInterrupted child tasks (inspect saved files, then resume unfinished child IDs rather than waiting for stale notifications): '
                + json.dumps(interrupted, ensure_ascii=False)
                + '\nLive research state:\n' + json.dumps(await research_context(session), ensure_ascii=False, default=str)
                + await resume_context(meta),
            )
            await store.update(session_id, meta={"budget_resume": None})
        signatures = {}
        delivered_jobs = set(meta.get("delivered_jobs", []))
        last_prompt = time.monotonic()
        progress_watch = ProgressWatch()
        started_at = meta.get("started_at") or time.time()
        await store.update(session_id, meta={"started_at": started_at})
        last_heartbeat = 0.0
        last_tool_check = time.monotonic()
        changed = asyncio.Event()
        event_task = asyncio.create_task(watch_events(client, conversation_id, changed))

        while True:
            # Budget accounting after a crash resumes from this heartbeat; each write
            # rewrites the session metadata, so keep it coarse.
            if time.monotonic() - last_heartbeat >= 60:
                await store.update(session_id, meta={'last_active_at': time.time()})
                last_heartbeat = time.monotonic()
            current = await store.get(session_id)
            current_meta = current.recovery_metadata or {}
            if current_meta.get('delete_requested'):
                await stop_jobs(session_id)
                return
            references_waiting = bool(current_meta.get("pending_references")) and await client.active(conversation_id)
            if current_meta.get("pending_references") and not references_waiting:
                from uuid import UUID
                from backend.auth.models import User
                from backend.services.workbench import ResourceReference
                from .references import attach
                async with safe_session() as db:
                    owner = await db.get(User, UUID(current.user_id))
                pending_refs = current_meta["pending_references"]
                await attach(session_id, owner, [ResourceReference.model_validate(r) for r in pending_refs])
                # Remove only this batch; concurrently accepted references survive.
                from .references import acknowledge_references
                await acknowledge_references(session_id, pending_refs)
                current = await store.get(session_id)
                current_meta = current.recovery_metadata or {}
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
                await runtime.stop()
                client = await runtime.start(model, current_meta.get("data_mounts", {}), current_meta.get("custom_skills", []), language=current_meta.get('language'))
                event_task = asyncio.create_task(watch_events(client, conversation_id, changed))
                await store.update(session_id, meta={"mounts_changed": False})
            commands = await store.take_commands(session_id)
            for command in commands:
                action = command["kind"]
                if action == "message":
                    prompt = command["text"] + await resume_context(current_meta)
                    prompt += '\nLive research context:\n' + json.dumps(await research_context(current), ensure_ascii=False, default=str)
                    prompt += '\nAcknowledge the new instruction concisely and apply it now. Execute the next concrete step; do not answer only with a promise or wait for routine confirmation. Reconcile or redirect child tasks affected by this instruction.'
                    if interrupted:
                        prompt += '\nRestart-interrupted child IDs: inspect their saved outputs and resume or redirect them; do not wait for stale completion notifications. ' + json.dumps(interrupted, ensure_ascii=False)
                    if references_waiting:
                        prompt += '\nNewly selected resource mounts are pending until active native work ends. Acknowledge this instruction now; do not claim to have read the pending resources. Continue independent work and yield when mounts are needed.'
                    prompt += "\nReassess set_task_scope (including research_standard and current_goal) against this latest request before proceeding. An upgraded scientific goal needs a current protocol and fresh evidence review; it does not grant additional budget."
                    if current_meta.get("resource_references"):
                        prompt += "\nCurrent resource references: " + json.dumps(current_meta['resource_references'], ensure_ascii=False)
                    if command.get("continuation"):
                        prompt += (
                            "\n\nContinuation context: improve the existing results in this same session. "
                            "Review the saved findings and the selected baseline's config, metrics, code and artifacts. "
                            "Keep historical runs intact; submit new runs for comparisons. Preserve patient splits and evaluation "
                            "protocol unless the user requests a justified change; never tune on test results. "
                            "Update the plan and compare new findings against this baseline. If no run is selected, "
                            "use the saved findings as context. Remaining experiment attempts: "
                            f"{max(0, current.max_iterations - current.current_iteration)}.\n"
                            + json.dumps(command["continuation"], ensure_ascii=False)
                        )
                    await client.prompt(
                        conversation_id,
                        prompt,
                        "msg_" + command["id"],
                        internal=False,
                        delivery='steer',
                    )
                    if current_meta.get("budget_resume"):
                        await store.update(session_id, meta={"budget_resume": None})
                        current_meta = {**current_meta, "budget_resume": None}
                    last_prompt = time.monotonic()
                    interrupted = []
                    progress_watch.idle_turns = 0
                elif action == "answer":
                    payload = json.loads(command["text"])
                    try:
                        await client.reply_form(
                            conversation_id, payload["form_id"], payload["answer"]
                        )
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 409:
                            await store.update(
                                session_id,
                                event={
                                    "kind": "command",
                                    "command_id": command["id"],
                                    "status": "failed",
                                    "text": "Answer was rejected; check the pending form",
                                },
                            )
                            await store.acknowledge_command(session_id, command["id"])
                            continue
                elif action in {"pause", "stop"}:
                    await client.interrupt(conversation_id)
                    if action == "stop":
                        await stop_jobs(session_id)
                    status = "paused" if action == "pause" else "interrupted"
                    await store.acknowledge_command(session_id, command["id"])
                    await store.update(
                        session_id,
                        status=status,
                        phase=status,
                        event={"kind": "state", "status": status},
                    )
                    return
                await store.update(
                    session_id,
                    event={
                        "kind": "command",
                        "command_id": command["id"],
                        "status": "delivered",
                        "action": action,
                    },
                )
                await store.acknowledge_command(session_id, command["id"])
            # Reconcile full projected messages. This also repairs missed volatile events.
            if commands:
                current = await store.get(session_id)
                current_meta = current.recovery_metadata or {}
            if time.monotonic() - last_tool_check >= 30:
                restored = await client.ensure_research_tools(current.workspace_path)
                last_tool_check = time.monotonic()
                if restored:
                    await client.prompt(conversation_id,
                        'PathLab MCP tool discovery was disconnected and has now been restored. '
                        'Use the available pathlab_* tools to read current context, register measured decisions and submit the next authorized job. '
                        'An empty MCP resource list does not mean tools are unavailable. Check existing jobs before resubmitting; '
                        'do not remain in a local-test-only loop because of the previous connection failure.', delivery='steer')
            messages = await client.messages(conversation_id)
            for message in messages:
                if message.get("metadata", {}).get("pathlabInternal") or message.get(
                    "type"
                ) in {"user", "synthetic", "system"}:
                    continue
                if message["type"] not in {"assistant", "user", "idle"}:
                    continue
                message = project_message(message)
                signature = json.dumps(message, sort_keys=True)
                if signatures.get(message["id"]) != signature:
                    signatures[message["id"]] = signature
                    await store.update(
                        session_id, event={"kind": "message", "message": message}
                    )
            native = await client.work_state(conversation_id)
            active = bool(native['root_active'] or native['children'] or native['shells'] or native['inbox'])
            native_wait = active and not native['root_active']
            if native != current_meta.get('native_work'):
                await store.update(session_id, meta={'native_work': native}, event={'kind': 'native_work', **native})
            progress_watch.observe(messages)
            forms = await client.forms(conversation_id)
            if forms != current_meta.get("forms", []):
                await store.update(
                    session_id,
                    meta={"forms": forms},
                    event={"kind": "forms", "forms": forms},
                )
            all_jobs = await store.jobs(session_id)
            # A tool may have saved a report or requested help during message reads.
            current = await store.get(session_id)
            current_meta = current.recovery_metadata or {}
            gpu_waiting = [j for j in all_jobs if j['status'] == 'queued' and j['payload'].get('device') == 'gpu']
            outstanding = [j for j in all_jobs if j['status'] in store.ACTIVE_JOBS]
            waiting_only = bool(gpu_waiting) and not active and not forms and len(gpu_waiting) == len(outstanding) and not current_meta.get('report_generation_id') and not current_meta.get('budget_shutdown')
            wait_started = current_meta.get('gpu_wait_started_at')
            if waiting_only and not wait_started:
                await store.update(session_id, meta={'gpu_wait_started_at': time.time()}, event={'kind': 'gpu_wait', 'job_ids': [j['job_id'] for j in gpu_waiting]})
                current = await store.get(session_id)
            elif not waiting_only and wait_started:
                started_at = (current_meta.get('started_at') or started_at) + max(0, time.time() - wait_started)
                await store.update(session_id, meta={'started_at': started_at, 'gpu_wait_started_at': None})
                current = await store.get(session_id)
            if current_meta.get("recovery_requested") and current.status not in {
                "pausing",
                "stopping",
            }:
                await client.interrupt(conversation_id)
                await block(session_id, **current_meta["recovery_requested"])
                return
            if await checkpoint_stop(current, client, conversation_id, active, [project_message(m) for m in messages]):
                return
            current = await store.get(session_id)
            current_meta = current.recovery_metadata or {}
            if current_meta.get("budget_shutdown"):
                await asyncio.sleep(1)
                continue
            generation_id = current_meta.get("report_generation_id")
            if generation_id:
                from backend.services.manuscript_writer import read_job

                _, writing = await read_job(generation_id)
                if writing and writing.status in {"queued", "running"}:
                    if current_meta.get('report_failure_notified'):
                        await store.update(session_id, meta={'report_failure_notified': None})
                    await asyncio.sleep(1)
                    continue
                if writing and writing.status in {"paused", "failed"}:
                    if writing.error_code == 'budget':
                        await block(session_id, reason='budget', detail='Article writing reached its budget. Completed sections are saved; continue with an authorized budget extension.')
                        return
                    if current_meta.get('report_failure_notified') != generation_id:
                        await client.prompt(conversation_id,
                            'Article writing was interrupted; completed sections are saved. Diagnose the current failure and retry generate_article to resume the existing draft, '
                            'or fix its inputs/dependencies first. A first writer failure does not require user help. Continue independent useful work; '
                            'escalate only verified external dependencies or exhausted repairs with actual attempts/results.\n'
                            + json.dumps({'report_id': generation_id, 'status': writing.status, 'error_code': writing.error_code}, ensure_ascii=False))
                        await store.update(session_id, meta={'report_failure_notified': generation_id})
                        last_prompt = time.monotonic()
                if writing and writing.status == "completed" and current_meta.get("delivered_report_id") != generation_id:
                    await store.update(session_id, meta={"delivered_report_id": generation_id})
                    await client.prompt(conversation_id, "The LLM scientific article is complete, with verified citations and editable Word/LaTeX exports. Review the saved manuscript and then finish_research if the task is fulfilled.")
            pending = [j for j in all_jobs if j["status"] in store.ACTIVE_JOBS]
            finished = [
                j
                for j in all_jobs
                if j["status"] not in store.ACTIVE_JOBS
                and j["job_id"] not in delivered_jobs
            ]
            if current_meta.get("mounts_changed") and not active:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
                await runtime.stop()
                client = await runtime.start(model, current_meta.get("data_mounts", {}), current_meta.get("custom_skills", []), language=current_meta.get('language'))
                event_task = asyncio.create_task(
                    watch_events(client, conversation_id, changed)
                )
                await store.update(session_id, meta={"mounts_changed": False})
            if (
                current_meta.get("finish_requested")
                and not active
                and not pending
                and current.status not in {"pausing", "stopping"}
            ):
                completed = await store.update(
                    session_id,
                    status="completed",
                    expected_statuses={"running", "waiting"},
                    phase="completed",
                    event={"kind": "state", "status": "completed"},
                )
                if completed:
                    from .file_catalog import index_tree
                    await index_tree(current)
                    return
            remaining = int(current_meta.get("time_budget_seconds", 14400)) - (time.time() - started_at)
            if not waiting_only and remaining <= min(120, int(current_meta.get("time_budget_seconds", 14400)) * .1) and not current_meta.get("budget_warning_sent"):
                await store.update(session_id, meta={"budget_warning_sent": True})
                await client.prompt(conversation_id, "The time budget is nearly exhausted. Save completed report sections with save_report_draft now; reserve time to finish or checkpoint cleanly. Do not begin work that cannot finish within the remaining budget.")
            if not active and not forms and time.monotonic() - last_prompt > 4:
                if finished:
                    checkpoint = strategy_checkpoint(current, await store.experiments(session_id), all_jobs)
                    await client.prompt(
                        conversation_id,
                        "Background jobs finished. Inspect their actual outputs and complete the next action for the current task scope. "
                        "For failures, inspect get_job/logs, repair code, dependencies, paths or resource settings and rerun to verify within budget. A failed job alone is not a reason to request user assistance. "
                        "Record a research decision for training experiments; computation/download jobs instead support the requested analysis or document.\n"
                        + json.dumps([completed_job_summary(j) for j in finished], ensure_ascii=False)
                        + ('\nResearch strategy checkpoint (brief decision, no new review package):\n'
                           + json.dumps(checkpoint, ensure_ascii=False) if checkpoint else ''),
                    )
                    delivered_jobs.update(j["job_id"] for j in finished)
                    await store.update(
                        session_id, meta={"delivered_jobs": sorted(delivered_jobs)}
                    )
                    last_prompt = time.monotonic()
                    progress_watch.idle_turns = 0
                elif not pending:
                    last = messages[-1] if messages else {}
                    attempts = progress_watch.resume()
                    if attempts > 6:
                        raise RuntimeError(
                            "Agent produced six idle turns without a new successful tool action or settled experiment; runtime needs recovery"
                        )
                    prompt = await continuation_prompt(current, stalled=attempts >= 3)
                    if last.get('type') == 'idle' and last.get('outcome') == 'failed':
                        prompt += '\nThe previous native turn failed. Diagnose this error and retry with a targeted correction:\n' + json.dumps(last.get('error', {}), ensure_ascii=False)
                    await client.prompt(conversation_id, prompt)
                    last_prompt = time.monotonic()
            status = "waiting" if native_wait or (not active and pending) else "running"
            if current.status != status:
                await store.update(
                    session_id, status=status, event={"kind": "state", "status": status}
                )
            changed.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(changed.wait(), 2)
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        # Process restart leaves the durable session eligible for recovery.
        raise
    except DBAPIError:
        # Persistence cannot record a blocker during an outage. The scheduler
        # retries from the last durable heartbeat once the database is writable.
        raise
    except Exception as exc:
        log.exception("Research %s failed", session_id)
        # An agent/service failure need not destroy independent healthy jobs.
        await block(session_id, reason=classify_error(exc), detail=str(exc))
    finally:
        if event_task:
            event_task.cancel()
            await asyncio.gather(event_task, return_exceptions=True)
        await runtime.stop()


async def main():
    from backend.common.redis_client import close_redis, init_redis
    from backend.database import close_db, init_db

    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    await init_db()
    await init_redis()

    async def cleanup(session_id: str):
        await AgentRuntime(session_id).cleanup_orphan()

    scheduler = ResearchScheduler(run_session, stop_jobs, cleanup)
    from backend.services.manuscript_writer import WritingQueue

    writing_queue = WritingQueue()
    from backend.services.chat_deletion import ChatDeletionQueue
    deletion_queue = ChatDeletionQueue(scheduler, writing_queue)
    from backend.storage.deletion import StorageQueue
    storage_queue = StorageQueue()
    recovered = False
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in [signal.SIGTERM, signal.SIGINT]:
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows ProactorEventLoop
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    # One supervisor owns this deployment's research sessions.
    async with engine.connect() as lock_connection:
        locked = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(72419832)")
        )
        if not locked:
            raise RuntimeError("A Research Worker is already running")
        try:
            await writing_queue.recover()
            while not stop.is_set():
                try:
                    async with safe_session() as db:
                        rows = (
                            await db.scalars(
                                select(AutoResearchSession)
                                .where(
                                    AutoResearchSession.status.in_(store.ACTIVE),
                                )
                                .order_by(*queue_order())
                            )
                        ).all()
                    if not recovered:
                        await scheduler.recover(rows)
                        recovered = True
                    await deletion_queue.tick()
                    await storage_queue.tick()
                    await scheduler.tick(rows, Config.get_max_autoresearch_concurrent())
                    await writing_queue.tick()
                except (DBAPIError, RedisError, OSError) as exc:
                    log.error('Research infrastructure unavailable; retrying in 5s: %s', type(exc).__name__)
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), 5)
                    continue
                try:
                    await asyncio.wait_for(stop.wait(), 2)
                except asyncio.TimeoutError:
                    pass
        finally:
            await deletion_queue.shutdown()
            await storage_queue.shutdown()
            await scheduler.shutdown()
            await writing_queue.shutdown()
            await lock_connection.execute(text("SELECT pg_advisory_unlock(72419832)"))
    await close_redis()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
