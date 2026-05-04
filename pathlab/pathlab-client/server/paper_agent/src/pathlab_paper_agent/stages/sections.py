"""Section-writing stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperConfig, PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import SECTION_ORDER, load_config, register_artifact, write_text


def section_text(section: str, config: PaperConfig) -> str:
    title = config.title or "PathLab Paper Draft"
    if section == "abstract":
        return (
            "\\begin{abstract}\n"
            f"This scaffold initializes the paper-generation pipeline for {title}. "
            "Evidence-locked metrics are intentionally omitted until collector output is available.\n"
            "\\end{abstract}\n"
        )
    if section == "introduction":
        idea = (
            config.user_idea
            or "PathLab converts completed digital pathology experiments into evidence-locked manuscripts."
        ).strip()
        return f"\\section{{Introduction}}\n{idea}\n"
    if section == "related_work":
        return "\\section{Related Work}\nVerified citations will be inserted by the Literature Review Agent.\n"
    if section == "methods":
        return "\\section{Methods}\n\\input{locked_blocks/method_block.tex}\n"
    if section == "experiments":
        return "\\section{Experimental Setup}\n\\input{locked_blocks/dataset_block.tex}\n"
    if section == "results":
        return "\\section{Results}\n\\input{locked_blocks/results_block.tex}\n\\input{tables/table_1_dataset.tex}\n"
    if section == "discussion":
        return "\\section{Discussion}\nClaim strength is limited to evidence available in the PathLab run.\n"
    if section == "conclusion":
        return "\\section{Conclusion}\nThis scaffold is ready for collector, agent, guard, renderer, and export milestones.\n"
    raise ValueError(f"Unknown section: {section}")


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    for section in SECTION_ORDER:
        rel_path = f"drafts/sections/{section}.tex"
        write_text(paths.sections_dir / f"{section}.tex", section_text(section, config))
        register_artifact(
            manifest,
            rel_path,
            label=f"Section: {section.replace('_', ' ').title()}",
            content_type="text/x-tex",
        )
