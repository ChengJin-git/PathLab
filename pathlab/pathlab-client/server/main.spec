# -*- mode: python ; coding: utf-8 -*-
#
# PathLab Python Sidecar - PyInstaller spec
#
# Build command (run from pathlab-client/):
#   pyinstaller server/main.spec
#
# Output: server/dist/main/   (onedir bundle)
#
# Design notes:
# ------------
# 1. --onedir (not --onefile) is mandatory because:
#    - torch + its CUDA extensions are several GB; onefile would extract them on
#      every launch (30-60 s cold start, fills /tmp)
#    - The onedir folder is shipped via extraResources and spawned directly by
#      Electron's sidecar-manager
#
# 2. Dynamic module loading via string literals
#    server/main.py starts three uvicorn workers with string app-module paths:
#      "backend.preprocessing.main:app"
#      "backend.ai.main:app"
#      "gateway.main:app"
#    PyInstaller's static analyser cannot trace these.  Every module that may be
#    imported at runtime must appear in hiddenimports.
#
# 3. collect_all() is used for large packages that hide sub-modules behind lazy
#    imports (torch, transformers, timm, lancedb, uvicorn, …).
#
# 4. System shared libraries that are dlopen()-ed at runtime and not bundled
#    automatically are added explicitly in binaries[].

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# ---------------------------------------------------------------------------
# Helper: collect a package only if it is actually installed
# ---------------------------------------------------------------------------
def safe_collect_all(pkg):
    try:
        d, b, h = collect_all(pkg)
        return d, b, h
    except Exception:
        return [], [], []


# ---------------------------------------------------------------------------
# collect_all for every major dependency
# ---------------------------------------------------------------------------
packages_to_collect = [
    # Web framework stack
    'uvicorn', 'fastapi', 'starlette', 'anyio',
    # Auth
    'fastapi_users', 'fastapi_users_db_sqlalchemy',
    'jose', 'bcrypt', 'email_validator',
    # Database
    'sqlalchemy', 'asyncpg',
    # Image processing
    'PIL', 'cv2', 'numpy', 'tifffile',
    # WSI
    'openslide',
    # ML / AI — these are the heaviest; collect_all is essential
    'torch', 'torchvision', 'torchaudio',
    'timm', 'transformers', 'huggingface_hub', 'safetensors',
    'torchmetrics', 'einops', 'grad_cam',
    'sklearn', 'scipy', 'lifelines',
    'open_clip',
    # LLM / PDF / RAG
    'lancedb', 'sentence_transformers', 'llama_index',
    'marker', 'pymupdf4llm',
    # LLM clients
    'openai', 'dashscope',
    # Misc utilities
    'omegaconf', 'h5py', 'pandas', 'tqdm', 'loguru', 'coloredlogs',
    'httpx', 'aiohttp', 'requests', 'websockets',
    'redis', 'python_multipart',
    'pydantic', 'pydantic_settings',
    'python_dotenv',
    'multipart',
    'uvloop',
    'click',
    'nvidia_ml_py',
]

all_datas = []
all_binaries = []
all_hiddenimports = []

for pkg in packages_to_collect:
    d, b, h = safe_collect_all(pkg)
    all_datas += d
    all_binaries += b
    all_hiddenimports += h

# ---------------------------------------------------------------------------
# Additional hidden imports — modules loaded via string literals or late imports
# ---------------------------------------------------------------------------
extra_hidden = [
    # uvicorn internals loaded by string in its lifespan / reload machinery
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.loops.uvloop',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.middleware',
    'uvicorn.middleware.proxy_headers',
    'uvicorn.middleware.wsgi',
    # Gateway and backend app modules — loaded as strings by multiprocessing
    'gateway',
    'gateway.main',
    'gateway.dependencies',
    'gateway.pipeline',
    'gateway.task_queue',
    'gateway.utils',
    'gateway.models',
    'gateway.routes',
    'gateway.routes.auth',
    'gateway.routes.stats',
    'gateway.routes.wsi',
    'gateway.routes.wsi_upload',
    'gateway.routes.training',
    'gateway.routes.ai_tasks',
    'gateway.routes.results',
    'gateway.routes.models',
    'gateway.routes.chat',
    'gateway.routes.chat_pdf',
    'gateway.routes.chat_pdf_vectorstore',
    'gateway.routes.chat_feedback',
    'gateway.routes.chat_patch_inference',
    'gateway.routes.chat_training_recommendation',
    'gateway.routes.storage',
    'gateway.routes.storage_scan',
    'gateway.routes.storage_tasks',
    'gateway.routes.queue',
    'gateway.routes.asr',
    'gateway.routes.heatmap',
    'gateway.routes.settings',
    'gateway.routes.gpu',
    'gateway.routes.annotation',
    'gateway.routes.wsi_grants',
    'gateway.routes.analysis_helpers',
    'gateway.routes.analysis_metrics',
    'gateway.routes.analysis_state',
    'gateway.routes.classification_analysis',
    'gateway.routes.segmentation_analysis',
    'gateway.routes.survival_analysis',
    'gateway.routes.external_validation_analysis',
    'gateway.routes.transformers_runtime',
    # Backend — preprocessing
    'backend',
    'backend.preprocessing',
    'backend.preprocessing.main',
    'backend.preprocessing.tiling',
    'backend.preprocessing.coords_utils',
    'backend.preprocessing.heatmap_routes',
    'backend.preprocessing.heatmap_utils',
    'backend.preprocessing.heatmap_preview_cache',
    # Backend — AI
    'backend.ai',
    'backend.ai.main',
    'backend.ai.routes',
    'backend.ai.routes.training',
    'backend.ai.routes.inference',
    'backend.ai.schemas',
    'backend.ai.schemas.base',
    'backend.ai.tasks',
    'backend.ai.utils',
    'backend.ai.extractors',
    'backend.ai.aggregators',
    'backend.ai.classifiers',
    'backend.ai.segmentors',
    'backend.ai.cancellation',
    'backend.ai.permission_revocation',
    # Backend — auth
    'backend.auth',
    'backend.auth.models',
    'backend.auth.users',
    # Backend — common
    'backend.common',
    'backend.common.config',
    'backend.common.redis_client',
    'backend.common.port_utils',
    'backend.common.chat_context_cache',
    'backend.common.gpu_utils',
    'backend.common.progress_store',
    'backend.common.slide_utils',
    'backend.common.file_types',
    # Backend — database
    'backend.database',
    'backend.database.models',
    'backend.database.repositories',
    'backend.database.init_db',
    # Backend — storage
    'backend.storage',
    'backend.storage.manager',
    'backend.storage.stats_mixin',
    'backend.storage.orphan_mixin',
    'backend.storage.migration',
    # Aslide (installed from git)
    'Aslide',
    'Aslide.deepzoom',
    # asyncpg internals
    'asyncpg.protocol',
    'asyncpg.protocol.protocol',
    # multiprocessing — used by main.py
    'multiprocessing',
    'multiprocessing.util',
    'multiprocessing.synchronize',
    # standard library modules that PyInstaller may miss
    'email.mime.text',
    'email.mime.multipart',
    'ctypes',
    'ctypes.util',
    '_ctypes',
    'distutils',
    'distutils.util',
    # PyJWT / python-jose
    'jwt',
    'jose',
    'jose.jwt',
    'jose.jws',
    'jose.jwe',
    'jose.constants',
    'jose.backends',
]

all_hiddenimports += extra_hidden

# ---------------------------------------------------------------------------
# Datas: include server source tree so module strings resolve at runtime.
# PyInstaller bundles .pyc files for packages it traces, but the source tree
# is needed for string-based import resolution by uvicorn/importlib.
# ---------------------------------------------------------------------------
server_root = os.path.abspath(os.path.dirname(SPEC))  # server/

all_datas += [
    # Include the entire server source tree
    (os.path.join(server_root, 'gateway'),   'gateway'),
    (os.path.join(server_root, 'backend'),   'backend'),
    # Include bundled knowledge/prompt assets
    (os.path.join(server_root, 'gateway', 'knowledge'), 'gateway/knowledge'),
    (os.path.join(server_root, 'gateway', 'prompts'),   'gateway/prompts'),
]

# openslide-python >= 4.0 ships libopenslide.so.1 inside the openslide_bin
# wheel package and loads it via importlib.resources (not ctypes.util.find_library).
# PyInstaller does NOT automatically bundle .so files that are package data, so
# we must include it explicitly as a datas entry so it lands at
# _internal/openslide_bin/libopenslide.so.1 where importlib.resources can find it.
_openslide_bin_so = None
try:
    import importlib.resources as _ir
    import openslide_bin as _osb
    _lib_name = 'libopenslide.so.1' if sys.platform == 'linux' else (
        'libopenslide.1.dylib' if sys.platform == 'darwin' else 'libopenslide-1.dll'
    )
    with _ir.as_file(_ir.files('openslide_bin').joinpath(_lib_name)) as _p:
        if _p.exists():
            _openslide_bin_so = str(_p)
except Exception:
    pass

if _openslide_bin_so:
    all_datas.append((_openslide_bin_so, 'openslide_bin'))
    print(f"[spec] Including openslide_bin library: {_openslide_bin_so}")
else:
    print("[spec] WARNING: openslide_bin library not found; openslide may fail at runtime")

# ---------------------------------------------------------------------------
# Aslide native libraries: sdpc/lib, kfb/lib, tron/lib
#
# collect_all('Aslide') collects these .so files as "binaries", but PyInstaller
# strips their directory structure and deposits them flat into _internal/ top
# level. sdpc_bindings.py uses os.path.dirname(os.path.abspath(__file__)) to
# construct the path to lib/libsqrayslideservice.so, so the files MUST land at
# _internal/Aslide/sdpc/lib/ (and similarly for kfb and tron).
#
# Solution: include each lib/ directory as datas (not binaries) so PyInstaller
# copies the full directory tree verbatim to the correct dest path.
# ---------------------------------------------------------------------------
try:
    import site as _site
    _aslide_base = None
    for _sp in _site.getsitepackages():
        _candidate = os.path.join(_sp, 'Aslide')
        if os.path.isdir(_candidate):
            _aslide_base = _candidate
            break

    if _aslide_base:
        for _subdir, _dest in [
            ('sdpc/lib', 'Aslide/sdpc/lib'),
            ('kfb/lib',  'Aslide/kfb/lib'),
            ('tron/lib', 'Aslide/tron/lib'),
        ]:
            _src_dir = os.path.join(_aslide_base, *_subdir.split('/'))
            if os.path.isdir(_src_dir):
                all_datas.append((_src_dir, _dest))
                print(f"[spec] Including Aslide libs: {_src_dir} -> {_dest}")
            else:
                print(f"[spec] WARNING: Aslide lib dir not found: {_src_dir}")
    else:
        print("[spec] WARNING: Aslide package not found in site-packages; Aslide slide support may fail")
except Exception as _e:
    print(f"[spec] WARNING: Failed to locate Aslide libs: {_e}")

# Deduplicate datas (collect_all may produce duplicates)
seen_datas = set()
dedup_datas = []
for src, dst in all_datas:
    key = (os.path.normpath(str(src)), os.path.normpath(str(dst)))
    if key not in seen_datas:
        seen_datas.add(key)
        dedup_datas.append((src, dst))

extra_binaries = []

if sys.platform == 'linux':
    for candidate in [
        '/usr/lib/x86_64-linux-gnu/libopenslide.so.0',
        '/usr/lib/x86_64-linux-gnu/libopenslide.so.0.4.1',
        '/usr/lib64/libopenslide.so.0',
        '/usr/local/lib/libopenslide.so.0',
    ]:
        if os.path.exists(candidate):
            extra_binaries.append((candidate, '.'))
            break

    for candidate in [
        '/usr/lib/x86_64-linux-gnu/libgomp.so.1',
        '/usr/lib/x86_64-linux-gnu/libgomp.so.1.0.0',
        '/usr/lib64/libgomp.so.1',
    ]:
        if os.path.exists(candidate):
            extra_binaries.append((candidate, '.'))
            break

elif sys.platform == 'darwin':
    for candidate in [
        '/opt/homebrew/lib/libopenslide.dylib',
        '/opt/homebrew/opt/openslide/lib/libopenslide.dylib',
        '/usr/local/lib/libopenslide.dylib',
        '/opt/local/lib/libopenslide.dylib',
    ]:
        if os.path.exists(candidate):
            extra_binaries.append((candidate, '.'))
            break

    for candidate in [
        '/opt/homebrew/opt/libomp/lib/libomp.dylib',
        '/opt/homebrew/lib/libgomp.1.dylib',
        '/usr/local/lib/libgomp.1.dylib',
        '/opt/homebrew/opt/gcc/lib/gcc/current/libgomp.1.dylib',
    ]:
        if os.path.exists(candidate):
            extra_binaries.append((candidate, '.'))
            break

elif sys.platform == 'win32':
    for candidate in [
        r'C:\Program Files\OpenSlide\bin\libopenslide-1.dll',
        r'C:\Program Files\OpenSlide\bin\openslide.dll',
    ]:
        if os.path.exists(candidate):
            extra_binaries.append((candidate, '.'))
            break

all_binaries += extra_binaries

# ---------------------------------------------------------------------------
# Deduplicate hidden imports
# ---------------------------------------------------------------------------
all_hiddenimports = list(dict.fromkeys(all_hiddenimports))

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join(server_root, 'main.py')],
    pathex=[server_root],          # so "gateway" and "backend" are importable
    binaries=all_binaries,
    datas=dedup_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude test frameworks (not needed at runtime)
        # NOTE: 'pdb', 'unittest', 'doctest' must NOT be excluded:
        #   - torch/distributed/__init__.py imports pdb
        #   - torch/_dispatch/python.py imports unittest.mock
        #   - torch and other libs use doctest internally
        'pytest',
        # Exclude Jupyter / IPython (heavy, not needed)
        'IPython', 'jupyter', 'notebook',
        # Exclude Qt GUI (not needed in headless server)
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter', 'wx',
        # Exclude matplotlib GUI backend (marker-pdf may import matplotlib)
        'matplotlib.backends._backend_tk',
        # --- Size optimisation: packages not needed in the sidecar ---------------
        # Triton: torch JIT-compilation backend (torch.compile). PathLab never
        # calls torch.compile(), so the ~540 MB Triton wheel is dead weight.
        'triton',
        # vLLM and its exclusive dependencies.  The check-vllm endpoint only
        # pings an *external* vLLM server via httpx — it never imports the vllm
        # Python package.  vllm, ray, xgrammar and llguidance are all uninstalled
        # from the environment; these entries are a safety-net for future re-installs.
        'vllm', 'ray', 'xgrammar', 'llguidance',
        # HoloViz / Panel visualisation stack pulled in as optional lancedb deps.
        # None of these are used by the PathLab sidecar.
        'panel', 'bokeh', 'holoviews', 'hvplot', 'param', 'colorcet',
        # PyAV — video/audio I/O pulled in as an optional transformers dep.
        # PathLab only uses transformers for image feature extraction, not video.
        'av',
        # Polars — high-performance DataFrame lib used by the HoloViz stack above.
        # lancedb's core functionality works with pyarrow/pandas without polars.
        'polars',
        # CuPy — GPU array library; was a vllm optional dep, not used directly.
        'cupy', 'cupy_backends',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE + COLLECT  (onedir mode — single directory, no extraction on launch)
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],                            # binaries go into COLLECT, not EXE
    exclude_binaries=True,         # required for onedir
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # Don't UPX — breaks many native extensions
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='main',                   # output dir: server/dist/main/
)
