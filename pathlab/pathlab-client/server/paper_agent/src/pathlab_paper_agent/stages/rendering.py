"""Template rendering stage scaffold."""

from __future__ import annotations

import shutil

from gateway.paper_generation.schemas import PaperConfig, PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import SECTION_ORDER, copy_tree_contents, load_config, register_artifact, write_text


def main_tex(template_id: str, config: PaperConfig) -> str:
    title = config.title or "PathLab Paper Draft"
    template_note = (
        "MICCAI/LNCS scaffold" if template_id == "miccai" else "Nature Scientific Reports scaffold"
    )
    section_inputs = "\n".join(
        f"\\input{{sections/{section}.tex}}" for section in SECTION_ORDER
    )
    return f"""\\documentclass{{article}}
\\usepackage{{booktabs}}
\\usepackage{{graphicx}}
\\title{{{title}}}
\\author{{PathLab Paper Agent}}
\\date{{}}
\\begin{{document}}
\\maketitle
% {template_note}. Venue-specific classes land in M4.
{section_inputs}
\\bibliographystyle{{plain}}
\\bibliography{{refs}}
\\end{{document}}
"""


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        final_dir = paths.final_for_template(template_id)
        final_dir.mkdir(parents=True, exist_ok=True)
        write_text(final_dir / "main.tex", main_tex(template_id, config))
        copy_tree_contents(paths.sections_dir, final_dir / "sections")
        copy_tree_contents(paths.locked_blocks_dir, final_dir / "locked_blocks")
        copy_tree_contents(paths.tables_dir, final_dir / "tables")
        copy_tree_contents(paths.figures_dir, final_dir / "figures")
        if paths.refs_bib.exists():
            shutil.copy2(paths.refs_bib, final_dir / "refs.bib")
        else:
            write_text(final_dir / "refs.bib", "")
        register_artifact(
            manifest,
            f"final/{template_id}/main.tex",
            label=f"{template_id} LaTeX main",
            content_type="text/x-tex",
        )
