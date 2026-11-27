#!/usr/bin/env python3
"""Export the verified installed runtime as wheels; restore without re-resolving it.

Run export with the source environment's Python. No application settings, model
weights, datasets, credentials or OpenCode user configuration are collected.
"""
import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def installed():
    return sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower())


def inventory():
    return {
        'python': platform.python_version(), 'platform': platform.system(),
        'architecture': platform.machine(), 'libc': platform.libc_ver(),
        'packages': [{'name': d.metadata['Name'], 'version': d.version,
                      'source': json.loads(d.read_text('direct_url.json') or 'null'),
                      'wheel': d.read_text('WHEEL')} for d in installed()],
    }


def repack(dist, destination):
    """Repack installed files, including local patches, with fresh wheel hashes."""
    wheel_metadata = dist.read_text('WHEEL')
    if not wheel_metadata or not dist.files:
        raise RuntimeError(f'{dist.metadata["Name"]}: missing WHEEL/RECORD')
    from packaging.tags import parse_tag, sys_tags
    supported = set(sys_tags())
    tags = re.findall(r'^Tag: (.+)$', wheel_metadata, re.M)
    tag = next((tag for tag in tags if parse_tag(tag) & supported), None)
    if tag is None:
        raise RuntimeError(f'{dist.metadata["Name"]}: no compatible installed wheel tag')
    name = re.sub(r'[-_.]+', '_', dist.metadata['Name'])
    stem = f'{name}-{dist.version}'
    output = destination / f'{stem}-{tag}.whl'
    root = Path(dist.locate_file('')).resolve()
    prefix = Path(sys.prefix).resolve()
    records = []
    entrypoints = {ep.name for ep in dist.entry_points if ep.group in {'console_scripts', 'gui_scripts'}}
    record_name = None
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for item in dist.files:
            relative = str(item)
            path = Path(dist.locate_file(item)).resolve()
            if '__pycache__' in item.parts or relative.endswith(('.pyc', '.pyo')):
                continue
            if relative.endswith('.dist-info/RECORD') and len(item.parts) == 2:
                record_name = relative
                continue
            if relative.endswith(('.dist-info/INSTALLER', '.dist-info/REQUESTED', '.dist-info/direct_url.json')):
                continue
            if not path.is_file():
                raise RuntimeError(f'Missing installed file: {path}')
            if relative.startswith('../'):
                local = path.relative_to(prefix)
                if local.parts[0] == 'bin':
                    if local.name in entrypoints or (name == 'pip' and local.name.startswith('pip')):
                        continue  # installer regenerates entry-point shebangs
                    relative = f'{stem}.data/scripts/{local.name}'
                else:
                    relative = f'{stem}.data/data/{local.as_posix()}'
            elif not path.is_relative_to(root):
                raise RuntimeError(f'Package file escapes site-packages: {path}')
            digest = hashlib.sha256()
            size = 0
            info = zipfile.ZipInfo.from_file(path, arcname=relative)
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open('rb') as source, archive.open(info, 'w', force_zip64=True) as target:
                for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
                    target.write(chunk); digest.update(chunk); size += len(chunk)
            records.append((relative, 'sha256=' + base64.urlsafe_b64encode(digest.digest()).rstrip(b'=').decode(), size))
        if not record_name:
            raise RuntimeError(f'{name}: no RECORD')
        contents = io.StringIO()
        writer = csv.writer(contents, lineterminator='\n')
        writer.writerows([*records, (record_name, '', '')])
        archive.writestr(record_name, contents.getvalue())
    return output


def export(args):
    required_assets = [('opencode', args.opencode), ('sandbox.sif', args.sandbox), ('uv', shutil.which('uv'))]
    for name, value in required_assets:
        if not value or not Path(value).is_file():
            raise RuntimeError(f'Missing required asset: {name}')
    expected_opencode = json.loads((Path(__file__).resolve().parents[1] / 'package.json').read_text())['opencodeVersion']
    if subprocess.check_output([args.opencode, '--version'], text=True).strip() != f'opencode v{expected_opencode}':
        raise RuntimeError(f'Update OpenCode to {expected_opencode} before exporting the runtime bundle')
    destination = Path(args.bundle).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    wheels = destination / 'wheels'; wheels.mkdir()
    manifest = inventory()
    manifest['format'] = 1
    client_root = Path(__file__).resolve().parents[1]
    manifest['created_at'] = datetime.now(timezone.utc).isoformat()
    manifest['pathlab_version'] = json.loads((client_root / 'package.json').read_text())['version']
    manifest['source_commit'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=client_root,text=True).strip()
    manifest['source_dirty'] = bool(subprocess.check_output(['git','status','--porcelain'],cwd=client_root,text=True).strip())
    manifest['assets'] = {}
    manifest['requirements'] = []
    for dist in installed():
        path = repack(dist, wheels)
        digest = sha256(path)
        manifest['assets'][str(path.relative_to(destination))] = digest
        manifest['requirements'].append(f'{dist.metadata["Name"]}=={dist.version} --hash=sha256:{digest}')
        print(f'Exported {path.name}', flush=True)
    for name, value in required_assets:
        if not value:
            raise RuntimeError(f'Missing required asset: {name}')
        source = Path(value).resolve()
        target = destination / name
        shutil.copy2(source, target)
        manifest['assets'][name] = sha256(target)
    manifest['opencode_version'] = subprocess.check_output([args.opencode, '--version'], text=True).strip()
    manifest['apptainer_version'] = subprocess.check_output(
        [shutil.which('apptainer') or 'apptainer', '--version'], text=True
    ).strip()
    manifest['uv_version'] = subprocess.check_output([str(destination / 'uv'), '--version'], text=True).strip()
    lock = destination / 'requirements.lock'
    lock.write_text('\n'.join(manifest['requirements']) + '\n')
    manifest['assets']['requirements.lock'] = sha256(lock)
    for helper in ['runtime_bundle.py', 'verify-runtime.py', 'install-runtime.sh']:
        shutil.copy2(Path(__file__).with_name(helper), destination / helper)
        manifest['assets'][helper] = sha256(destination / helper)
    for relative in ['package.json', 'package-lock.json', 'server/requirements.txt', 'server/requirements-test.txt',
                     'server/requirements-sandbox-survival.txt',
                     'server/backend/autoresearch/runtime/containers/skills-runtime-requirements.txt',
                     'server/backend/autoresearch/runtime/containers/ml-runtime-requirements.txt']:
        target = destination / 'source-declarations' / relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(client_root / relative, target)
        manifest['assets'][str(target.relative_to(destination))] = sha256(target)
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Bundle complete: {destination}')


def install(args):
    bundle = Path(args.bundle).resolve()
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest['platform'] != platform.system() or manifest['architecture'] != platform.machine():
        raise RuntimeError('Bundle requires the same operating system and architecture')
    source_libc, source_version = manifest['libc']
    target_libc, target_version = platform.libc_ver()
    if source_libc == 'glibc' and (target_libc != 'glibc' or tuple(map(int, target_version.split('.'))) < tuple(map(int, source_version.split('.')))):
        raise RuntimeError(f'Bundle requires glibc >= {source_version}')
    for name, digest in manifest['assets'].items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle) or sha256(path) != digest:
            raise RuntimeError(f'Bundle checksum mismatch: {name}')
    target = Path(args.target).resolve()
    if target.exists():
        raise RuntimeError('Target already exists; install into a new environment and verify before switching')
    uv = str(bundle / 'uv')
    subprocess.run([uv, 'venv', '--python', args.python or manifest['python'], str(target)], check=True)
    python = str(target / 'bin/python')
    version = subprocess.check_output([python, '-c', 'import platform;print(platform.python_version())'], text=True).strip()
    if version != manifest['python']:
        raise RuntimeError(f'Use Python {manifest["python"]}, not {version}')
    subprocess.run([uv, 'pip', 'install', '--python', python, '--no-index', '--no-deps',
                    '--require-hashes', '--find-links', str(bundle / 'wheels'),
                    '-r', str(bundle / 'requirements.lock')], check=True)
    subprocess.run([python, '-m', 'pip', 'check'], check=True)
    subprocess.run([python, str(Path(__file__).with_name('verify-runtime.py'))], check=True)
    subprocess.run([str(bundle / 'opencode'), '--version'], check=True)
    subprocess.run([shutil.which('apptainer') or 'apptainer','exec','--cleanenv',str(bundle/'sandbox.sif'),
                    'python','-c','import torch, sklearn, numpy; print("Sandbox ML imports passed")'],check=True)
    runtime = target / 'pathlab-runtime'; runtime.mkdir()
    shutil.copy2(bundle / 'opencode', runtime / 'opencode')
    # Keep the SIF in the bundle: it is immutable and avoids another multi-GB copy.
    env = target / 'pathlab.env'
    import shlex
    env.write_text('\n'.join(f'export {key}={shlex.quote(value)}' for key, value in {
        'PATHLAB_PYTHON': python, 'PATHLAB_OPENCODE_BIN': str(runtime / 'opencode'),
        'AUTORESEARCH_SANDBOX_IMAGE': str(bundle / 'sandbox.sif'),
    }.items()) + '\n')
    print(f'Installed. Keep the bundle in place. Source {env} before deploy/start.sh.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    exp = commands.add_parser('export')
    exp.add_argument('--bundle', required=True)
    exp.add_argument('--sandbox', required=True)
    exp.add_argument('--opencode', default=shutil.which('opencode'))
    exp.set_defaults(run=export)
    ins = commands.add_parser('install')
    ins.add_argument('--bundle', required=True)
    ins.add_argument('--target', required=True)
    ins.add_argument('--python', help='Interpreter path; otherwise uv obtains the exact source Python version')
    ins.set_defaults(run=install)
    inv = commands.add_parser('inventory')
    inv.set_defaults(run=lambda args: print(json.dumps(inventory(), indent=2)))
    args = parser.parse_args(); args.run(args)


if __name__ == '__main__':
    main()
