"""Single fair GPU lease scheduler for whole jobs and training pipeline stages."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
CUDA_OUTAGE_RECHECK_SECONDS = 60.0


@dataclass
class Request:
    task_id: str
    stage: str
    required_mb: float
    future: asyncio.Future
    created_at: float = field(default_factory=time.monotonic)
    bypasses: int = 0
    gpu: int | None = None
    pid: int | None = None
    process_group: bool = False
    drain_gpu: int | None = None
    device: str | None = None


class GpuScheduler:
    def __init__(
        self,
        snapshot: Callable,
        process_memory: Callable,
        limit=1,
        interval=2.0,
        cuda_check: Callable[[], bool] = lambda: True,
    ):
        self.snapshot = snapshot
        self.cuda_check = cuda_check
        # Set while new processes cannot initialize CUDA: nothing is dispatched.
        self.cuda_outage_since: float | None = None
        self.process_memory = process_memory
        self.limit = limit
        self.interval = interval
        self.pending: dict[tuple[str, str], Request] = {}
        self.leases: dict[tuple[str, str], Request] = {}
        self.bad_gpus: set[int] = set()
        # GPUs a task must not return to, e.g. after a device fault there.
        self.avoid: dict[str, set[int]] = {}
        self.changed = asyncio.Event()
        self.worker: asyncio.Task | None = None
        self.stopped = False
        self.last_processes: dict[int, dict[int, float]] = {}
        self.baselines: dict[tuple[int, int, bool], float] = {}
        self.devices: list[dict] = []

    def start(self):
        if self.worker is None:
            self.stopped = False
            self.worker = asyncio.create_task(self._loop())

    async def stop(self):
        self.stopped = True
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        for request in self.pending.values():
            request.future.cancel()
        self.pending.clear()
        self.leases.clear()
        self.baselines.clear()
        self.devices = []

    async def acquire(self, task_id: str, stage: str, required_mb: float) -> str:
        if self.stopped:
            raise asyncio.CancelledError("GPU scheduler stopped")
        if not math.isfinite(required_mb) or required_mb <= 0:
            raise ValueError("GPU reservation must be a finite positive MiB value")
        key = task_id, stage
        if any(
            r.task_id == task_id
            for r in [*self.pending.values(), *self.leases.values()]
        ):
            raise ValueError("Release the current GPU stage before acquiring another")
        request = Request(
            task_id, stage, required_mb, asyncio.get_running_loop().create_future()
        )
        self.pending[key] = request
        self.start()
        self.changed.set()
        try:
            gpu = await request.future
            return request.device or f"cuda:{gpu}"
        except BaseException:
            self.pending.pop(key, None)
            self.leases.pop(key, None)
            self._clear_baselines()
            self.changed.set()
            raise

    def pause_for_cuda_outage(self):
        """Hold every dispatch until new processes can initialize CUDA again."""
        if self.cuda_outage_since is None:
            self.cuda_outage_since = time.monotonic()
            logger.error("CUDA cannot initialize in new processes; GPU dispatch paused")
        self.changed.set()

    async def _cuda_recovered(self) -> bool:
        if not await asyncio.to_thread(self.cuda_check):
            return False
        logger.warning(
            "CUDA initializes again after %.0fs; GPU dispatch resumed",
            time.monotonic() - (self.cuda_outage_since or time.monotonic()),
        )
        self.cuda_outage_since = None
        return True

    def release(self, task_id: str, stage: str):
        self._retire_lease((task_id, stage))
        self._clear_baselines()
        self.changed.set()

    def release_task(self, task_id: str):
        for key, request in list(self.pending.items()):
            if request.task_id == task_id:
                self.pending.pop(key)
                request.future.cancel()
        for key in list(self.leases):
            if key[0] == task_id:
                self._retire_lease(key)
        self._clear_baselines()
        self.changed.set()

    def _retire_lease(self, key):
        lease = self.leases.pop(key, None)
        if lease and lease.pid is not None and not lease.process_group:
            group = lease.gpu, lease.pid, False
            # Recently finished allocations can still be cached in a shared
            # service. They must not be credited to a different starting job.
            if any(
                (other.gpu, other.pid, other.process_group) == group
                for other in self.leases.values()
            ):
                baseline = self.baselines.get(group, 0)
                actual = self.last_processes.get(lease.gpu, {}).get(lease.pid, 0)
                self.baselines[group] = baseline + min(
                    lease.required_mb, max(0, actual - baseline)
                )

    def bind_process(self, task_id: str, pid: int, *, process_group=False):
        for request in self.leases.values():
            if request.task_id == task_id:
                request.pid, request.process_group = pid, process_group
                key = request.gpu, pid, process_group
                if key not in self.baselines:
                    self.baselines[key] = (
                        0
                        if process_group
                        else self.last_processes.get(request.gpu, {}).get(pid, 0)
                    )

    def _clear_baselines(self):
        active = {(r.gpu, r.pid, r.process_group) for r in self.leases.values()}
        self.baselines = {
            key: value for key, value in self.baselines.items() if key in active
        }

    def effective_free(self, gpu: dict, processes: dict[int, float]) -> float:
        # NVML free already excludes allocated memory. Withhold only the part
        # of our peak commitments not visible in their actual owning processes.
        # Shared AI-service leases aggregate by PID to avoid crediting it twice.
        groups: dict[tuple[int | None, bool], float] = {}
        for lease in self.leases.values():
            if lease.gpu == gpu["index"]:
                key = lease.pid, lease.process_group
                groups[key] = groups.get(key, 0) + lease.required_mb
        withheld = 0.0
        credited = set()
        for (pid, is_group), budget in groups.items():
            actual = 0.0
            if pid is not None:
                for process, memory in processes.items():
                    if process in credited:
                        continue
                    try:
                        matches = (
                            os.getpgid(process) == pid if is_group else process == pid
                        )
                    except (OSError, AttributeError):
                        matches = False
                    if matches:
                        credited.add(process)
                        actual += memory
            baseline = self.baselines.get((gpu["index"], pid, is_group), 0)
            withheld += max(0.0, budget - max(0.0, actual - baseline))
        return max(0.0, float(gpu["free_mb"]) - withheld)

    def dispatch(self, gpus: list[dict], processes: dict[int, dict[int, float]]):
        self.last_processes = processes
        healthy = [
            gpu
            for gpu in gpus
            if gpu["index"] not in self.bad_gpus
            and math.isfinite(float(gpu.get("total_mb", 0)))
            and float(gpu.get("total_mb", 0)) > 0
            and math.isfinite(float(gpu.get("free_mb", 0)))
            and float(gpu.get("free_mb", 0)) >= 0
        ]
        self.devices = healthy
        # A failed telemetry read is never permission to launch on GPU zero.
        if not healthy:
            return
        capacity = max(float(gpu["total_mb"]) for gpu in healthy)
        for key, request in list(self.pending.items()):
            if request.future.cancelled():
                self.pending.pop(key)
            elif request.required_mb > capacity:
                self.pending.pop(key)
                request.future.set_exception(
                    ValueError(
                        f"GPU stage {request.stage} requires {request.required_mb:.0f} MiB; "
                        f"largest healthy GPU has {capacity:.0f} MiB. Reduce batch/input size or provide a measured peak."
                    )
                )
        blocked_gpu = None
        older: list[Request] = []
        for key, request in list(self.pending.items()):
            if len(self.leases) >= self.limit:
                break
            allowed = [
                gpu for gpu in healthy
                if gpu["index"] not in self.avoid.get(request.task_id, ())
            ] or healthy
            candidates = [
                (self.effective_free(gpu, processes.get(gpu["index"], {})), gpu)
                for gpu in allowed
                if gpu["index"] != blocked_gpu
            ]
            fits = [
                (free, gpu) for free, gpu in candidates if free >= request.required_mb
            ]
            if fits:
                # Preserve larger-capacity devices, but among equal-sized GPUs
                # choose the most headroom, not the busiest barely-fitting card.
                _, gpu = min(
                    fits,
                    key=lambda pair: (pair[1]['total_mb'], -pair[0], pair[1]['index']),
                )
                self.pending.pop(key)
                request.gpu = gpu["index"]
                request.device = gpu.get('device', f'cuda:{request.gpu}')
                self.leases[key] = request
                for waiting in older:
                    waiting.bypasses += 1
                    if waiting.bypasses >= 3 and blocked_gpu is None:
                        eligible = [
                            g for g in healthy if g["total_mb"] >= waiting.required_mb
                        ]
                        if eligible:
                            waiting.drain_gpu = (
                                waiting.drain_gpu
                                if any(
                                    g["index"] == waiting.drain_gpu for g in eligible
                                )
                                else max(
                                    eligible,
                                    key=lambda g: self.effective_free(
                                        g, processes.get(g["index"], {})
                                    ),
                                )["index"]
                            )
                            blocked_gpu = waiting.drain_gpu
                request.future.set_result(request.gpu)
            else:
                older.append(request)
                if blocked_gpu is None and (
                    request.bypasses >= 3 or time.monotonic() - request.created_at >= 60
                ):
                    eligible = [
                        gpu for gpu in healthy if gpu["total_mb"] >= request.required_mb
                    ]
                    if eligible:
                        # Drain one capable GPU for the oldest blocked job while
                        # allowing unrelated devices to keep doing useful work.
                        if not any(
                            gpu["index"] == request.drain_gpu for gpu in eligible
                        ):
                            request.drain_gpu = max(
                                eligible,
                                key=lambda gpu: self.effective_free(
                                    gpu, processes.get(gpu["index"], {})
                                ),
                            )["index"]
                        blocked_gpu = request.drain_gpu

    async def _loop(self):
        while True:
            self.changed.clear()
            try:
                if self.cuda_outage_since is not None and not await self._cuda_recovered():
                    self.devices = []
                    await asyncio.sleep(CUDA_OUTAGE_RECHECK_SECONDS)
                    continue
                processes, gpus = await asyncio.to_thread(
                    lambda: (self.process_memory(), self.snapshot())
                )
                self.dispatch(gpus, processes)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Telemetry failure keeps requests pending; next tick retries.
                self.devices = []
                logger.exception("GPU telemetry unavailable")
            try:
                await asyncio.wait_for(self.changed.wait(), self.interval)
            except TimeoutError:
                pass

    def details(self) -> dict:
        positions = {key: index + 1 for index, key in enumerate(self.pending)}
        waiting_for = (
            "cuda_outage" if self.cuda_outage_since is not None
            else "capacity" if len(self.leases) >= self.limit
            else "memory"
        )
        return {
            f"{r.task_id}:{r.stage}": {
                "task_id": r.task_id,
                "stage": r.stage,
                "state": "running" if r.gpu is not None else "waiting",
                "gpu": r.gpu,
                "device": r.device or (f"cuda:{r.gpu}" if r.gpu is not None else None),
                "position": positions.get((r.task_id, r.stage), 0),
                "reason": waiting_for,
                "required_vram_mb": r.required_mb,
                "wait_seconds": round(time.monotonic() - r.created_at, 1),
            }
            for r in [*self.leases.values(), *self.pending.values()]
        }

    def capacity(self) -> list[dict]:
        return [
            {'device': gpu.get('device', f'cuda:{gpu["index"]}'),
             'total_mb': round(gpu['total_mb']), 'free_mb': round(gpu['free_mb']),
             'available_mb': round(self.effective_free(gpu, self.last_processes.get(gpu['index'], {})))}
            for gpu in self.devices if gpu['index'] not in self.bad_gpus
        ]
