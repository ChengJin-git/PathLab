"""Venue template rendering stage."""

from __future__ import annotations

from pathlab_paper_agent.schemas import PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from ..citations.sync import sync_refs_bib_to_selected_refs, sync_section_citations_to_selected_refs
from ..renderers.latex_compiler import maybe_compile_with_docker
from ..renderers.template_renderer import render_template
from .common import load_config, register_artifact


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    sync_refs_bib_to_selected_refs(paths)
    sync_section_citations_to_selected_refs(paths)
    config = load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        manifest.artifact_index.pop(f"final/{template_id}/main.pdf", None)
        final_dir = render_template(paths, config, template_id)
        compile_result = maybe_compile_with_docker(paths.root, template_id)
        register_artifact(
            manifest,
            f"final/{template_id}/main.tex",
            label=f"{template_id} LaTeX main",
            content_type="text/x-tex",
        )
        register_artifact(
            manifest,
            f"final/{template_id}/style.json",
            label=f"{template_id} style metadata",
            content_type="application/json",
        )
        register_artifact(
            manifest,
            f"final/{template_id}/main.compile_summary.txt",
            label=f"{template_id} compile summary",
            content_type="text/plain",
        )
        if (
            compile_result.status == "compiled"
            and compile_result.pdf_path is not None
            and (final_dir / "main.pdf").exists()
        ):
            register_artifact(
                manifest,
                f"final/{template_id}/main.pdf",
                label=f"{template_id} compiled PDF",
                content_type="application/pdf",
            )
