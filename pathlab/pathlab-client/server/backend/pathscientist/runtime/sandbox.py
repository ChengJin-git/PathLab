"""Apptainer sandbox for isolated script execution with GPU passthrough.

Provides container-level isolation for LLM-generated training scripts.
Uses ephemeral `apptainer exec` — each run starts a fresh container process.

Requires: `module load apptainer` on HPC clusters.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
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
    ) -> SandboxResult:
        """Execute a Python script inside the container.

        Args:
            script_path: Relative path within workspace_dir (e.g. "train.py").
            workspace_dir: Host path to the git-backed workspace (bind as rw).
            output_dir: Host path for experiment outputs (bind as rw).
            env_vars: Extra environment variables to inject.
            timeout: Wall-clock timeout in seconds.
        """
        cmd = self._build_exec_cmd(workspace_dir, output_dir)
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

    def _build_exec_cmd(self, workspace_dir: Path, output_dir: Path) -> list[str]:
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

        # Bind common host root directories (data paths typically live under these)
        for root_dir in ["/project", "/tmp", "/data"]:
            root = Path(root_dir)
            if root.exists() and root != workspace_dir and root != output_dir:
                cmd.extend(["--bind", f"{root_dir}:{root_dir}"])

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
            )
            try:
                for line in proc.stdout:
                    log_lines.append(line)
                    elapsed = time.monotonic() - start_time
                    if elapsed < _EARLY_FAIL_WINDOW:
                        match = _EARLY_FAIL_REGEX.search(line)
                        if match:
                            early_failed = True
                            logger.warning(
                                f"[sandbox] Early failure at {elapsed:.1f}s: {match.group(0)}"
                            )
                            proc.kill()
                            proc.wait(timeout=5)
                            return -1, "".join(log_lines), True

                proc.wait(timeout=max(0, timeout - (time.monotonic() - start_time)))
                return proc.returncode, "".join(log_lines), False

            except subprocess.TimeoutExpired:
                logger.warning(f"[sandbox] Timeout after {timeout:.0f}s")
                proc.kill()
                proc.wait(timeout=5)
                return -1, "".join(log_lines), False

        except Exception as e:
            logger.error(f"[sandbox] Execution error: {e}", exc_info=True)
            return -1, "".join(log_lines) + f"\n{e}", False
