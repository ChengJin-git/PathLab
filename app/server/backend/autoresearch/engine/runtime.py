"""Apptainer process ownership for the OpenCode service and experiment jobs."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import httpx

from backend.common.config import Config
from backend.common.model_config import ModelConfig

from ..runtime.sandbox import _resolve_apptainer_bin, _resolve_default_image
from .client import OpenCodeClient
from .skills import install_skills
from .builtin_skills import LIBRARY, install_domain_skills
from . import pathtrove
from .skill_credentials import credentials_directory, skill_environment
from ..runtime import container_backend
from .processes import spawn_owned, stop as stop_owned, terminate

# Must equal package.json "opencodeVersion" (test_research_engine checks it).
OPENCODE_VERSION = "2.4.2"


def opencode_binary() -> str | None:
    """PATHLAB_OPENCODE_BIN, then PATH, then the install-opencode.py location.

    The last fallback keeps a service started with a minimal PATH (systemd at
    boot) able to run research instead of blocking every session.
    """
    installed = Path.home() / ".opencode/bin/opencode"
    return (
        os.getenv("PATHLAB_OPENCODE_BIN")
        or shutil.which("opencode")
        or (str(installed) if os.access(installed, os.X_OK) else None)
    )

PACKAGE = Path(__file__).parents[1]


def workspace(session_id: str) -> Path:
    return Config.get_autoresearch_sessions_dir() / f"session_{session_id}"


def private_dir(session_id: str) -> Path:
    path = Config.get_autoresearch_dir() / "runtime" / session_id
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def credentials(session_id: str) -> dict:
    path = private_dir(session_id) / "credentials.json"
    if not path.exists():
        payload = {
            "password": secrets.token_urlsafe(32),
            "tool_token": secrets.token_urlsafe(32),
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
    return json.loads(path.read_text())


def sandbox_command(
    root: Path, data_mounts: dict[str, str], *, gpu: str | None = None
) -> list[str]:
    image = _resolve_default_image()
    if container_backend.backend() != 'docker' and not Path(image).exists():
        raise RuntimeError(f"Apptainer image missing: {image}")
    cmd = [
        _resolve_apptainer_bin(),
        "exec",
        "--contain",
        "--no-home",
        "--no-mount",
        "cwd,bind-paths",
        "--cleanenv",
        "--writable-tmpfs",
    ]
    if gpu is not None:
        cmd.append("--nv")
    cmd += ["--bind", f"{root}:{root}:rw", "--pwd", str(root)]
    for name in ["runs", "datasets", "downloads"]:
        directory = root / name
        directory.mkdir(exist_ok=True)
        cmd += ["--bind", f"{directory}:{directory}:ro"]
    # --contain/--no-mount removes this site's implicit resolver bind.
    resolver = Path("/etc/resolv.conf").resolve()
    if resolver.is_file():
        cmd += ["--bind", f"{resolver}:/etc/resolv.conf:ro"]
    inputs = (
        Config.get_autoresearch_dir()
        / "runtime"
        / root.name.removeprefix("session_")
        / "inputs"
    )
    inputs.mkdir(parents=True, exist_ok=True)
    cmd += ["--bind", f"{inputs}:/research-data:ro"]
    for path, destination in sorted(data_mounts.items()):
        p = Path(path).resolve()
        if p == inputs or (p.is_dir() and p.is_relative_to(inputs)):
            continue
        if p.exists() and (str(p) != destination or (p != root and root not in p.parents)):
            cmd += ["--bind", f"{p}:{destination}:ro"]
    cmd += ["--bind", f"{PACKAGE / 'domain/templates'}:/opt/pathlab/templates:ro"]
    cmd += ["--bind", f"{PACKAGE / 'domain/skills'}:/opt/pathlab/guidance:ro"]
    cmd += ["--bind", f"{LIBRARY}:/opt/pathlab/skill-library:ro"]
    if pathtrove.home().is_dir():
        cmd += ["--bind", f"{pathtrove.home()}:{pathtrove.SANDBOX_HOME}:ro"]
    packages = root / '.opencode/packages'
    if packages.is_dir():
        cmd += ['--bind', f'{packages}:{packages}:ro']
    publisher_credentials = credentials_directory() / "lit-dl"
    if publisher_credentials.is_dir():
        cmd += ["--bind", f"{publisher_credentials}:/opt/pathlab/lit-dl:ro"]
    for cache in [
        Config.get_uploads_dir() / "extractor_checkpoints",
        Path(os.getenv("HF_HOME", str(Path.home() / ".cache/huggingface"))),
        Path.home() / ".cache/torch",
    ]:
        if cache.is_dir():
            cmd += ["--bind", f"{cache}:{cache}:{'rw' if gpu is not None else 'ro'}"]
    cmd.append(image)
    return cmd


class AgentRuntime:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.root = workspace(session_id)
        self.private = private_dir(session_id)
        self.process: asyncio.subprocess.Process | None = None
        self.client: OpenCodeClient | None = None
        self.container_name: str | None = None

    async def start(
        self, model: ModelConfig, data_mounts: dict[str, str], custom_skills: list[dict] | None = None,
        language: str | None = None,
    ) -> OpenCodeClient:
        await asyncio.to_thread(pathtrove.install)
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in ["home", "config", "data", "cache", "state"]:
            (self.private / directory).mkdir(exist_ok=True)
        key = credentials(self.session_id)
        skill_dir = self.root / ".opencode" / "skills" / "pathlab-research"
        shutil.rmtree(skill_dir, ignore_errors=True)
        shutil.copytree(PACKAGE / "engine/research-skill", skill_dir)
        install_domain_skills(self.root)
        install_skills(self.root, custom_skills or [])
        shutil.copyfile(
            PACKAGE / "engine/agent-instructions.md", self.root / "AGENTS.md"
        )
        if custom_skills:
            with (self.root / "AGENTS.md").open('a', encoding='utf-8') as instructions:
                instructions.write(
                    '\n\n## User-selected skills\n'
                    'After loading pathlab-research, load these skills by ID before planning: '
                    + ', '.join(skill['id'] for skill in custom_skills)
                    + '. They supplement the user goal; current user corrections and PathLab execution/data boundaries take priority. '
                    'Package wrappers point to full skill trees with scripts, assets and sibling references. '
                    'Follow their resource base directory. Packages are read-only and remain accessible in jobs '
                    'under PATHLAB_WORKSPACE/.opencode/packages. Copy scripts into the workspace before editing, '
                    'and send generated output to OUTPUT_DIR. Use actual tools available here; upstream tool names '
                    'or allowed-tools declarations do not install tools or MCP services. Report concrete missing '
                    'dependencies and use install_dependencies where applicable. Never invent absent resources.\n'
                )
        with (self.root / 'AGENTS.md').open('a', encoding='utf-8') as instructions:
            output_language = {'en-US': 'English', 'zh-CN': 'Simplified Chinese', 'zh-HK': 'Traditional Chinese (Hong Kong)'}.get(language, "the language of the user's request")
            instructions.write(f'\n\n## Output language\nUse {output_language} for user-facing messages, '
                'plan titles, progress/activity descriptions, delegated task titles and instructions, findings.md, research-plan.md, Markdown headings, captions and report prose. '
                'When delegating, explicitly pass this output language to every child. Set the activity field on public research tools '
                'to a short factual description of the scientific action in this language. Keep retrieval queries in whichever '
                'language gives the best source coverage; never use the raw query as the progress description. '
                'Pass the session language to generate_article unless the user explicitly requests another. '
                'A skill written in another language does not change this output language. Preserve filenames, '
                'code, API fields, identifiers, citations and original source quotations. Explicit user language '
                'requests take priority.\n')
            if container_backend.backend() == 'docker' and sys.platform == 'darwin':
                instructions.write('\n## Compute backend\nThis Docker Desktop research container has CPU only. '
                    'Submit experiments with device=cpu. Apple MPS is exposed only to PathLab built-in native trainers, '
                    'not this container. Do not request CUDA or claim sandbox MPS execution.\n')
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": "pathlab/research",
            "providers": {"pathlab": model.opencode_provider()},
            "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            "snapshots": False,
            # The research loop owns scheduling; agent-created timers would outlive its budget.
            "automations": False,
            "skills": [
                "/opt/pathlab/skill-library/nature-skills/skills",
                "/opt/pathlab/skill-library/editing",
                f"{pathtrove.SANDBOX_PLUGIN}/skills",
            ],
            "mcp": {
                "servers": {
                    "pathlab": {
                        "type": "local",
                        "command": ["python", "/opt/pathlab/mcp_stdio.py"],
                        "codemode": False,
                        "environment": {
                            "PATHLAB_RESEARCH_ID": self.session_id,
                            "PATHLAB_RESEARCH_TOKEN": "{env:PATHLAB_RESEARCH_TOKEN}",
                            "PATHLAB_GATEWAY_URL": Config.GATEWAY_SERVICE_URL,
                        },
                    },
                    "pathtrove": pathtrove.mcp_server(),
                }
            },
        }
        (self.root / "opencode.json").write_text(json.dumps(config, indent=2))
        docker = container_backend.backend() == 'docker'
        binary = opencode_binary()
        if not docker:
            if not binary:
                raise RuntimeError("Install OpenCode V2 (deploy/install-opencode.py --output ~/.opencode/bin/opencode) or configure PATHLAB_OPENCODE_BIN")
            version = await asyncio.to_thread(subprocess.check_output, [binary, "--version"], text=True, timeout=10)
            if version.strip() != f'opencode v{OPENCODE_VERSION}':
                raise RuntimeError(f"The research runtime requires OpenCode {OPENCODE_VERSION}; run deploy/install-opencode.py")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cmd = sandbox_command(self.root, data_mounts)
        image = cmd.pop()
        cmd.remove("--no-home")
        for name in ["config", "data", "cache", "state"]:
            directory = self.private / name
            cmd += ["--bind", f"{directory}:{directory}:rw"]
        cmd += [
            "--home",
            f"{self.private / 'home'}:/home/research",
            "--bind",
            f"{Path(binary or sys.executable).resolve()}:/opt/opencode:ro",
            "--bind",
            f"{PACKAGE / 'engine/mcp_stdio.py'}:/opt/pathlab/mcp_stdio.py:ro",
            image,
            "/opt/opencode",
            "serve",
            "--hostname",
            "0.0.0.0" if docker else "127.0.0.1",
            "--port",
            str(port),
        ]
        injected = {
            **skill_environment(),
            "XDG_CONFIG_HOME": str(self.private / "config"),
            "XDG_DATA_HOME": str(self.private / "data"),
            "XDG_CACHE_HOME": str(self.private / "cache"),
            "XDG_STATE_HOME": str(self.private / "state"),
            "OPENCODE_SERVER_PASSWORD": key["password"],
            "PATHLAB_MODEL_KEY": model.api_key,
            "PATHLAB_RESEARCH_TOKEN": key["tool_token"],
            "CUDA_VISIBLE_DEVICES": "",
        }
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", ""),
        }
        env.update({f"APPTAINERENV_{k}": v for k, v in injected.items()})
        if docker:
            # Only the authenticated per-session MCP endpoint is reachable through
            # the scoped relay. The public Gateway remains loopback-only.
            from .docker_relay import start_relay
            self.relay, relay_port = await start_relay(self.session_id, key['tool_token'])
            config['mcp']['servers']['pathlab']['environment']['PATHLAB_GATEWAY_URL'] = f'http://host.docker.internal:{relay_port}'
            (self.root / 'opencode.json').write_text(json.dumps(config, indent=2))
        cmd, env, self.container_name = container_backend.prepare(cmd, env, name='pathlab-agent-' + self.session_id, publish_port=port)
        with (self.private / "server.log").open("a") as log:
            log_start = log.tell()
            self.process = await spawn_owned(
                self.session_id, self.private / 'process.json', cmd,
                record_data={'port': port, 'container': self.container_name},
                env=env,
                stdout=log,
                stderr=log,
            )
        self.client = OpenCodeClient(f"http://127.0.0.1:{port}", key["password"])
        for _ in range(120):
            if self.process.returncode is not None:
                with (self.private / 'server.log').open('rb') as log:
                    log.seek(max(log_start, log.seek(0, os.SEEK_END) - 4000))
                    detail = log.read().decode(errors='replace').strip()
                for secret in (key['password'], key['tool_token'], model.api_key):
                    if secret:
                        detail = detail.replace(secret, '[redacted]')
                raise RuntimeError(f"OpenCode sandbox exited ({self.process.returncode}): {detail or 'No startup output'}")
            try:
                await self.client.request("GET", "/api/info")
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
                continue
            await self.client.ensure_research_tools(str(self.root))
            return self.client
        raise RuntimeError("OpenCode sandbox startup timed out")

    async def stop(self):
        await stop_owned(self.private / 'process.json')
        relay = getattr(self, 'relay', None)
        if relay:
            relay.close(); await relay.wait_closed()
        if self.process:
            if self.process.returncode is None:
                await terminate(self.process.pid)
            await asyncio.wait_for(self.process.wait(), 5)
        if self.client:
            await self.client.close()
        (self.private / "process.json").unlink(missing_ok=True)

    async def cleanup_orphan(self):
        path = self.private / "process.json"
        await stop_owned(path)
        path.unlink(missing_ok=True)
