#!/usr/bin/env python3
"""Install the project-pinned OpenCode CLI from npm, validating SHA-512 integrity."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tarfile
import tempfile
import urllib.request


def pinned_version():
    return json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text())['opencodeVersion']


def install(target, output, version=None):
    version = version or pinned_version()
    package = f'@opencode/cli-{target}'
    with urllib.request.urlopen(f'https://registry.npmjs.org/{package.replace("/", "%2f")}/{version}') as response:
        metadata = json.load(response)
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / 'opencode.tgz'
        urllib.request.urlretrieve(metadata['dist']['tarball'], archive)
        digest = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
        if metadata['dist']['integrity'] != 'sha512-' + digest:
            raise RuntimeError('OpenCode package integrity mismatch')
        output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
        binary = 'opencode.exe' if target.startswith('windows') else 'opencode'
        with tarfile.open(archive) as package_file:
            member = package_file.extractfile('package/bin/' + binary)
            if member is None: raise RuntimeError('OpenCode binary is absent')
            temporary = output.with_name(output.name + '.new')
            temporary.write_bytes(member.read()); temporary.chmod(0o755)
            os.replace(temporary, output)
        print(f'Installed OpenCode {version} ({target}): {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default={'win32':'windows','darwin':'darwin'}.get(sys.platform,'linux') + '-' + ('arm64' if platform.machine().lower() in {'arm64','aarch64'} else 'x64'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', default=pinned_version())
    args = parser.parse_args(); install(args.target, args.output, args.version)
