import os
from pathlib import Path
import subprocess
import sys

from backend.common import file_lock


def test_native_lock_excludes_another_process_and_releases_on_close(tmp_path):
    path = tmp_path / 'coordination.lock'
    code = '''
import sys
from backend.common import file_lock
with open(sys.argv[1], 'a') as lock:
    try:
        file_lock.flock(lock, file_lock.LOCK_EX | file_lock.LOCK_NB)
    except BlockingIOError:
        sys.exit(3)
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    def probe():
        return subprocess.run([sys.executable, '-c', code, str(path)], env=env, timeout=10).returncode
    with path.open('a') as lock:
        file_lock.flock(lock, file_lock.LOCK_EX)
        assert probe() == 3
        file_lock.flock(lock, file_lock.LOCK_UN)
        assert probe() == 0
        file_lock.flock(lock, file_lock.LOCK_EX)
    assert probe() == 0
