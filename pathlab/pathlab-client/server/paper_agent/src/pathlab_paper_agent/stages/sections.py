"""Section-writing stage backed by the M9 Section Writing Agent."""

from __future__ import annotations

from pathlab_paper_agent.schemas import PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.agents.section_writing_agent import (
    SectionWritingAgent,
    SectionWritingInputs,
    SectionWritingResult,
)

from .common import load_config, register_artifact, write_text


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: SectionWritingAgent | None = None,
) -> None:
    config = load_config(paths)
    section_agent = agent or SectionWritingAgent()
    result = section_agent.generate(SectionWritingInputs.from_paths(paths, config))
    _write_outputs(paths, result)
    _register_artifacts(manifest, result)


def _write_outputs(paths: PaperRunPaths, result: SectionWritingResult) -> None:
    for section, text in result.sections.items():
        write_text(paths.sections_dir / f"{section}.tex", text)


def _register_artifacts(manifest: PaperManifest, result: SectionWritingResult) -> None:
    for section in result.sections:
        rel_path = f"drafts/sections/{section}.tex"
        register_artifact(
            manifest,
            rel_path,
            label=f"Section: {section.replace('_', ' ').title()}",
            content_type="text/x-tex",
        )
