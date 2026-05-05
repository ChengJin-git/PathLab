"""Submission bundle export stage."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from ..renderers.bundle_validator import BundleValidationResult, validate_bundle
from ..renderers.latex_compiler import (
    CompileResult,
    compile_with_docker,
    docker_available,
    write_compile_summary,
)
from ..renderers.zip_exporter import BundleExportResult, export_bundle
from .common import load_config, register_artifact

_M12A_WARNING_HEADER = "## M12a Export Hardening"


def _compile_final_pdf(paths: PaperRunPaths, template_id: str) -> CompileResult:
    final_dir = paths.final_for_template(template_id)
    if not docker_available():
        summary = write_compile_summary(
            final_dir,
            status="skipped",
            returncode=None,
            stderr="Docker is not available; final PDF compile was skipped.",
        )
        return CompileResult("skipped", None, None, summary)
    try:
        return compile_with_docker(paths.root, template_id)
    except Exception as exc:  # pragma: no cover - exercised by Docker/runtime failures.
        summary = write_compile_summary(
            final_dir,
            status="failed",
            returncode=None,
            stderr=str(exc),
        )
        return CompileResult("failed", None, None, summary, stderr=str(exc))


def _warning_for_compile(template_id: str, result: CompileResult) -> str | None:
    if result.status == "compiled" and result.pdf_path is not None:
        return None
    return (
        f"- `{template_id}` final PDF compile did not pass "
        f"(status={result.status}, returncode={result.returncode}).\n"
        f"  See `final/{template_id}/main.compile_summary.txt`."
    )


def _warning_for_bundle(template_id: str, result: BundleExportResult) -> str | None:
    if result.dependency_closed:
        return None
    missing = ", ".join(f"`{name}`" for name in result.missing_dependencies)
    return f"- `{template_id}` bundle is not dependency-closed; missing: {missing}."


def _warning_for_validation(template_id: str, result: BundleValidationResult) -> str | None:
    if result.status == "passed":
        return None
    return (
        f"- `{template_id}` bundle dry-run latexmk failed "
        f"(status={result.status}, returncode={result.returncode}).\n"
        f"  {result.summary}"
    )


def _append_export_warnings(paths: PaperRunPaths, warnings: list[str]) -> None:
    warnings_path = paths.validation_dir / "warnings.md"
    if warnings_path.exists():
        existing = warnings_path.read_text(encoding="utf-8").rstrip()
    else:
        existing = "# Validation Warnings"
    existing = _strip_m12a_warning_section(existing).rstrip()
    if not warnings:
        if warnings_path.exists():
            warnings_path.write_text(existing + "\n", encoding="utf-8")
        return
    section = f"\n\n{_M12A_WARNING_HEADER}\n\n" + "\n".join(warnings) + "\n"
    warnings_path.parent.mkdir(parents=True, exist_ok=True)
    warnings_path.write_text(existing + section, encoding="utf-8")


def _strip_m12a_warning_section(text: str) -> str:
    marker = f"\n\n{_M12A_WARNING_HEADER}"
    index = text.find(marker)
    if index == -1:
        if text.startswith(_M12A_WARNING_HEADER):
            return ""
        return text
    return text[:index]


def _register_compile_artifacts(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    template_id: str,
    compile_result: CompileResult,
) -> None:
    register_artifact(
        manifest,
        f"final/{template_id}/main.compile_summary.txt",
        label=f"{template_id} compile summary",
        content_type="text/plain",
    )
    manifest.artifact_index.pop(f"final/{template_id}/main.pdf", None)
    pdf_path = paths.final_for_template(template_id) / "main.pdf"
    if compile_result.status == "compiled" and pdf_path.is_file():
        register_artifact(
            manifest,
            f"final/{template_id}/main.pdf",
            label=f"{template_id} compiled PDF",
            content_type="application/pdf",
        )


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    warnings: list[str] = []
    for template in config.selected_templates:
        template_id = template.value
        bundle_name = f"{template_id}_bundle.zip"

        compile_result = _compile_final_pdf(paths, template_id)
        _register_compile_artifacts(paths, manifest, template_id, compile_result)

        export_result = export_bundle(
            paths.final_for_template(template_id),
            paths.exports_dir / bundle_name,
            config,
            template_id,
        )
        validation_result = validate_bundle(paths.exports_dir / bundle_name)
        downloadable = (
            compile_result.status == "compiled"
            and export_result.dependency_closed
            and validation_result.downloadable
        )

        for warning in (
            _warning_for_compile(template_id, compile_result),
            _warning_for_bundle(template_id, export_result),
            _warning_for_validation(template_id, validation_result),
        ):
            if warning:
                warnings.append(warning)

        register_artifact(
            manifest,
            f"exports/{bundle_name}",
            downloadable=downloadable,
            label=f"{template_id} submission bundle",
            content_type="application/zip",
        )
    _append_export_warnings(paths, warnings)
    warnings_path = paths.validation_dir / "warnings.md"
    if warnings:
        register_artifact(
            manifest,
            "validation/warnings.md",
            label="Validation warnings",
            content_type="text/markdown",
        )
    elif warnings_path.exists():
        manifest.artifact_index.pop("validation/warnings.md", None)
