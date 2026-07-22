"""LaTeX compilation helpers for rendered paper templates."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


_COMPILE_OUTPUT_NAMES = (
    "main.aux",
    "main.bbl",
    "main.bcf",
    "main.blg",
    "main.compile_summary.txt",
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
class CompileResult:
    """Outcome of a LaTeX compile attempt."""

    status: str
    returncode: int | None
    pdf_path: Path | None
    summary_path: Path
    stdout: str = ""
    stderr: str = ""


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def docker_image_available(image: str = "pathlab/paper-latex:latest") -> bool:
    if not docker_available():
        return False
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def host_latexmk_available() -> bool:
    return shutil.which("latexmk") is not None


def should_compile_from_env() -> bool:
    return os.environ.get("PATHLAB_PAPER_AGENT_COMPILE_LATEX", "0") in {"1", "true", "yes"}


def remove_stale_compile_outputs(template_dir: Path) -> None:
    """Remove previous compile outputs before judging a new Docker compile."""
    for name in _COMPILE_OUTPUT_NAMES:
        path = template_dir / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def write_compile_summary(
    template_dir: Path,
    *,
    status: str,
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
) -> Path:
    summary_path = template_dir / "main.compile_summary.txt"
    pdf_present = "yes" if (template_dir / "main.pdf").exists() else "no"
    summary_path.write_text(
        "compile_summary\n"
        f"  status={status}\n"
        f"  returncode={returncode}\n"
        f"  pdf_present={pdf_present}\n"
        "  stdout_tail:\n"
        f"{stdout[-2000:]}\n"
        "  stderr_tail:\n"
        f"{stderr[-2000:]}\n",
        encoding="utf-8",
    )
    return summary_path


def compile_with_docker(
    paper_root: Path,
    template_id: str,
    *,
    image: str = "pathlab/paper-latex:latest",
    timeout_seconds: int = 120,
) -> CompileResult:
    """Compile `final/{template_id}/main.tex` via the paper-latex Docker image."""
    template_dir = paper_root / "final" / template_id
    remove_stale_compile_outputs(template_dir)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{(paper_root / 'final').resolve()}:/work",
        image,
        "compile",
        template_id,
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
    )
    status = "compiled" if proc.returncode == 0 and (template_dir / "main.pdf").exists() else "failed"
    summary = write_compile_summary(
        template_dir,
        status=status,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
    pdf_path = (template_dir / "main.pdf") if status == "compiled" else None
    return CompileResult(
        status=status,
        returncode=proc.returncode,
        pdf_path=pdf_path,
        summary_path=summary,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def compile_with_host_latexmk(
    paper_root: Path,
    template_id: str,
    *,
    timeout_seconds: int = 120,
) -> CompileResult:
    """Compile `final/{template_id}/main.tex` with host latexmk as a fallback."""
    template_dir = paper_root / "final" / template_id
    remove_stale_compile_outputs(template_dir)
    proc = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-file-line-error", "main.tex"],
        cwd=template_dir,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
    )
    status = "compiled" if proc.returncode == 0 and (template_dir / "main.pdf").exists() else "failed"
    summary = write_compile_summary(
        template_dir,
        status=status,
        returncode=proc.returncode,
        stdout="Host latexmk fallback was used.\n" + proc.stdout,
        stderr=proc.stderr,
    )
    pdf_path = (template_dir / "main.pdf") if status == "compiled" else None
    return CompileResult(status, proc.returncode, pdf_path, summary, proc.stdout, proc.stderr)


def compile_latex(
    paper_root: Path,
    template_id: str,
    *,
    image: str = "pathlab/paper-latex:latest",
    timeout_seconds: int = 120,
) -> CompileResult:
    """Compile LaTeX, preferring the Docker sandbox and falling back to host latexmk."""
    if docker_image_available(image):
        return compile_with_docker(paper_root, template_id, image=image, timeout_seconds=timeout_seconds)
    if host_latexmk_available():
        return compile_with_host_latexmk(paper_root, template_id, timeout_seconds=timeout_seconds)

    template_dir = paper_root / "final" / template_id
    summary = write_compile_summary(
        template_dir,
        status="skipped",
        returncode=None,
        stderr=(
            f"Docker image {image!r} is not available and host latexmk was not found. "
            "Build the Docker image or install a TeX distribution."
        ),
    )
    return CompileResult("skipped", None, None, summary)


def maybe_compile_with_docker(paper_root: Path, template_id: str) -> CompileResult:
    """Compile only when explicitly enabled by env; otherwise write a skip summary."""
    template_dir = paper_root / "final" / template_id
    if not should_compile_from_env():
        summary = write_compile_summary(
            template_dir,
            status="skipped",
            returncode=None,
            stderr="Set PATHLAB_PAPER_AGENT_COMPILE_LATEX=1 to compile with Docker.",
        )
        return CompileResult("skipped", None, None, summary)
    return compile_latex(paper_root, template_id)
