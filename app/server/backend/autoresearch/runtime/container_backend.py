"""Translate the existing explicit Apptainer mount contract to Docker Desktop.

The same read-only/write mounts are used by both backends. Docker never receives
the host Docker socket, home directory, privileged mode or arbitrary host ports.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import uuid


def backend() -> str:
    value = os.getenv('PATHLAB_SANDBOX_BACKEND', 'docker' if sys.platform in {'darwin', 'win32'} else 'apptainer')
    if value not in {'docker', 'apptainer'}:
        raise ValueError('PATHLAB_SANDBOX_BACKEND must be docker or apptainer')
    return value


def docker_image() -> str:
    return os.getenv('PATHLAB_DOCKER_IMAGE', 'pathlab/sandbox:1.0.8-r3-cpu')


def docker_binary() -> str:
    configured = os.getenv('PATHLAB_DOCKER_BIN')
    if configured: return configured
    discovered = shutil.which('docker')
    if discovered: return discovered
    candidates = [Path('/Applications/Docker.app/Contents/Resources/bin/docker')]
    if os.name == 'nt':
        candidates.insert(0, Path(os.getenv('ProgramFiles', r'C:\Program Files')) / 'Docker/Docker/resources/bin/docker.exe')
    return next((str(path) for path in candidates if path.is_file()), 'docker')


def container_path(path: str) -> str:
    """Linux paths stay identical; Windows drive paths get a stable POSIX prefix."""
    if re.match(r'^[A-Za-z]:[\\/]', path):
        p = PureWindowsPath(path)
        return '/pathlab-host/' + p.drive[0].lower() + '/' + '/'.join(p.parts[1:])
    return path


def split_mount(value: str) -> tuple[str, str, str]:
    # Drive colons are followed by a slash; mount separators are not drive colons.
    # Work explicitly from the mode suffix and the known absolute target start.
    match = re.match(r'^([A-Za-z]:[\\/].*?|/.*?):((?:[A-Za-z]:[\\/]|/).+?)(?::(ro|rw))?$', value)
    if not match:
        raise ValueError(f'Invalid explicit mount: {value}')
    return match[1], match[2], match[3] or 'rw'


def translate_value(value: str, mounts: list[tuple[str, str, str]]) -> str:
    for source, target, _ in sorted(mounts, key=lambda item: len(item[0]), reverse=True):
        destination = container_path(target)
        for prefix in {source, source.replace('\\', '/')}:
            if value == prefix or value.startswith(prefix + '/') or value.startswith(prefix + '\\'):
                return destination + value[len(prefix):].replace('\\', '/')
    return container_path(value)


def map_tree(value, mapping):
    if isinstance(value, dict): return {key: map_tree(item, mapping) for key, item in value.items()}
    if isinstance(value, list): return [map_tree(item, mapping) for item in value]
    if isinstance(value, str):
        for source, target in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            if value == source or value.startswith(source + '/') or value.startswith(source + '\\'):
                return target + value[len(source):].replace('\\', '/')
    return value


def prepare(command: list[str], env: dict[str, str], *, name: str | None = None,
            publish_port: int | None = None) -> tuple[list[str], dict[str, str], str | None]:
    if backend() == 'apptainer':
        return command, env, None
    name = name or 'pathlab-' + uuid.uuid4().hex
    mounts: list[tuple[str, str, str]] = []
    cwd, home, gpu = '/tmp', None, False
    index = 2  # apptainer exec
    while index < len(command) and command[index].startswith('--'):
        flag = command[index]
        if flag in {'--bind', '--pwd', '--home', '--no-mount', '--memory', '--cpus'}:
            value = command[index + 1]; index += 2
            if flag == '--bind': mounts.append(split_mount(value))
            elif flag == '--pwd': cwd = value
            elif flag == '--home':
                source, target, mode = split_mount(value)
                mounts.append((source, target, mode)); home = target
        else:
            if flag == '--nv': gpu = True
            index += 1
    if index >= len(command):
        raise ValueError('Container command has no image')
    image = docker_image()
    executable = docker_binary()
    args = [executable, 'run', '--rm', '--name', name, '--label', 'com.pathlab.managed=true',
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=512',
            '--tmpfs', '/tmp:rw,nosuid,size=2g', '--shm-size=512m',
            '--memory', os.getenv('PATHLAB_DOCKER_MEMORY', '6g'),
            '--cpus', os.getenv('PATHLAB_DOCKER_CPUS', '4')]
    if sys.platform != 'win32': args += ['--user', f'{os.getuid()}:{os.getgid()}']
    else: args += ['--user', '1000:1000']
    if sys.platform == 'linux': args += ['--add-host', 'host.docker.internal:host-gateway']
    if publish_port is not None: args += ['--publish', f'127.0.0.1:{publish_port}:{publish_port}']
    if gpu:
        visible = env.get('APPTAINERENV_CUDA_VISIBLE_DEVICES', '')
        if sys.platform == 'darwin': raise ValueError('Docker Desktop cannot expose Apple MPS; submit this sandbox job with device=cpu')
        if image.endswith('-cpu'): raise ValueError('This Docker sandbox image is CPU-only. Submit device=cpu or configure a CUDA-enabled PATHLAB_DOCKER_IMAGE.')
        args += ['--gpus', 'device=' + visible if visible else 'all']
    filtered = []
    for source, target, mode in mounts:
        # OpenCode's Linux executable is part of the OCI image, not a Mac/Windows binary.
        if target == '/opt/opencode': continue
        if target == '/etc/resolv.conf': continue  # Docker owns its network/DNS configuration.
        target = container_path(target)
        if ',' in source or ',' in target: raise ValueError('Docker bind paths cannot contain commas')
        if not Path(source).exists(): raise FileNotFoundError(source)
        args += ['--mount', f'type=bind,source={Path(source).resolve()},target={target}' + (',readonly' if mode == 'ro' else '')]
        filtered.append((source, target, mode))
    args += ['--workdir', translate_value(cwd, filtered)]
    child_env = dict(os.environ)
    for key, value in env.items():
        if key.startswith('APPTAINERENV_'):
            key = key.removeprefix('APPTAINERENV_')
            child_env[key] = translate_value(value, filtered)
            args += ['--env', key]
    if gpu: child_env['CUDA_VISIBLE_DEVICES'] = '0'
    if home:
        child_env['HOME'] = container_path(home); args += ['--env', 'HOME']
    elif 'APPTAINERENV_HOME' not in env:
        child_env['HOME'] = '/tmp'; args += ['--env', 'HOME']
    child_env['PATHLAB_PATH_MAP'] = json.dumps({source: target for source, target, _ in filtered if source != target})
    args += ['--env', 'PATHLAB_PATH_MAP']
    inner = [translate_value(arg, filtered) for arg in command[index + 1:]]
    args += [image, *inner]
    return args, child_env, name


def remove_container_sync(name: str | None):
    if not name: return
    if not re.fullmatch(r'pathlab-[a-zA-Z0-9_.-]+', name): raise ValueError('Not a PathLab container name')
    subprocess.run([docker_binary(), 'rm', '-f', name],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


async def remove_container(name: str | None):
    await asyncio.to_thread(remove_container_sync, name)


def available() -> tuple[bool, str]:
    if backend() == 'apptainer': return True, ''  # existing Apptainer startup checks apply
    try:
        result = subprocess.run([docker_binary(), 'image', 'inspect', docker_image()],
                                capture_output=True, timeout=10)
        if result.returncode == 0: return True, ''
        return False, f'Start Docker Desktop and load the PathLab sandbox image ({docker_image()}).'
    except (OSError, subprocess.TimeoutExpired):
        return False, 'Install and start Docker Desktop to use the local research sandbox.'
