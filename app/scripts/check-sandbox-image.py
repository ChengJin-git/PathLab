#!/usr/bin/env python3
"""Verify the OCI image's project-pinned OpenCode server and filesystem contract."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import base64

image = os.getenv('PATHLAB_DOCKER_IMAGE', 'pathlab/sandbox:1.0.8-r3-cpu')
version = json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text())['opencodeVersion']
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / 'workspace').mkdir(); (root / 'home').mkdir()
    name = 'pathlab-image-validation-' + str(os.getpid())
    password = 'isolated-ci-test'
    command = ['docker','run','--rm','--name',name,'--user',f'{os.getuid()}:{os.getgid()}','--read-only','--cap-drop=ALL',
        '--security-opt=no-new-privileges','--tmpfs','/tmp:rw,nosuid,size=512m',
        '--mount',f'type=bind,source={root / "workspace"},target=/workspace',
        '--mount',f'type=bind,source={root / "home"},target=/home/research',
        '--workdir','/workspace','--env','HOME=/home/research',
        '--env',f'OPENCODE_SERVER_PASSWORD={password}','-p',f'127.0.0.1:{port}:{port}',
        image,'/opt/opencode','serve','--hostname','0.0.0.0','--port',str(port)]
    with (root / 'server.log').open('w+') as log:
        child = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            for _ in range(90):
                try:
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/info', headers={
                        'Authorization': 'Basic '+base64.b64encode(f'opencode:{password}'.encode()).decode()})
                    with urllib.request.urlopen(req, timeout=2) as response:
                        print(json.load(response)); break
                except (urllib.error.URLError, TimeoutError):
                    if child.poll() is not None: raise RuntimeError('OpenCode container exited')
                    time.sleep(1)
            else: raise RuntimeError('OpenCode server did not become ready')
            result = subprocess.check_output(['docker','exec',name,'/opt/opencode','--version'], text=True).strip()
            assert result == f'opencode v{version}', result
            subprocess.run(['docker','exec',name,'python','-c',
                "from pathlib import Path;Path('/workspace/result').write_text('ok');assert not Path('/var/run/docker.sock').exists();\ntry:Path('/host-write').write_text('bad');raise AssertionError('root writable')\nexcept OSError:pass"],check=True)
            assert (root / 'workspace/result').read_text() == 'ok'
        except Exception:
            log.flush(); log.seek(0); print(log.read()); raise
        finally:
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child.wait(timeout=30)
