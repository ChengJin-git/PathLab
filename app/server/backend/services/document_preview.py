"""Versioned, on-demand page previews for PDF and Office deliverables."""

from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import zipfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from backend.common.file_lock import flock, LOCK_EX, LOCK_NB, LOCK_UN

OFFICE_SUFFIXES = {".ppt", ".pptx", ".odp", ".doc", ".docx", ".odt", ".rtf"}
PAGE_SUFFIXES = OFFICE_SUFFIXES | {".pdf"}
MAX_BYTES = 32 * 1024 * 1024
MAX_PAGES = 300
_warm_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-preview")
_warm_lock = threading.Lock()
_pdf_lock = threading.RLock()  # PyMuPDF documents must not run concurrently in threads.
_warming: set[tuple[str, str, int, int]] = set()


def schedule_preview(path: Path, display_name: str) -> None:
    """Prepare delivered documents off the request/agent path; bounded, deduplicated."""
    if Path(display_name).suffix.lower() not in PAGE_SUFFIXES:
        return
    try:
        stat = path.stat()
    except OSError:
        return
    if stat.st_size > MAX_BYTES:
        return
    key = (str(path), Path(display_name).suffix.lower(), stat.st_mtime_ns, stat.st_size)
    version = hashlib.sha256(f"{stat.st_mtime_ns}:{stat.st_size}:{key[1]}".encode()).hexdigest()[:24]
    cache = path.parent / (path.name + '.preview') / version
    if (cache / 'pages.json').is_file() and (cache / 'page-1.png').is_file():
        return
    with _warm_lock:
        if key in _warming or len(_warming) >= 8:
            return
        _warming.add(key)

    def prepare():
        try:
            if path.is_file():
                preview_document(path, display_name)
        except (OSError, ValueError, RuntimeError):
            # An optional warm-up cannot fail publication; an explicit preview
            # reports its own localized error if the renderer is unavailable.
            pass
        finally:
            if not path.is_file():
                # Deletion can race an already-admitted background conversion.
                shutil.rmtree(path.parent / (path.name + '.preview'), ignore_errors=True)
            with _warm_lock:
                _warming.discard(key)

    try:
        _warm_pool.submit(prepare)
    except RuntimeError:
        with _warm_lock:
            _warming.discard(key)


def _office_command(work: Path, suffix: str):
    binary = os.getenv("PATHLAB_PREVIEW_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice")
    if binary:
        return [binary, f"-env:UserInstallation={(work / 'profile').resolve().as_uri()}",
                "--headless", "--nologo", "--nodefault", "--norestore", "--convert-to", "pdf",
                "--outdir", str(work), str(work / ('source' + suffix))], {**os.environ, "SAL_USE_VCLPLUGIN": "svp"}, None
    # Desktop installations already ship the Office-capable research sandbox.
    # Mount only this temporary conversion directory, not the research workspace.
    from backend.autoresearch.runtime import container_backend
    from backend.autoresearch.runtime.sandbox import _resolve_apptainer_bin, _resolve_default_image
    image = _resolve_default_image()
    if container_backend.backend() != 'docker' and not Path(image).is_file():
        raise ValueError("previewRendererUnavailable")
    command = [_resolve_apptainer_bin(), "exec", "--contain", "--no-home", "--no-mount", "cwd,bind-paths",
               "--cleanenv", "--writable-tmpfs", "--bind", f"{work}:/preview:rw", "--pwd", "/preview", image,
               "soffice", "-env:UserInstallation=file:///preview/profile", "--headless", "--nologo",
               "--nodefault", "--norestore", "--convert-to", "pdf", "--outdir", "/preview", "/preview/source" + suffix]
    return container_backend.prepare(command, {"PATH": os.environ.get('PATH', ''), "HOME": os.environ.get('HOME', ''), "APPTAINERENV_SAL_USE_VCLPLUGIN": "svp"})


def _cache(path: Path, suffix: str) -> Path:
    stat = path.stat()
    if stat.st_size > MAX_BYTES:
        raise ValueError("previewTooLarge")
    version = hashlib.sha256(f"{stat.st_mtime_ns}:{stat.st_size}:{suffix}".encode()).hexdigest()[:24]
    root = path.parent / (path.name + ".preview") / version
    root.mkdir(parents=True, exist_ok=True)
    return root


def _convert_office(path: Path, suffix: str, root: Path) -> Path:
    target = root / "document.pdf"
    if target.is_file():
        return target
    with (root / "convert.lock").open("a+b") as lock:
        deadline = time.monotonic() + 47
        while True:
            try:
                flock(lock, LOCK_EX | LOCK_NB)
                break
            except BlockingIOError:
                if target.is_file():
                    return target
                if time.monotonic() >= deadline:
                    raise ValueError("previewBusy") from None
                time.sleep(0.05)
        try:
            if target.is_file():
                return target
            if suffix in {".pptx", ".docx", ".odp", ".odt"}:
                try:
                    with zipfile.ZipFile(path) as archive:
                        entries = archive.infolist()
                        required = {".pptx": "ppt/presentation.xml", ".docx": "word/document.xml",
                                    ".odp": "content.xml", ".odt": "content.xml"}[suffix]
                        if required not in archive.namelist():
                            raise ValueError("previewUnavailable")
                        if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 256 * 1024 * 1024:
                            raise ValueError("previewTooLarge")
                except zipfile.BadZipFile:
                    raise ValueError("previewUnavailable") from None
            with tempfile.TemporaryDirectory(prefix="render-", dir=root) as directory:
                work = Path(directory)
                source = work / ("source" + suffix)
                shutil.copyfile(path, source)
                profile = work / "profile"
                (profile / "user").mkdir(parents=True)
                (profile / "user/registrymodifications.xcu").write_text(
                    '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
                    '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                    '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>'
                    '</oor:items>', encoding="utf-8",
                )
                command, env, container = _office_command(work, suffix)
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=os.name != "nt", env=env)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    if container:
                        from backend.autoresearch.runtime.container_backend import remove_container_sync
                        remove_container_sync(container)
                    if os.name == "nt":
                        process.kill()
                    else:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
                    raise ValueError("previewTimeout") from None
                converted = work / "source.pdf"
                if process.returncode or not converted.is_file():
                    raise ValueError("previewUnavailable")
                _page_info(converted)
                if not path.is_file():
                    raise FileNotFoundError(path)
                os.replace(converted, target)
            return target
        finally:
            flock(lock, LOCK_UN)


def _page_info(path: Path) -> dict:
    import pymupdf

    if path.stat().st_size > MAX_BYTES:
        raise ValueError("previewTooLarge")
    try:
        with _pdf_lock, pymupdf.open(path) as document:
            if document.needs_pass or not document.page_count:
                raise ValueError("previewUnavailable")
            if document.page_count > MAX_PAGES:
                raise ValueError("previewTooLarge")
            rect = document[0].rect
            return {"page_count": document.page_count, "page_width": rect.width, "page_height": rect.height}
    except (pymupdf.FileDataError, RuntimeError):
        raise ValueError("previewUnavailable") from None


def document_path(path: Path, display_name: str) -> tuple[Path, Path]:
    suffix = Path(display_name).suffix.lower()
    if suffix not in PAGE_SUFFIXES:
        raise ValueError("unsupportedPreview")
    cache = _cache(path, suffix)
    return (path if suffix == ".pdf" else _convert_office(path, suffix, cache)), cache


def _document_info(source: Path, cache: Path) -> dict:
    manifest = cache / 'pages.json'
    if manifest.is_file():
        try:
            return json.loads(manifest.read_text())
        except (OSError, ValueError):
            pass
    info = _page_info(source)
    with tempfile.NamedTemporaryFile(dir=cache, mode='w', encoding='utf-8', delete=False) as temporary:
        json.dump(info, temporary)
        name = Path(temporary.name)
    try:
        os.replace(name, manifest)
    finally:
        name.unlink(missing_ok=True)
    return info


def preview_document(path: Path, display_name: str) -> dict:
    document, cache = document_path(path, display_name)
    suffix = Path(display_name).suffix.lower()
    info = _document_info(document, cache)
    first = render_page(path, display_name, 1)
    # Deliver the ready first page with the descriptor, removing the sequential
    # descriptor -> page request round trip. Keep the JSON payload bounded.
    first_page = "data:image/png;base64," + base64.b64encode(first.read_bytes()).decode() if first.stat().st_size <= 1024 * 1024 else None
    return {"kind": "slides" if suffix in {".ppt", ".pptx", ".odp"} else "pdf" if suffix == ".pdf" else "document",
            **info, "first_page": first_page}


def render_page(path: Path, display_name: str, page: int) -> Path:
    import pymupdf

    source, cache = document_path(path, display_name)
    target = cache / f"page-{page}.png"
    # Cached pages need neither a PDF open nor font/layout work.
    if 1 <= page <= MAX_PAGES and target.is_file():
        return target
    info = _document_info(source, cache)
    if page < 1 or page > info["page_count"]:
        raise ValueError("previewPageNotFound")
    with _pdf_lock:
        if target.is_file():
            return target
        with pymupdf.open(source) as document:
            current = document[page - 1]
            # Bound pixel memory even for unusual poster/slide page dimensions.
            scale = min(2, 1800 / max(current.rect.width, current.rect.height, 1))
            pixmap = current.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            with tempfile.NamedTemporaryFile(dir=cache, suffix=".png", delete=False) as temporary:
                filename = Path(temporary.name)
            try:
                pixmap.save(filename)
                os.replace(filename, target)
            finally:
                filename.unlink(missing_ok=True)
    return target
