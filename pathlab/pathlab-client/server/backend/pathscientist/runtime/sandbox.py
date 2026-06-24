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
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .kaggle_auth import (
    resolve_kaggle_api_token,
    resolve_kaggle_config_dir,
)

logger = logging.getLogger(__name__)

try:
    from backend.common.config import Config as _PathLabConfig
except Exception:  # pragma: no cover - import can fail in isolated unit tests
    _PathLabConfig = None

# Apptainer binary — resolved once at import time.
def _resolve_apptainer_bin() -> str:
    """Resolve apptainer from env, PATH, then the legacy cluster module path."""
    env_bin = os.getenv("APPTAINER_BIN", "").strip()
    if env_bin:
        return env_bin
    path_bin = shutil.which("apptainer")
    if path_bin:
        return path_bin
    return "/cm/local/apps/apptainer/current/bin/apptainer"


_APPTAINER_BIN = _resolve_apptainer_bin()

# Default .sif image: PathScientist-owned local state.
def _resolve_default_image(backend_dir: Path | None = None) -> str:
    """Resolve the default Apptainer image used when no image is passed."""
    env_image = os.getenv("PATHSCIENTIST_SANDBOX_IMAGE") or os.getenv("PATHLAB_SANDBOX_IMAGE")
    if env_image and Path(env_image).expanduser().exists():
        return env_image

    backend = backend_dir or Path(__file__).resolve().parents[2]
    client_root = backend.parents[1]
    pathscientist_image_dir = client_root / ".local" / "pathscientist" / "sandbox"

    transformers_image = pathscientist_image_dir / "pathlab-sandbox-transformers.sif"
    if transformers_image.exists():
        return str(transformers_image)
    image = pathscientist_image_dir / "pathlab-sandbox.sif"
    if image.exists():
        return str(image)

    return str(pathscientist_image_dir / "pathlab-sandbox.sif")


_DEFAULT_IMAGE = _resolve_default_image()
_KAGGLE_CONTAINER_CONFIG_DIR = "/kaggle"
_CGROUP_DISABLE_VALUES = {"0", "false", "no", "off", "disabled"}
_CGROUP_FORCE_VALUES = {"1", "true", "yes", "on", "enabled", "force"}

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


def _validate_workspace_relative_script_path(script_path: str) -> str:
    raw = str(script_path or "").strip()
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError("script_path must be workspace-relative")
    return raw


def _resolve_kaggle_config_dir() -> Path | None:
    """Return the host Kaggle config dir to expose to the sandbox, if any."""
    return resolve_kaggle_config_dir()


def _pathlab_extractor_checkpoint_root() -> Path | None:
    """Resolve PathLab's extractor checkpoint root for PathScientist sandboxes."""
    env_dir = os.getenv("PATHLAB_CKPT_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()

    if _PathLabConfig is not None:
        try:
            return _PathLabConfig.get_uploads_dir() / "extractor_checkpoints"
        except Exception:
            logger.debug("Could not resolve PathLab uploads checkpoint root", exc_info=True)

    try:
        backend_dir = Path(__file__).resolve().parents[2]
        return backend_dir / "ai" / "extractors" / "checkpoints"
    except Exception:
        return None


def _resource_cgroups_available(setting: str | None = None) -> bool:
    """Return whether Apptainer resource-limit flags are safe to use."""
    raw_setting = (
        setting
        if setting is not None
        else os.getenv("PATHSCIENTIST_SANDBOX_CGROUPS", "auto")
    )
    cgroups_setting = str(raw_setting or "auto").strip().lower()
    if cgroups_setting in _CGROUP_DISABLE_VALUES:
        return False
    if cgroups_setting in _CGROUP_FORCE_VALUES:
        return True

    required_files = [
        Path("/sys/fs/cgroup/cgroup.controllers"),
        Path("/sys/fs/cgroup/cpu.max"),
        Path("/sys/fs/cgroup/memory.max"),
    ]
    return all(path.exists() for path in required_files)


def _symlink_chain_mounts(link_path: Path, *, max_depth: int = 32) -> list[Path]:
    """Return read-only bind roots needed by an absolute symlink chain."""
    mounts: list[Path] = []
    seen_targets: set[str] = set()
    current = link_path

    for _ in range(max_depth):
        try:
            if not current.is_symlink():
                break
            raw_target = current.readlink()
        except OSError:
            break

        target = raw_target if raw_target.is_absolute() else current.parent / raw_target
        target_key = str(target)
        if target_key in seen_targets:
            break
        seen_targets.add(target_key)

        if raw_target.is_absolute():
            try:
                mount_path = (
                    target
                    if target.exists() and target.is_dir() and not target.is_symlink()
                    else target.parent
                )
            except OSError:
                mount_path = target.parent
            if mount_path.exists():
                mounts.append(mount_path)

        current = target

    return mounts


def _symlink_target_mounts(root: Path, *, max_symlinks: int = 10000) -> list[Path]:
    """Find extra binds needed to keep absolute symlinks valid in sandbox."""
    if not root.exists():
        return []

    mounts: list[Path] = []
    dataset_mounts: list[Path] = []
    seen_mounts: set[str] = set()
    seen_dataset_mounts: set[str] = set()
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            link_path = Path(dirpath) / name
            if not link_path.is_symlink():
                continue
            scanned += 1
            if scanned > max_symlinks:
                logger.warning(
                    "Stopped scanning symlink targets under %s after %s symlinks",
                    root,
                    max_symlinks,
                )
                return _merge_symlink_mounts(mounts, dataset_mounts)
            dataset_mount = _pathlab_dataset_parent_for_symlink(link_path)
            if dataset_mount is not None:
                dataset_str = str(dataset_mount)
                if dataset_str not in seen_dataset_mounts:
                    seen_dataset_mounts.add(dataset_str)
                    dataset_mounts.append(dataset_mount)
            for mount_path in _symlink_chain_mounts(link_path):
                mount_str = str(mount_path)
                if mount_str not in seen_mounts:
                    seen_mounts.add(mount_str)
                    mounts.append(mount_path)

    return _merge_symlink_mounts(mounts, dataset_mounts)


_SPLIT_DIR_NAMES = {"train", "training", "val", "valid", "validation", "test", "eval"}


def _contains_path(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _dedupe_mounts(mounts: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for mount in mounts:
        key = str(mount)
        if key in seen:
            continue
        seen.add(key)
        out.append(mount)
    return out


def _normalized_container_mount(path_text: str) -> str:
    text = str(path_text or "").strip()
    if not text:
        return ""
    return text.rstrip("/") or "/"


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _data_mount_preference_score(host_path: Path, workspace_dir: Path) -> int:
    """Rank duplicate container-target mounts by freshness and locality."""
    host_text = str(host_path)
    score = 0
    if _path_is_relative_to(host_path, workspace_dir):
        score += 100
    if "/.dataset/pathlab_registered/" in host_text:
        score += 50
    if "/pathlab_datasets/session_inputs/" in host_text:
        score -= 50
    return score


def _dedupe_data_mounts_by_container_target(
    data_mounts: dict[str, str] | None,
    *,
    workspace_dir: Path,
) -> list[tuple[str, str]]:
    """Return data mounts with one host path per container target.

    PathScientist can carry a stale session_inputs contract and a freshly
    generated workspace contract for the same dataset. Both point at the same
    container path, but only the workspace contract has the latest split IDs.
    Apptainer warns on duplicate destinations and the visible mount can be
    ambiguous, so choose deterministically before constructing --bind flags.
    """
    selected: dict[str, tuple[str, str, int]] = {}
    order: list[str] = []
    for host_path, container_path in (data_mounts or {}).items():
        host_str = str(host_path)
        container_str = str(container_path)
        target = _normalized_container_mount(container_str)
        if not host_str or not target:
            continue
        score = _data_mount_preference_score(Path(host_str), workspace_dir)
        existing = selected.get(target)
        if existing is None:
            selected[target] = (host_str, container_str, score)
            order.append(target)
            continue

        old_host, old_container, old_score = existing
        if score > old_score:
            logger.warning(
                "Replacing duplicate data_mount target %s: %s -> %s wins over %s -> %s",
                target, host_str, container_str, old_host, old_container,
            )
            selected[target] = (host_str, container_str, score)
        else:
            logger.warning(
                "Skipping duplicate data_mount target %s: keeping %s -> %s over %s -> %s",
                target, old_host, old_container, host_str, container_str,
            )

    return [(selected[target][0], selected[target][1]) for target in order]


def _pathlab_dataset_parent_for_symlink(link_path: Path) -> Path | None:
    """Infer the source dataset root for PathLab class-directory symlinks."""
    try:
        raw_target = link_path.readlink()
    except OSError:
        return None
    if not raw_target.is_absolute():
        return None

    target = raw_target
    label_dir = link_path.parent.name
    if not label_dir or target.parent.name != label_dir:
        return None

    split_or_dataset = target.parent.parent
    dataset_root = (
        split_or_dataset.parent
        if split_or_dataset.name.lower() in _SPLIT_DIR_NAMES
        else split_or_dataset
    )
    try:
        if dataset_root.exists() and dataset_root.is_dir():
            return dataset_root
    except OSError:
        return None
    return None


def _merge_symlink_mounts(mounts: list[Path], dataset_mounts: list[Path]) -> list[Path]:
    if not dataset_mounts:
        return _lift_symlink_mounts_to_common_parent(mounts)

    selected = _dedupe_mounts(dataset_mounts)
    for mount in mounts:
        if any(_contains_path(parent, mount) for parent in selected):
            continue
        selected.append(mount)
    return _dedupe_mounts(selected)


def _lift_symlink_mounts_to_common_parent(mounts: list[Path]) -> list[Path]:
    """Collapse many class/split leaf target mounts to their dataset parent.

    PathLab dataset views commonly store patches as symlinks:
    ``images/<class>/<id>.jpg -> <warehouse>/<dataset>/<split>/<class>/<file>``.
    Binding each leaf works until a large first class hits the scan cap before
    later classes are seen. Binding the shared dataset parent keeps every class
    target visible inside the sandbox.
    """
    if len(mounts) < 2:
        return mounts
    try:
        expanded = [mount.expanduser() for mount in mounts]
        common = Path(os.path.commonpath([str(path) for path in expanded]))
    except (OSError, ValueError):
        return mounts
    if common.is_file():
        common = common.parent
    if not common.exists() or not common.is_dir():
        return mounts
    if str(common) in {common.anchor, os.path.expanduser("~")}:
        return mounts
    if common.name in {"", "home", "tmp", "data", "project"}:
        return mounts
    return [common]


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
        image = str(image or "").strip()
        if image and not Path(image).expanduser().exists():
            logger.warning(
                "Ignoring missing Apptainer sandbox image %s; falling back to %s",
                image,
                _DEFAULT_IMAGE,
            )
            image = ""
        self.image = image or _DEFAULT_IMAGE
        self.gpu_ids = gpu_ids or ["0"]
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.apptainer = _APPTAINER_BIN
        self._cgroups_available = _resource_cgroups_available()

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
        script_type: str = "python",
        session_id: str = "",
        run_id: str = "",
        tool_name: str = "run_experiment",
    ) -> SandboxResult:
        """Execute a Python or bash script inside the container.

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
        runner = "bash" if script_type == "bash" else "python"
        try:
            safe_script_path = _validate_workspace_relative_script_path(script_path)
        except ValueError as exc:
            return SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration=0.0,
                timed_out=False,
                early_failed=True,
            )
        cmd = self._build_exec_cmd(workspace_dir, output_dir, data_mounts=data_mounts)
        shell_command = (
            f"cd {shlex.quote(str(workspace_dir))} && "
            f"{shlex.quote(runner)} {shlex.quote(safe_script_path)}"
        )
        cmd.extend([self.image, "bash", "-lc", shell_command])
        env = self._build_env(env_vars)

        logger.info(
            f"[sandbox] apptainer exec: {runner} {script_path} "
            f"(gpu={self.gpu_ids}, timeout={timeout:.0f}s)"
        )

        start = time.monotonic()
        exit_code, stdout, early_failed = self._run_with_early_detection(
            cmd,
            env,
            timeout,
            start,
            session_id=session_id,
            run_id=run_id,
            tool_name=tool_name,
        )
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
            str(_pathlab_extractor_checkpoint_root() or ""),
        ]:
            if cache_dir and Path(cache_dir).exists():
                cmd.extend(["--bind", f"{cache_dir}:{cache_dir}:rw"])
                bound_hosts.add(cache_dir)

        # Kaggle CLI credentials. The sandbox uses --no-home, so ~/.kaggle is
        # not visible unless we explicitly expose the config dir. Bind the
        # minimal directory read-only instead of mounting the whole home.
        kaggle_config_dir = _resolve_kaggle_config_dir()
        if kaggle_config_dir is not None:
            host_str = str(kaggle_config_dir)
            if host_str not in bound_hosts:
                cmd.extend([
                    "--bind",
                    f"{host_str}:{_KAGGLE_CONTAINER_CONFIG_DIR}:ro",
                ])
                bound_hosts.add(host_str)

        # data_mounts from acquisition / user --data-mount flags. Bound rw so
        # prepared-contract scripts can write feature outputs back into
        # prepared_root if needed. Skip entries whose host path is missing
        # or already bound (workspace/output/fixed roots) so the command
        # stays idempotent and tidy.
        for host_path, container_path in _dedupe_data_mounts_by_container_target(
            data_mounts,
            workspace_dir=workspace_dir,
        ):
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
            for target_mount in _symlink_target_mounts(Path(host_str)):
                target_str = str(target_mount)
                if target_str in bound_hosts:
                    continue
                cmd.extend(["--bind", f"{target_str}:{target_str}:ro"])
                bound_hosts.add(target_str)

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
        ckpt_dir = _pathlab_extractor_checkpoint_root()
        if ckpt_dir is not None and ckpt_dir.exists():
            env["PATHLAB_CKPT_DIR"] = str(ckpt_dir)
            env["APPTAINERENV_PATHLAB_CKPT_DIR"] = str(ckpt_dir)
        hf_home = os.getenv("HF_HOME", "")
        if hf_home:
            env["APPTAINERENV_HF_HOME"] = hf_home
            env["APPTAINERENV_HUGGINGFACE_HUB_CACHE"] = os.getenv(
                "HUGGINGFACE_HUB_CACHE", f"{hf_home}/hub"
            )
        for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "PATHSCIENTIST_HUGGINGFACE_TOKEN"):
            value = os.getenv(key, "")
            if value:
                env[f"APPTAINERENV_{key}"] = value

        # Kaggle credential forwarding for dataset acquisition inside the
        # sandbox. Do not log these values; only pass them through when set.
        for key in ("KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
            value = os.getenv(key, "")
            if value:
                env[f"APPTAINERENV_{key}"] = value
        kaggle_config_dir = _resolve_kaggle_config_dir()
        if kaggle_config_dir is not None:
            env["APPTAINERENV_KAGGLE_CONFIG_DIR"] = _KAGGLE_CONTAINER_CONFIG_DIR
            token = resolve_kaggle_api_token(kaggle_config_dir / "kaggle.json")
            if token and "APPTAINERENV_KAGGLE_API_TOKEN" not in env:
                env["APPTAINERENV_KAGGLE_API_TOKEN"] = token

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
        *,
        session_id: str = "",
        run_id: str = "",
        tool_name: str = "",
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
        registered_run_id = run_id or f"pid_{proc.pid}"
        if session_id:
            try:
                from .session_registry import register_active_process

                register_active_process(
                    session_id=session_id,
                    run_id=registered_run_id,
                    pid=proc.pid,
                    pgid=pgid,
                    tool_name=tool_name,
                    command=" ".join(cmd),
                )
            except Exception as exc:
                logger.debug("[sandbox] active process registration failed: %s", exc)

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
        finally:
            if session_id:
                try:
                    from .session_registry import is_session_cancelled, unregister_active_process

                    unregister_active_process(session_id, registered_run_id)
                    if is_session_cancelled(session_id) and proc.returncode not in (0, None):
                        log_lines.append("\n[cancelled] Stopped by user from PathLab.\n")
                except Exception:
                    pass
