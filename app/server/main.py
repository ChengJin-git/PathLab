from typing import Any

"""
PathLab Python Backend - Unified Entry Point

Main entry point for the browser/server (B/S) web application backend, started by
the deploy scripts or the systemd unit.

It launches three HTTP services and two background workers:
- Gateway (6100) - Main API gateway
- Preprocessing (6101) - WSI processing, tile serving
- AI (6102) - Model training and inference
- TaskWorker - Background task execution
- ResearchWorker - OpenCode research supervision

Ports come from GATEWAY_PORT, PREPROCESSING_PORT and AI_PORT (defaults 6100,
6101, 6102); nginx proxies the browser to them.
"""

import os
import sys
import signal
import atexit
import multiprocessing
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

if __name__ == '__main__' and '--pdf-worker' in sys.argv:
    sys.argv.remove('--pdf-worker')
    from backend.services.pdf_cpu import main as pdf_worker
    pdf_worker()
    raise SystemExit(0)

from backend.common.config import Config


def service_process(*, target, name, args=(), daemon=False):
    return multiprocessing.Process(target=target, name=name, args=args, daemon=daemon)


def _detect_and_exclude_bad_gpus() -> list[int]:
    # If operator has already configured CUDA_VISIBLE_DEVICES (e.g. via server/.env),
    # respect it unconditionally — do not overwrite with auto-detected healthy list.
    existing_cvd = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if existing_cvd:
        print(
            f"[GPUCheck] CUDA_VISIBLE_DEVICES already set to '{existing_cvd}' "
            f"— respecting operator config, skipping auto-exclusion.",
            flush=True,
        )
        return []

    # CUDA_VISIBLE_DEVICES only takes effect when cuInit() itself succeeds.
    # If a faulty GPU poisons cuInit(), the operator must first unbind it at the
    # driver level (requires root) before restarting this process:
    #   sudo bash -c 'echo <pci_addr> > /sys/bus/pci/drivers/nvidia/unbind'
    try:
        import pynvml

        pynvml.nvmlInit()
        num_gpus = pynvml.nvmlDeviceGetCount()
    except Exception as e:
        print(
            f"[GPUCheck] pynvml unavailable ({e}), skipping GPU health probe",
            flush=True,
        )
        return []

    healthy: list[int] = []
    bad: list[int] = []
    for i in range(num_gpus):
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            healthy.append(i)
            print(f"[GPUCheck]   GPU {i} ({name}): OK", flush=True)
        except Exception as e:
            bad.append(i)
            print(f"[GPUCheck]   GPU {i}: FAILED — {e}", flush=True)

    if bad:
        print(
            f"[GPUCheck] Detected {len(bad)} unhealthy GPU(s): {bad}. "
            f"Setting CUDA_VISIBLE_DEVICES to healthy GPUs: {healthy}",
            flush=True,
        )
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in healthy)
    else:
        print(f"[GPUCheck] All {num_gpus} GPU(s) passed health check.", flush=True)

    return bad


def run_task_worker():
    import asyncio
    from importlib import import_module

    task_worker_main = import_module("task_worker.main").main

    print("[TaskWorker] Starting background task worker...", flush=True)
    asyncio.run(task_worker_main())


def run_research_worker():
    import asyncio
    from backend.autoresearch.engine.worker import main as research_main
    asyncio.run(research_main())


def restart_failed_workers(processes):
    """Keep durable queue consumers alive without tearing down HTTP services."""
    targets = {'TaskWorker': run_task_worker, 'ResearchWorker': run_research_worker}
    for index, process in enumerate(processes):
        if process.name not in targets or process.exitcode is None:
            continue
        print(f'[Main] Restarting {process.name} after exit {process.exitcode}', flush=True)
        process.join(timeout=0)
        replacement = service_process(target=targets[process.name], name=process.name, daemon=False)
        replacement.start()
        processes[index] = replacement


def run_service(
    app_module: str,
    port: int,
    name: str,
    workers: int = 1,
    limit_max_requests: int | None = None,
):
    """Run a single uvicorn service in a subprocess"""
    import uvicorn

    extra = ""
    if limit_max_requests:
        extra = f", limit_max_requests={limit_max_requests}"
    print(
        f"[{name}] Starting on port {port} with {workers} worker(s){extra}...",
        flush=True,
    )

    kwargs: dict[str, Any] = dict[str, Any](
        host=os.environ.get("PATHLAB_BIND_HOST", "0.0.0.0"),
        port=port,
        log_level="info",
        reload=False,  # Disable reload in subprocess
        workers=workers,
    )
    if limit_max_requests:
        # Recycle workers after N requests to release accumulated C library memory.
        # This is the standard defence against memory leaks in native (C/C++) extensions
        # such as the SdpcSlide SDK which can leak internal decoder buffers.
        kwargs["limit_max_requests"] = limit_max_requests

    # uvicorn uses multiprocessing.get_context("spawn") for workers, which exec()s a
    # fresh interpreter that doesn't inherit fds. uvicorn/_subprocess.py passes
    # stdin_fileno to each worker, which calls os.fdopen(stdin_fileno) — if fd 0 is
    # not inheritable (common under nohup), every worker crashes with EBADF → 503.
    # Redirect fd 0 to /dev/null + mark inheritable; fall back to None so uvicorn
    # skips stdin setup entirely (it guards with `if stdin_fileno is not None`).
    try:
        fd = os.open(os.devnull, os.O_RDONLY)
        if fd != 0:
            os.dup2(fd, 0)
            os.close(fd)
        os.set_inheritable(0, True)
        sys.stdin = os.fdopen(0, "r", closefd=False)
    except Exception:
        sys.stdin = None

    uvicorn.run(app_module, **kwargs)


def main():
    """Main entry point for PathLab Python backend"""
    import secrets
    os.environ.setdefault('PATHLAB_INTERNAL_SECRET', secrets.token_urlsafe(48))

    main_pid = os.getpid()
    gateway_port = int(os.environ.get("GATEWAY_PORT", Config.DEFAULT_GATEWAY_PORT))
    preprocessing_port = int(
        os.environ.get("PREPROCESSING_PORT", Config.DEFAULT_PREPROCESSING_PORT)
    )
    ai_port = int(os.environ.get("AI_PORT", Config.DEFAULT_AI_PORT))

    # Set environment variables for service discovery
    Config.configure_service_ports(
        gateway=gateway_port, preprocessing=preprocessing_port, ai=ai_port
    )

    print(
        f"[Services] Gateway: {gateway_port}, Preprocessing: {preprocessing_port}, AI: {ai_port}, TaskWorker",
        flush=True,
    )

    _detect_and_exclude_bad_gpus()

    # Track child processes for cleanup
    processes = []

    def cleanup(signum=None, frame=None, from_atexit=False):
        """Cleanup all child processes on shutdown"""
        # Only main process should cleanup
        if os.getpid() != main_pid:
            return

        if not processes:
            return

        print("\n[Shutdown] Stopping all services...", flush=True)

        # Send SIGTERM to all processes first (parallel shutdown)
        for p in processes:
            if p.is_alive():
                print(f"[Shutdown] Terminating process {p.pid}...", flush=True)
                p.terminate()

        # Then wait for them to exit
        for p in processes:
            if p.is_alive():
                try:
                    p.join(timeout=10 if p.name in {"TaskWorker", "ResearchWorker"} else 2)
                except Exception:
                    pass

                if p.is_alive():
                    print(f"[Shutdown] Force killing process {p.pid}...", flush=True)
                    try:
                        p.kill()
                    except Exception:
                        pass

        processes.clear()
        print("[Shutdown] All services stopped", flush=True)

        if not from_atexit:
            sys.exit(0)

    # Register signal handlers and atexit for robust cleanup
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    atexit.register(lambda: cleanup(from_atexit=True))

    # Start Preprocessing service in subprocess
    # NOTE: daemon=False allows AI service to spawn DataLoader workers (num_workers > 0)
    # Daemon processes cannot have children due to Python multiprocessing restrictions
    # Preprocessing uses multiple workers to handle concurrent tile requests
    # Each worker owns its own SlideCacheManager; cached slide handles are not shared.
    preprocessing_workers = int(os.environ.get("PREPROCESSING_WORKERS", "4"))
    # Recycle preprocessing workers every 500 requests to release C library memory leaks
    # (SdpcSlide SDK accumulates internal buffers that are not fully freed on close).
    preprocessing_max_requests = int(
        os.environ.get("PREPROCESSING_MAX_REQUESTS", "500")
    )
    preprocessing_proc = service_process(
        target=run_service,
        name="Preprocessing",
        args=(
            "backend.preprocessing.main:app",
            preprocessing_port,
            "Preprocessing",
            preprocessing_workers,
            preprocessing_max_requests,
        ),
        daemon=False,
    )
    preprocessing_proc.start()
    processes.append(preprocessing_proc)

    # Start AI service in subprocess
    # NOTE: daemon=False is REQUIRED for PyTorch DataLoader with num_workers > 0
    # Otherwise: "AssertionError: daemonic processes are not allowed to have children"
    ai_proc = service_process(
        target=run_service,
        name="AI",
        args=("backend.ai.main:app", ai_port, "AI"),
        daemon=False,
    )
    ai_proc.start()
    processes.append(ai_proc)

    task_worker_proc = service_process(
        target=run_task_worker,
        name="TaskWorker",
        daemon=False,
    )
    task_worker_proc.start()
    processes.append(task_worker_proc)

    research_proc = service_process(target=run_research_worker, name="ResearchWorker", daemon=False)
    research_proc.start()
    processes.append(research_proc)

    # Start Gateway service in subprocess (instead of main process)
    # This keeps the main process free for signal handling
    gateway_proc = service_process(
        target=run_service,
        name="Gateway",
        args=("gateway.main:app", gateway_port, "Gateway"),
        daemon=False,
    )
    gateway_proc.start()
    processes.append(gateway_proc)

    # Main process loop just waits for signals
    print("[Main] Service processes launched; waiting for health checks...", flush=True)
    try:
        # Keep main process alive
        import time

        while True:
            restart_failed_workers(processes)
            failed = next((p for p in processes if p.exitcode is not None), None)
            if failed is not None:
                print(f'[Main] {failed.name} exited unexpectedly (code {failed.exitcode})', flush=True)
                cleanup(from_atexit=True)
                raise SystemExit(1)
            time.sleep(1)
    except KeyboardInterrupt:
        # This will be caught by signal handler usually, but explicit catch is safe
        cleanup()
    except Exception as e:
        print(f"[Main] Error: {e}")
        cleanup()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
