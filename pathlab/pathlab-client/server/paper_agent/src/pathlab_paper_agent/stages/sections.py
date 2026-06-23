"""Section-writing stage backed by the M9 Section Writing Agent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pathlab_paper_agent.schemas import PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from pathlab_paper_agent.agents.section_writing_agent import (
    SectionWritingAgent,
    SectionWritingInputs,
    SectionWritingResult,
)

from ..process_logging import register_private_log_artifact, write_stage_process_log
from .common import load_config, register_artifact, write_text

_PROCESS_LOG_REL_PATH = "logs/section_writing_log.private.json"


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: SectionWritingAgent | None = None,
) -> None:
    config = load_config(paths)
    section_agent = agent or SectionWritingAgent()
    events: list[dict[str, Any]] = []
    previous_sink = getattr(section_agent, "event_sink", None)
    started_at = datetime.now(UTC)
    status = "failed"
    error_payload: dict[str, str] | None = None

    def sink(event: dict[str, Any]) -> None:
        events.append(event)
        if callable(previous_sink):
            previous_sink(event)

    if hasattr(section_agent, "event_sink"):
        section_agent.event_sink = sink
    try:
        result = section_agent.generate(SectionWritingInputs.from_paths(paths, config))
        _write_outputs(paths, result)
        _register_artifacts(manifest, result)
        status = "completed"
    except Exception as exc:
        error_payload = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if hasattr(section_agent, "event_sink"):
            section_agent.event_sink = previous_sink
        write_stage_process_log(
            paths,
            _PROCESS_LOG_REL_PATH,
            stage="section_writing",
            status=status,
            started_at=started_at,
            events=events,
            error=error_payload,
        )
        register_private_log_artifact(
            manifest,
            _PROCESS_LOG_REL_PATH,
            label="Section writing process log",
        )


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
