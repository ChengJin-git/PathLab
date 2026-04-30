"""Apptainer sandbox for isolated script execution with GPU passthrough.

Provides container-level isolation for LLM-generated training scripts.
Uses ephemeral `apptainer exec` — each run starts a fresh container process.

Requires: `module load apptainer` on HPC clusters.
"""
from __future__ import annotations

import logging
import os
import queue
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Apptainer binary — resolved once at import time.
_APPTAINER_BIN = os.getenv(
    "APPTAINER_BIN",
    "/cm/local/apps/apptainer/current/bin/apptainer",
)

# Default .sif image — co-located with auto_research_old
_DEFAULT_IMAGE = (
    os.getenv("PATHLAB_SANDBOX_IMAGE")
    or str(Path(__file__).resolve().parents[2] / "auto_research_old" / "pathlab-sandbox.sif")
)

# Patterns that signal a fatal error within the first N seconds.
# Compiled into a single regex so per-line matching is O(1) instead of O(patterns).
_EARLY_FAIL_PATTERNS = [
    "ModuleNotFoundError",
    "ImportError",
    "SyntaxError",
    "FileNotFoundError",
    "NameError",
    "IndentationError",
    "CUDA error",
    "RuntimeError: CUDA out of memory",
    "torch.cuda.OutOfMemoryError",
]
_EARLY_FAIL_REGEX = re.compile("|".join(re.escape(p) for p in _EARLY_FAIL_PATTERNS))
_EARLY_FAIL_WINDOW = 30  # seconds


@dataclass
class SandboxResult:
    """Structured result from a sandbox execution."""

    exit_code: int
    stdout: str
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    early_failed: bool = False


class ApptainerSandbox:
    """Run scripts inside an Apptainer container.

    Security model:
    - Rootless (runs as current user)
    - ``--no-home``: host home not mounted
    - ``--writable-tmpfs``: container writes go to tmpfs (ephemeral)
    - ``--nv``: GPU passthrough via nvidia-container-cli
    - Explicit bind mounts for workspace, output, data, and model caches
    """

    def __init__(
        self,
        image: str = "",
        gpu_ids: list[str] | None = None,
        memory_limit: str = "64G",
        cpus: str = "16",
    ):
        self.image = image or _DEFAULT_IMAGE
        self.gpu_ids = gpu_ids or ["0"]
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.apptainer = _APPTAINER_BIN
        self._cgroups_available = Path("/sys/fs/cgroup/cgroup.controllers").exists()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_script(
        self,
        script_path: str,
        workspace_dir: Path,
        output_dir: Path,
        env_vars: dict[str, str] | None = None,
        timeout: float = 600.0,
        data_mounts: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute a Python script inside the container.

        Args:
            script_path: Relative path within workspace_dir (e.g. "train.py").
            workspace_dir: Host path to the git-backed workspace (bind as rw).
            output_dir: Host path for experiment outputs (bind as rw).
            env_vars: Extra environment variables to inject.
            timeout: Wall-clock timeout in seconds.
            data_mounts: Optional ``host_path -> container_path`` map. Each
                entry becomes an additional ``--bind`` so prepared dataset
                roots from acquisition land at their declared container
                locations (e.g. ``prepared_root -> /data``).
        """
        cmd = self._build_exec_cmd(workspace_dir, output_dir, data_mounts=data_mounts)
        cmd.extend([self.image, "bash", "-c", f"cd {workspace_dir} && python {script_path}"])
        env = self._build_env(env_vars)

        logger.info(
            f"[sandbox] apptainer exec: {script_path} "
            f"(gpu={self.gpu_ids}, timeout={timeout:.0f}s)"
        )

        start = time.monotonic()
        exit_code, stdout, early_failed = self._run_with_early_detection(cmd, env, timeout, start)
        duration = time.monotonic() - start
        timed_out = exit_code == -1 and not early_failed

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout,
            duration=duration,
            timed_out=timed_out,
            early_failed=early_failed,
        )

    @staticmethod
    def check_available() -> bool:
        """Return True if apptainer binary exists and default image is present."""
        if not Path(_APPTAINER_BIN).exists():
            return False
        try:
            proc = subprocess.run(
                [_APPTAINER_BIN, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode != 0:
                return False
        except Exception:
            return False
        return Path(_DEFAULT_IMAGE).exists()

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    def _build_exec_cmd(
        self,
        workspace_dir: Path,
        output_dir: Path,
        data_mounts: dict[str, str] | None = None,
    ) -> list[str]:
        """Build the `apptainer exec` command with all flags and bind mounts."""
        cmd = [
            self.apptainer, "exec",
            "--nv",
            "--no-home",
            "--writable-tmpfs",
        ]
        # Resource limits (requires cgroups v2)
        if self._cgroups_available:
            cmd.extend(["--memory", self.memory_limit, "--cpus", self.cpus])

        # Bind workspace (rw) and output (rw)
        cmd.extend(["--bind", f"{workspace_dir}:{workspace_dir}:rw"])
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--bind", f"{output_dir}:{output_dir}:rw"])

        # Track already-bound host paths so we don't double-bind. Apptainer
        # tolerates duplicates but they make the command harder to read.
        bound_hosts: set[str] = {str(workspace_dir), str(output_dir)}

        # Bind common host root directories (data paths typically live under these)
        for root_dir in ["/project", "/tmp", "/data"]:
            root = Path(root_dir)
            if root.exists() and root != workspace_dir and root != output_dir:
                cmd.extend(["--bind", f"{root_dir}:{root_dir}"])
                bound_hosts.add(root_dir)

        # Bind common/ template utilities into workspace
        common_dir = Path(__file__).parents[1] / "domain" / "templates" / "common"
        if common_dir.exists():
            cmd.extend(["--bind", f"{common_dir}:{workspace_dir}/common:ro"])

        # Bind model cache directories (rw)
        home = os.path.expanduser("~")
        for cache_dir in [
            f"{home}/.cache/torch",
            os.getenv("HF_HOME", f"{home}/.cache/huggingface"),
            os.getenv("PATHLAB_CKPT_DIR", ""),
        ]:
            if cache_dir and Path(cache_dir).exists():
                cmd.extend(["--bind", f"{cache_dir}:{cache_dir}:rw"])
                bound_hosts.add(cache_dir)

        # data_mounts from acquisition / user --data-mount flags. Bound rw so
        # prepared-contract scripts can write feature outputs back into
        # prepared_root if needed. Skip entries whose host path is missing
        # or already bound (workspace/output/fixed roots) so the command
        # stays idempotent and tidy.
        for host_path, container_path in (data_mounts or {}).items():
            host_str = str(host_path)
            if host_str in bound_hosts:
                continue
            if not Path(host_str).exists():
                logger.warning(
                    "Skipping data_mount %s -> %s: host path does not exist",
                    host_str, container_path,
                )
                continue
            cmd.extend(["--bind", f"{host_str}:{container_path}:rw"])
            bound_hosts.add(host_str)

        return cmd

    def _build_env(self, extra_vars: dict[str, str] | None = None) -> dict[str, str]:
        """Build environment dict with APPTAINERENV_ prefix for container injection."""
        env = os.environ.copy()

        # GPU control
        gpu_str = ",".join(self.gpu_ids)
        env["CUDA_VISIBLE_DEVICES"] = gpu_str
        env["APPTAINERENV_CUDA_VISIBLE_DEVICES"] = gpu_str

        # Python config
        env["APPTAINERENV_PYTHONUNBUFFERED"] = "1"
        env["APPTAINERENV_TORCH_CUDNN_V8_API_DISABLED"] = "1"

        # Model cache forwarding
        ckpt_dir = os.getenv("PATHLAB_CKPT_DIR", "")
        if ckpt_dir:
            env["APPTAINERENV_PATHLAB_CKPT_DIR"] = ckpt_dir
        hf_home = os.getenv("HF_HOME", "")
        if hf_home:
            env["APPTAINERENV_HF_HOME"] = hf_home
            env["APPTAINERENV_HUGGINGFACE_HUB_CACHE"] = os.getenv(
                "HUGGINGFACE_HUB_CACHE", f"{hf_home}/hub"
            )

        # Extra variables from caller (e.g. OUTPUT_DIR, PATHLAB_QUICK_CHECK)
        if extra_vars:
            for k, v in extra_vars.items():
                env[f"APPTAINERENV_{k}"] = v

        return env

    # ------------------------------------------------------------------
    # Execution with early failure detection
    # ------------------------------------------------------------------

    def _run_with_early_detection(
        self,
        cmd: list[str],
        env: dict[str, str],
        timeout: float,
        start_time: float,
    ) -> tuple[int, str, bool]:
        """Run command, kill early if a fatal pattern appears in the first 30s.

        Wall-clock timeout enforcement (Plan-2026-04-28 P0 #1):
        the previous implementation iterated ``for line in proc.stdout``,
        which blocks indefinitely on a quiet child — the timeout check
        only ran AFTER the next line arrived, so a long-running silent
        training pass would blow past `timeout` by hours
        (session_d162f805e1d7: 1800s requested, 12973s observed).

        Fix:
        - Spawn the child in its own process group (``start_new_session=True``)
          so we can hard-kill the whole tree, including any subprocesses
          the training script forked.
        - Use ``select.poll()`` on stdout with a short interval so the
          wall-clock check fires regardless of how chatty the child is.
        - On wall-clock timeout, escalate SIGTERM → SIGKILL on the
          process group.

        Returns (exit_code, stdout, early_failed).
        """
        log_lines: list[str] = []
        early_failed = False

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1,
                start_new_session=True,  # new process group → killpg works
            )
        except Exception as e:
            logger.error(f"[sandbox] Failed to launch: {e}", exc_info=True)
            return -1, f"{e}", False

        pgid = os.getpgid(proc.pid)

        def _kill_tree(sig: int) -> None:
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                pass
            except Exception:
                # Fallback: at least try the parent.
                try:
                    proc.send_signal(sig)
                except Exception:
                    pass

        # Reader thread + queue: bypasses TextIOWrapper's internal
        # buffer (select/poll on the fd doesn't see buffered text;
        # readline can sit on the buffer indefinitely while the kernel
        # pipe has no new bytes). The thread does blocking readlines
        # and feeds the main loop via a queue with a short timeout, so
        # the wall-clock check fires regardless of how chatty the child
        # is. ``queue.get(timeout=interval)`` is the responsive wait.
        line_queue: queue.Queue[str | None] = queue.Queue()

        def _reader():
            try:
                for line in iter(proc.stdout.readline, ""):
                    line_queue.put(line)
            except Exception as e:
                logger.debug(f"[sandbox] reader thread exited: {e}")
            finally:
                line_queue.put(None)  # sentinel: stdout EOF

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        try:
            while True:
                elapsed = time.monotonic() - start_time
                remaining = timeout - elapsed

                if remaining <= 0:
                    logger.warning(
                        f"[sandbox] Wall-clock timeout after {elapsed:.0f}s "
                        f"(budget {timeout:.0f}s); killing process group {pgid}"
                    )
                    _kill_tree(signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _kill_tree(signal.SIGKILL)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                    break

                # Pull at most one line per iteration with a bounded wait,
                # so the wall-clock check fires within ~0.5s of expiry.
                wait = min(0.5, max(0.05, remaining))
                try:
                    line = line_queue.get(timeout=wait)
                except queue.Empty:
                    line = ""

                if line is None:
                    # Reader saw EOF on stdout; child has exited or is
                    # about to. Wait briefly for the exit, then drain.
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    return proc.returncode if proc.returncode is not None else -1, "".join(log_lines), False

                if line:
                    log_lines.append(line)
                    if elapsed < _EARLY_FAIL_WINDOW:
                        match = _EARLY_FAIL_REGEX.search(line)
                        if match:
                            logger.warning(
                                f"[sandbox] Early failure at {elapsed:.1f}s: {match.group(0)}"
                            )
                            _kill_tree(signal.SIGTERM)
                            try:
                                proc.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                _kill_tree(signal.SIGKILL)
                                try:
                                    proc.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    pass
                            # Drain any lines the reader has already
                            # queued so the agent sees the full
                            # traceback below the kill marker.
                            while True:
                                try:
                                    extra = line_queue.get_nowait()
                                except queue.Empty:
                                    break
                                if extra is None:
                                    break
                                log_lines.append(extra)
                            return -1, "".join(log_lines), True

                # Child exited and queue empty? Let the EOF sentinel
                # handle the return; here we only short-circuit if the
                # child has already been reaped AND the queue is empty.
                if proc.poll() is not None and line_queue.empty():
                    return proc.returncode, "".join(log_lines), False

            return -1, "".join(log_lines), False

        except Exception as e:
            logger.error(
                f"[sandbox] Execution error: {type(e).__name__}: {e}",
                exc_info=True,
            )
            _kill_tree(signal.SIGKILL)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
            return -1, "".join(log_lines) + f"\n[sandbox-error] {type(e).__name__}: {e}", False
