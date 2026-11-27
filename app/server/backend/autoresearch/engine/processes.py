"""PID-reuse-safe process ownership for immediate cross-process cancellation."""

import asyncio
import json
import os
import signal
import sys
import tempfile
from pathlib import Path

import psutil

from sqlalchemy import select
from backend.database.database import safe_session
from backend.database.models import AutoResearchSession, ResearchJob


def identity(pid: int) -> str | None:
    try:
        if sys.platform != 'linux':
            return str(psutil.Process(pid).create_time())
        # Field 22; comm may contain spaces or parentheses.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError, psutil.NoSuchProcess):
        return None


def record(path: Path, pid: int, **extra):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.process-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'pid': pid, 'start_ticks': identity(pid), **extra}, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def terminate(pid: int):
    """Stop the process group AND descendants that created their own sessions."""
    if os.name == 'nt':
        import subprocess
        await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        return
    owned = {}
    try:
        parent = psutil.Process(pid)
        owned = {p.pid: p for p in [parent, *parent.children(recursive=True)]}
    except psutil.NoSuchProcess:
        pass
    # A leader may already have exited while its group still owns live workers.
    for item in psutil.process_iter(['pid']):
        try:
            if os.getpgid(item.pid) == pid:
                owned[item.pid] = item
        except (ProcessLookupError, PermissionError):
            continue

    def alive():
        result = []
        for p in owned.values():
            try:
                if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                    result.append(p)
            except psutil.NoSuchProcess:
                pass
        return result

    def send(sig):
        for p in alive():
            try:
                p.send_signal(sig)  # psutil verifies the process birth time.
            except psutil.NoSuchProcess:
                pass

    send(signal.SIGTERM)
    for _ in range(10):
        if not alive():
            return
        await asyncio.sleep(.05)
    send(signal.SIGKILL)
    for _ in range(40):
        if not alive():
            return
        await asyncio.sleep(.05)
    raise RuntimeError(f'Owned process tree {pid} has not exited')


async def spawn_owned(session_id, process_file, command, *, job_id=None, record_data=None, **kwargs):
    """Spawn and publish ownership under the same session lock as deletion."""
    from ..runtime.container_backend import remove_container
    process = None
    spawning = None
    async with safe_session() as db:
        session = await db.scalar(select(AutoResearchSession).where(
            AutoResearchSession.session_id == session_id).with_for_update())
        allowed = (session is not None and (
            session.status not in {'stopping', 'interrupted'} if job_id
            else session.status in {'preparing', 'running', 'waiting'}))
        if (not allowed
                or (session.recovery_metadata or {}).get('delete_requested')):
            raise asyncio.CancelledError()
        if job_id:
            job = await db.get(ResearchJob, job_id, with_for_update=True)
            if job is None or job.session_id != session_id or job.status != 'running':
                raise asyncio.CancelledError()
        try:
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(
                *command, start_new_session=os.name != 'nt', **kwargs))
            process = await asyncio.shield(spawning)
            record(process_file, process.pid, **(record_data or {}))
            await db.commit()
            return process
        except BaseException:
            if process is None and spawning is not None:
                process = await spawning
            if process is not None:
                await asyncio.gather(terminate(process.pid), remove_container((record_data or {}).get('container')))
                await process.wait()
                process_file.unlink(missing_ok=True)
            raise


async def stop(path: Path):
    from ..runtime.container_backend import remove_container

    try:
        saved = json.loads(path.read_text())
    except FileNotFoundError:
        return
    pid = int(saved['pid'])
    current = identity(pid)
    if saved['start_ticks'] is not None and current in {None, saved['start_ticks']}:
        await asyncio.gather(terminate(pid), remove_container(saved.get('container')))


async def stop_session(session):
    root = Path(session.workspace_path)
    from backend.common.config import Config
    paths = [Config.get_autoresearch_dir() / 'runtime' / session.session_id / 'process.json']
    paths.extend((root / 'runs').glob('*/process.json'))
    paths.extend((root / 'downloads').glob('*.process.json'))
    await asyncio.gather(*(stop(path) for path in paths))
