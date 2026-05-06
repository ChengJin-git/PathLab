"""Post-extract LaTeX validation for exported submission bundles."""

from __future__ import annotations

import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .latex_compiler import docker_available

_STALE_COMPILE_OUTPUTS = (
    "main.aux",
    "main.bbl",
    "main.bcf",
    "main.blg",
    "main.fdb_latexmk",
    "main.fls",
    "main.log",
    "main.out",
    "main.pdf",
    "main.run.xml",
    "main.synctex.gz",
    "main.toc",
)


@dataclass(frozen=True)
class BundleValidationResult:
    """Outcome of compiling an extracted ZIP bundle."""

    status: str
    returncode: int | None
    downloadable: bool
    summary: str
    stdout: str = ""
    stderr: str = ""


def validate_bundle(
    bundle_path: Path,
    *,
    image: str = "pathlab/paper-latex:latest",
    timeout_seconds: int = 120,
) -> BundleValidationResult:
    """Extract `bundle_path` and run a dry-run latexmk compile in Docker."""
    if not bundle_path.is_file():
        return BundleValidationResult(
            status="failed",
            returncode=None,
            downloadable=False,
            summary=f"Bundle is missing: {bundle_path}",
        )
    if not docker_available():
        return BundleValidationResult(
            status="skipped",
            returncode=None,
            downloadable=False,
            summary="Docker is not available; bundle latexmk dry-run was skipped.",
        )

    with TemporaryDirectory(prefix="pathlab_bundle_validate_") as tmp:
        extract_dir = Path(tmp) / "bundle"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            _safe_extract(bundle_path, extract_dir)
            _remove_stale_compile_outputs(extract_dir)
            proc = _run_latexmk(extract_dir, image=image, timeout_seconds=timeout_seconds)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return BundleValidationResult(
                status="failed",
                returncode=None,
                downloadable=False,
                summary=f"Bundle validation could not start: {exc}",
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_output(exc.stdout)
            stderr = _coerce_output(exc.stderr)
            return BundleValidationResult(
                status="failed",
                returncode=None,
                downloadable=False,
                summary=_summary(extract_dir, "latexmk timed out.", stdout, stderr),
                stdout=stdout,
                stderr=stderr,
            )

        downloadable = proc.returncode == 0 and (extract_dir / "main.pdf").is_file()
        status = "passed" if downloadable else "failed"
        return BundleValidationResult(
            status=status,
            returncode=proc.returncode,
            downloadable=downloadable,
            summary=_summary(extract_dir, f"latexmk status: {status}", proc.stdout, proc.stderr),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def _run_latexmk(
    extract_dir: Path,
    *,
    image: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{extract_dir.resolve()}:/work",
        "-w",
        "/work",
        "--entrypoint",
        "latexmk",
        image,
        "-pdf",
        "-interaction=nonstopmode",
        "-file-line-error",
        "main.tex",
    ]
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )


def _safe_extract(bundle_path: Path, extract_dir: Path) -> None:
    root = extract_dir.resolve()
    with zipfile.ZipFile(bundle_path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe ZIP member path: {member.filename}")
            target = (extract_dir / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"ZIP member escapes extraction root: {member.filename}") from exc
        archive.extractall(extract_dir)


def _remove_stale_compile_outputs(extract_dir: Path) -> None:
    for name in _STALE_COMPILE_OUTPUTS:
        path = extract_dir / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            raise ValueError(f"Unexpected directory where compile output should be a file: {name}")


def _summary(extract_dir: Path, headline: str, stdout: str, stderr: str) -> str:
    lines = [headline, ""]
    log_path = extract_dir / "main.log"
    if log_path.is_file():
        lines.extend(["main.log tail:", _tail(log_path.read_text(encoding="utf-8", errors="ignore")), ""])
    lines.extend(["stdout tail:", stdout[-2000:], "", "stderr tail:", stderr[-2000:]])
    return "\n".join(lines).strip()


def _tail(text: str, *, limit: int = 2000) -> str:
    return text[-limit:]


def _coerce_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
