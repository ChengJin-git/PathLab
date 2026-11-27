"""Durable experiment submission and TaskWorker execution."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from backend.common.queue_lifecycle import (
    fifo_key,
    is_restart_interruption,
    recover_fifo,
)
from backend.common.task_dispatch import (
    build_task_descriptor,
    enqueue_task_descriptor,
    publish_task_cancellation,
)
from backend.database.database import safe_session
from backend.database.models import (
    AutoResearchExperiment,
    AutoResearchSession,
    ResearchJob,
)

from ..runtime import container_backend
from . import store
from .processes import spawn_owned
from .processes import stop as stop_owned
from .runtime import sandbox_command
from .skill_credentials import skill_environment

log = logging.getLogger(__name__)

MAX_DEVICE_RETRIES = 2


@asynccontextmanager
async def staged_source(session, kind):
    """Copy outside the deletion lock; only publish the finished snapshot under it."""
    if kind == 'download':
        yield None
        return
    from backend.common.config import Config
    staging = Config.get_autoresearch_dir() / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging, prefix='source-') as directory:
        snapshot = Path(directory) / 'source'
        def copy():
            snapshot.mkdir()
            for entry in Path(session.workspace_path).iterdir():
                if entry.name in {'runs', 'downloads', 'reports', '.git', '.opencode',
                                  'opencode.json', '.venv', '.dependency-install.lock',
                                  'dependency-install.log'} or entry.is_symlink():
                    continue
                if entry.is_dir():
                    shutil.copytree(entry, snapshot / entry.name,
                                    ignore=shutil.ignore_patterns('__pycache__', '.venv', 'node_modules'), symlinks=True)
                else:
                    shutil.copy2(entry, snapshot / entry.name)
        copying = asyncio.create_task(asyncio.to_thread(copy))
        try:
            await asyncio.shield(copying)
        except asyncio.CancelledError:
            await copying
            raise
        yield snapshot


def numeric_metrics(value: dict, prefix: str = "") -> dict[str, float]:
    """Keep split/aggregation names when experiments emit nested metrics."""
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            result.update(numeric_metrics(item, name))
        elif (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
        ):
            result[name] = float(item)
    return result


def contained(root: Path, path: str) -> Path:
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Path must be inside this research workspace")
    return target


def python_command(root: Path, command: list[str]) -> list[str]:
    if command[0] in {"python", "python3"} and (root / ".venv/pyvenv.cfg").is_file():
        return [str(root / ".venv/bin/python"), *command[1:]]
    return command


# Longest run that may carry debug-only GPU settings.
DEBUG_RUN_SECONDS = 1800


async def submit(session_id: str, kind: str, payload: dict) -> dict:
    if kind not in {"experiment", "computation", "download"}:
        raise ValueError("Unsupported research job kind")
    payload = {**payload, "device": payload.get("device", "gpu" if kind == "experiment" else "cpu")}
    if kind == 'download':
        from .acquisition_contract import AcquisitionRecord
        payload['record'] = AcquisitionRecord.model_validate(payload['record']).model_dump()
    job_id = "research_" + uuid4().hex[:20]
    session = await store.get(session_id)
    if session.status not in {"running", "waiting", "queued"}:
        raise ValueError("Research is not accepting new jobs")
    if (session.recovery_metadata or {}).get('delete_requested'):
        raise ValueError('Research was deleted')
    if kind == 'experiment' and (session.recovery_metadata or {}).get('task_kind') in {'analysis','document'}:
        raise ValueError('This task is analysis/document-only. Use submit_computation. Change scope with set_task_scope only if the user requested new training experiments.')
    if kind == 'experiment':
        from .study import experiment_config
        payload['config'] = experiment_config(session, payload.get('config') or {})
    from .budget import expired

    if expired(session) or (session.recovery_metadata or {}).get("budget_shutdown"):
        raise ValueError("Time budget reached; save progress and request_help(reason='budget').")
    if kind == "experiment" and session.current_iteration >= session.max_iterations:
        await store.update(session_id, meta={"budget_stop_requested": "experiments"})
        raise ValueError("Experiment budget reached. Save results and draft, then request_help(reason='budget'). The user can add attempts and continue this same session.")
    if kind == "experiment":
        await store.update(session_id, phase="experiment", meta={"research_phase": "experiment"},
            event={"kind": "phase", "phase": "experiment"})
    if kind != 'download' and payload['device'] == 'gpu':
        if container_backend.backend() == 'docker' and sys.platform == 'darwin':
            raise ValueError('Apple MPS is available to built-in native training, not Docker. Submit sandbox experiments with device=cpu.')
        from backend.common.gpu_resources import GpuWorkload, estimate_gpu
        if not payload.get('resources'):
            raise ValueError('GPU jobs require resources: operation, model, batch_size and input dimensions; custom code also needs peak_vram_mb. Use device=cpu for CPU-only work.')
        resource = GpuWorkload.model_validate(payload['resources'])
        payload = {**payload, 'resources': resource.model_dump(), 'gpu_estimate': estimate_gpu(resource).public()}
    if kind in {"experiment", "computation"}:
        command = payload.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(x, str) for x in command)
        ):
            raise ValueError("command must be a nonempty string argument array")
        payload = {
            **payload,
            "timeout": min(int(payload.get("timeout", 3600)), 259200),
        }
        if payload["timeout"] > DEBUG_RUN_SECONDS and any(
            token.startswith("CUDA_LAUNCH_BLOCKING=") and token != "CUDA_LAUNCH_BLOCKING=0"
            for token in command
        ):
            raise ValueError(
                "CUDA_LAUNCH_BLOCKING serializes every GPU kernel and makes training several times slower; "
                f"use it only in a short debug run (timeout <= {DEBUG_RUN_SECONDS}s) that locates a crash. "
                "PathLab already detects faulty GPUs and reruns affected jobs elsewhere. Remove it and resubmit."
            )
    async with staged_source(session, kind) as source:
        return await commit_submission(session_id, job_id, kind, payload, source)


async def commit_submission(session_id, job_id, kind, payload, source):
    from .budget import expired
    from .study import experiment_config, validate_submission
    async with safe_session() as db:
        locked = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if locked is None or locked.status not in {"queued", "running", "waiting"} or (locked.recovery_metadata or {}).get('delete_requested'):
            raise ValueError("Research has been paused or stopped")
        if kind == 'experiment':
            payload['config'] = experiment_config(locked, payload['config'])
            previous = (await db.scalars(select(ResearchJob).where(
                ResearchJob.session_id == session_id))).all()
            validate_submission(locked, payload, [
                {'job_id': j.job_id, 'kind': j.kind, 'status': j.status, 'payload': j.payload, 'result': j.result}
                for j in previous])
        if expired(locked) or (locked.recovery_metadata or {}).get("budget_shutdown"):
            raise ValueError("Time budget reached; checkpoint and resume with added time.")
        if kind == "experiment" and locked.current_iteration >= locked.max_iterations:
            locked.recovery_metadata = {**(locked.recovery_metadata or {}), "budget_stop_requested": "experiments"}
            await db.commit()
            raise ValueError(
                "Experiment budget reached; save your draft and request_help(reason='budget'). Continue with added attempts."
            )
        if source is not None:
            from .study import current_protocol, scientific
            if kind == 'experiment' and scientific(locked):
                from types import SimpleNamespace
                current_protocol(SimpleNamespace(workspace_path=str(source), recovery_metadata=locked.recovery_metadata))
            snapshot = Path(locked.workspace_path) / 'runs' / job_id / 'source'
            snapshot.parent.mkdir(parents=True)
            os.replace(source, snapshot)
            payload = {**payload, 'source': str(snapshot)}
        if kind == 'experiment':
            locked.current_iteration += 1
            meta = dict(locked.recovery_metadata or {})
            store.invalidate_study_review(meta)
            locked.recovery_metadata = meta
            db.add(
                AutoResearchExperiment(
                    session_id=session_id,
                    training_task_id=job_id,
                    experiment_name=payload.get("name", job_id),
                    dataset_id=payload.get("dataset_id"),
                    hyperparams=payload,
                    status="queued",
                    iteration=locked.current_iteration,
                )
            )
        db.add(
            ResearchJob(
                job_id=job_id,
                session_id=session_id,
                kind=kind,
                status="queued",
                payload=payload,
                result={},
            )
        )
        await db.commit()
    try:
        await enqueue_task_descriptor(
            build_task_descriptor(
                job_id, "research", "research.run", {"task_id": job_id}
            )
        )
    except Exception as exc:  # noqa: BLE001 -- committed jobs must survive any publisher failure.
        # Durable queued rows are redispatched by the Worker recovery loop.
        log.warning("Research job %s awaits redispatch: %s", job_id, exc)
    await store.update(
        session_id,
        event={
            "kind": "job",
            "job_id": job_id,
            "job_kind": kind,
            "status": "queued",
            "name": payload.get("name", ""),
        },
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Job accepted into the shared task queue. GPU work waits automatically for its memory reservation and concurrency slot; a busy GPU is not a failed experiment. Tell the user it is queued, end your turn, and do not submit duplicates. Results will wake the session.",
    }


async def cancel(job_id: str):
    async with safe_session() as db:
        job = await db.get(ResearchJob, job_id, with_for_update=True)
        if job is None or job.status not in {"queued", "running", "cancelling"}:
            return
        status = "cancelling" if job.status in {'running', 'cancelling'} else "cancelled"
        job.status = status
        await db.commit()
    await store.update(
        job.session_id, event={"kind": "job", "job_id": job_id, "status": status}
    )
    if job.kind == "experiment":
        await store.experiment_update(job.session_id, job_id, status=status)
    await publish_task_cancellation(job_id)


async def run(*, task_id: str, assigned_device: str = "cpu", **_kwargs):
    job = None
    try:
        async with safe_session() as db:
            job = await db.get(ResearchJob, task_id)
            if job is None or job.status != "queued":
                return
            session = await db.scalar(
                select(AutoResearchSession).where(
                    AutoResearchSession.session_id == job.session_id
                ).with_for_update()
            )
            if session is None or session.status in {'stopping', 'interrupted'} or (session.recovery_metadata or {}).get('delete_requested'):
                job.status = 'cancelled'
                await db.commit()
                return
            await db.refresh(job, with_for_update=True)
            if job.status != 'queued':
                return
            job.status = "running"
            await db.commit()
        await store.job_update(task_id, "running")
        from .datasets import validate_access

        await validate_access(session)
        async with safe_session() as db:
            current = await db.get(ResearchJob, task_id)
            if current is None or current.status in {"cancelling", "cancelled"}:
                raise asyncio.CancelledError()
        if job.kind == "download":
            result = await execute_download(session, job)
        else:
            result = await execute_experiment(session, job, assigned_device)
            if job.kind == "experiment":
                confirm_device_faults(job, assigned_device)
        async with safe_session() as db:
            current = await db.get(ResearchJob, task_id)
            if current is None or current.status in {"cancelling", "cancelled"}:
                raise asyncio.CancelledError()
        await store.job_update(task_id, "completed", result)
    except asyncio.CancelledError as exc:
        if job is None:
            raise
        # Worker shutdown requeues the same frozen job; it is not a user cancel
        # and must neither consume another attempt nor discard its checkpoints.
        status = 'queued' if is_restart_interruption(exc) else 'cancelled'
        await store.job_update(task_id, status)
        if job.kind == "experiment":
            await store.experiment_update(job.session_id, task_id, status=status)
        raise
    except Exception as exc:
        if job is None:
            raise
        error = str(exc)
        if job.kind == "experiment" and assigned_device.startswith("cuda:"):
            error = await handle_device_fault(job, assigned_device, error)
            if error is None:
                return
        result = {"error": error}
        await store.job_update(task_id, "failed", result)
        if job.kind == "experiment":
            await store.experiment_update(
                job.session_id, task_id, status="failed", metrics=result
            )
        log.exception("Research job %s failed", task_id)


CUDA_OUTAGE_NOTICE = (
    "CUDA outage on this machine: new processes cannot initialize CUDA on any GPU (a GPU "
    "failed at the driver level and an operator must reset or unbind it). The unchanged run "
    "was requeued and starts automatically once CUDA initializes again; waiting for a GPU "
    "does not consume the time budget. Do not change its code, resubmit it, move it to CPU "
    "or request help for this: end your turn."
)


async def handle_device_fault(job, assigned_device: str, error: str) -> str | None:
    """Requeue a run that hit a CUDA device fault; return None once requeued.

    CUDA that cannot initialize in any new process is a machine outage: dispatch
    pauses and the run waits without counting a fault. The same device fault
    comes from faulty GPUs and from out-of-range kernels in the run. A failing
    stress probe convicts the GPU. Faults that a short probe cannot reproduce
    move the unchanged run to another GPU; only a fault there too is attributed
    to the run.
    """
    from backend.common.gpu_utils import (
        cuda_initializes,
        is_cuda_init_failure,
        is_device_fault,
        sandbox_visible_device,
        stress_probe,
    )
    from task_worker.task_queue import get_task_queue

    queue = get_task_queue()
    faults = job.payload.get("device_faults", [])
    init_failure = is_cuda_init_failure(error)
    if init_failure and not await asyncio.to_thread(cuda_initializes):
        queue.pause_for_cuda_outage()
        log.error("Job %s hit a machine-wide CUDA outage; requeued until CUDA initializes", job.job_id)
        return await requeue_after_fault(job, faults, CUDA_OUTAGE_NOTICE, error)
    if not (init_failure or is_device_fault(error)):
        return error
    index = int(assigned_device.split(":")[-1])
    faulty = not await asyncio.to_thread(stress_probe, sandbox_visible_device(index))
    if faulty:
        queue.mark_gpu_bad(index)
        log.error("GPU %s failed its stress probe after job %s; excluded from scheduling", assigned_device, job.job_id)
    devices = ", ".join(dict.fromkeys([*faults, assigned_device]))
    if not faulty and any(device != assigned_device for device in faults):
        return (
            f"{error}\n[PathLab] This unchanged run hit CUDA device faults on {devices}, and stress "
            "workloads pass on them, so the fault comes from the run itself (for example an "
            "out-of-range index). Locate the failing operation in a short debug run "
            f"(timeout <= {DEBUG_RUN_SECONDS}s) with CUDA_LAUNCH_BLOCKING=1."
        )
    if len(faults) >= MAX_DEVICE_RETRIES:
        return f"{error}\n[PathLab] Device retries are exhausted after CUDA device faults on {devices}."
    queue.avoid_gpu(job.job_id, index)
    verdict = (
        "failed a hardware stress probe and is excluded from scheduling"
        if faulty
        else "passes a short stress probe, so the unchanged run is repeated on another GPU "
        "to tell a hardware fault from a fault in the run"
    )
    notice = (
        f"CUDA device fault on {assigned_device}: the GPU {verdict}. "
        "The run was requeued automatically; do not change its code or move it to CPU for this."
    )
    return await requeue_after_fault(job, [*faults, assigned_device], notice, error)


async def requeue_after_fault(job, faults: list[str], notice: str, error: str) -> str | None:
    async with safe_session() as db:
        current = await db.get(ResearchJob, job.job_id, with_for_update=True)
        if current is None or current.status != "running":
            return error
        current.payload = {**current.payload, "device_faults": faults}
        await db.commit()
    await store.job_update(job.job_id, "queued", {"device_fault": notice})
    await store.experiment_update(job.session_id, job.job_id, status="queued")
    return None


def confirm_device_faults(job, assigned_device: str):
    """An unchanged run that faulted on other GPUs and then completed proves them faulty."""
    from task_worker.task_queue import get_task_queue

    for device in dict.fromkeys(job.payload.get("device_faults", [])):
        if device != assigned_device:
            get_task_queue().mark_gpu_bad(int(device.split(":")[-1]))
            log.error("GPU %s faulted on job %s, which then completed on %s; excluded from scheduling",
                      device, job.job_id, assigned_device)


async def execute_experiment(session, job, assigned_device: str) -> dict:
    root = Path(session.workspace_path)
    run_root = root / "runs" / job.job_id
    output = run_root / "output"
    output.mkdir(exist_ok=True)
    source = Path(job.payload["source"])
    meta = session.recovery_metadata or {}
    from backend.common.gpu_utils import sandbox_visible_device
    gpu = sandbox_visible_device(int(assigned_device.split(':')[-1])) if assigned_device.startswith('cuda:') else None
    cmd = sandbox_command(root, meta.get("data_mounts", {}), gpu=gpu)
    cmd[cmd.index(f"{root}:{root}:rw")] = f"{root}:{root}:ro"
    image = cmd.pop()
    cmd += ["--bind", f"{output}:{output}:rw", image]
    # --pwd must address the frozen source, while the full workspace remains available.
    cmd[cmd.index("--pwd") + 1] = str(source)
    execution_command = python_command(root, job.payload["command"])
    cmd += execution_command
    values = {
        **skill_environment(),
        "OUTPUT_DIR": str(output),
        "PATHLAB_WORKSPACE": str(root),
        "PATHLAB_DEVICE": "cuda:0" if gpu else "cpu",
        "CUDA_VISIBLE_DEVICES": gpu or "",
        "PYTHONUNBUFFERED": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "PYTHONPATH": "/opt/pathlab/templates",
    }
    from backend.common.config import Config

    values["PATHLAB_CKPT_DIR"] = str(Config.get_uploads_dir() / "extractor_checkpoints")
    values["HF_HOME"] = os.getenv("HF_HOME", str(Path.home() / ".cache/huggingface"))
    values["TORCH_HOME"] = str(Path.home() / ".cache/torch")
    values["HF_TOKEN"] = Config.get_global_settings().get("huggingface_token", "")
    (run_root / "execution.json").write_text(
        json.dumps(
            {
                "command": execution_command,
                "source": str(source),
                "device": assigned_device,
                "image": image,
                "dataset_id": job.payload.get("dataset_id"),
                "config": job.payload.get("config", {}),
            },
            indent=2,
        )
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
    }
    env.update({f"APPTAINERENV_{k}": v for k, v in values.items()})
    cmd, env, container = container_backend.prepare(cmd, env, name='pathlab-job-' + job.job_id)
    log_path = run_root / "run.log"
    if job.kind == "experiment":
        await store.experiment_update(session.session_id, job.job_id, status="running")
    with log_path.open("ab") as log:
        process = await spawn_owned(session.session_id, run_root / 'process.json', cmd, job_id=job.job_id,
                                    env=env, stdout=log, stderr=log, record_data={'source': str(source), 'container': container})
        started = time.monotonic()
        last_progress = ""
        try:
            if gpu is not None:
                from task_worker.task_queue import get_task_queue
                get_task_queue().bind_gpu_process(job.job_id, process.pid, process_group=True)
            while process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 2)
                except TimeoutError:
                    pass
                async with safe_session() as db:
                    current = await db.get(ResearchJob, job.job_id)
                    if current is None or current.status in {"cancelled", "cancelling"}:
                        raise asyncio.CancelledError()
                if time.monotonic() - started > job.payload["timeout"]:
                    raise TimeoutError("Experiment exceeded its time budget")
                progress_path = output / "progress.json"
                if progress_path.exists():
                    try:
                        text = progress_path.read_text()
                        if text != last_progress:
                            progress = json.loads(text)
                            await store.update(
                                session.session_id,
                                event={
                                    "kind": "progress",
                                    "run_id": job.job_id,
                                    "progress": progress,
                                },
                            )
                            last_progress = text
                    except (OSError, ValueError):
                        pass
        finally:
            await stop_owned(run_root / 'process.json')
            await process.wait()
            (run_root / "process.json").unlink(missing_ok=True)
    if process.returncode != 0:
        raise RuntimeError(
            f"Exit {process.returncode}: {log_path.read_text(errors='replace')[-6000:]}"
        )
    metrics = {}
    metric_path = output / "metrics.json"
    if metric_path.exists():
        raw = json.loads(metric_path.read_text())
        metrics = numeric_metrics(raw)
    measurement = None
    if job.kind == 'experiment' and job.payload.get('config', {}).get('study_revision'):
        from .study import read_measurement
        measurement = read_measurement(output, job.payload['config'], metrics)
    from .file_catalog import index_tree
    catalog = await index_tree(session, output)
    artifacts = catalog["items"]
    result = {
        "metrics": metrics,
        "artifacts": artifacts,
        "artifact_count": catalog["count"],
        "artifact_directory": str(output.relative_to(root)),
        "artifact_index_truncated": catalog['truncated'],
        "log_path": str(log_path.relative_to(root)),
        "duration_seconds": round(time.monotonic() - started, 2),
        "device": assigned_device,
        "finished_at": time.time(),
    }
    if job.kind == "experiment":
        fields = {}
        if measurement is not None:
            fields['hyperparams'] = {**job.payload, 'config': {
                **job.payload['config'], 'study_measurement': measurement}}
        await store.experiment_update(
            session.session_id, job.job_id, status="completed", metrics=metrics, **fields
        )
    await store.update(
        session.session_id,
        event={"kind": "artifacts", "run_id": job.job_id, "artifacts": artifacts},
    )
    return result


async def execute_download(session, job) -> dict:
    root = Path(session.workspace_path) / "downloads"
    root.mkdir(exist_ok=True)
    result_path = root / f"{job.job_id}.result.json"
    log_path = root / f"{job.job_id}.log"
    with log_path.open("ab") as log:
        process_file = root / f"{job.job_id}.process.json"
        process = await spawn_owned(session.session_id, process_file,
                                    [sys.executable, '-m', 'backend.autoresearch.engine.download_job', job.job_id],
                                    job_id=job.job_id, stdout=log, stderr=log)
        last = ""
        started = time.monotonic()
        timeout = int(
            (session.recovery_metadata or {}).get("time_budget_seconds", 14400)
        )
        try:
            while process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 1)
                except TimeoutError:
                    pass
                async with safe_session() as db:
                    current = await db.get(ResearchJob, job.job_id)
                if current is None or current.status in {"cancelled", "cancelling"}:
                    raise asyncio.CancelledError()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(
                        "Dataset download exceeded the research time budget"
                    )
                progress_file = root / f"{job.job_id}.json"
                if progress_file.exists():
                    try:
                        value = progress_file.read_text()
                        if value != last:
                            await store.update(
                                session.session_id,
                                event={
                                    "kind": "download_progress",
                                    "job_id": job.job_id,
                                    "progress": json.loads(value),
                                },
                            )
                            last = value
                    except (ValueError, OSError):
                        pass
        finally:
            await stop_owned(process_file)
            await process.wait()
            process_file.unlink(missing_ok=True)
    if process.returncode != 0:
        raise RuntimeError(log_path.read_text(errors="replace")[-4000:])
    return json.loads(result_path.read_text())


async def redispatch_pending():
    """Repair a committed job whose initial Redis publication failed."""
    from datetime import timedelta

    from backend.database.models import utc_now
    from task_worker.task_queue import get_task_queue

    async with safe_session() as db:
        rows = list(
            (
                await db.scalars(
                    select(ResearchJob).where(
                        ResearchJob.status == "queued",
                        ResearchJob.updated_at < utc_now() - timedelta(seconds=30),
                    ).order_by(ResearchJob.created_at, ResearchJob.job_id)
                )
            ).all()
        )
    for job in rows:
        if get_task_queue().is_task_in_queue(job.job_id):
            continue
        await enqueue_task_descriptor(
            build_task_descriptor(
                job.job_id, "research", "research.run", {"task_id": job.job_id}
            )
        )


async def recover():
    async with safe_session() as db:
        rows = list(
            (
                await db.scalars(
                    select(ResearchJob).where(ResearchJob.status.in_(store.ACTIVE_JOBS))
                )
            ).all()
        )
    async def restore(job):
        session = await store.get(job.session_id)
        cancelled = job.status == 'cancelling' or session.status in {'stopping', 'interrupted'} or (session.recovery_metadata or {}).get('delete_requested')
        if job.status in {"running", "cancelling"}:
            root = Path(session.workspace_path)
            process_file = (
                root / "runs" / job.job_id / "process.json"
                if job.kind != "download"
                else root / "downloads" / f"{job.job_id}.process.json"
            )
            if process_file.exists():
                await stop_owned(process_file)
                process_file.unlink(missing_ok=True)
            status = 'cancelled' if cancelled else 'queued'
            await store.job_update(
                job.job_id,
                status,
                {
                    'recovery': 'worker_restart',
                    'message': 'Resuming the saved job after worker restart; existing output and checkpoints are retained.',
                },
            )
            if job.kind == "experiment":
                await store.experiment_update(job.session_id, job.job_id, status=status)
        elif cancelled:
            await store.job_update(job.job_id, 'cancelled')
            if job.kind == 'experiment':
                await store.experiment_update(job.session_id, job.job_id, status='cancelled')
        if not cancelled:
            await enqueue_task_descriptor(
                build_task_descriptor(
                    job.job_id, "research", "research.run", {"task_id": job.job_id}
                )
            )
    await recover_fifo(rows, key=lambda job: fifo_key(job.created_at, job.job_id), restore=restore)
