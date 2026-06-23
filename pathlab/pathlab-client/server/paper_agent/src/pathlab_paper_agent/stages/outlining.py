"""PaperOrchestra-style Outline Agent stage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pathlab_paper_agent.schemas import OutlineDocument, PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

from ..agents import OutlineAgent, OutlineInputs
from ..process_logging import register_private_log_artifact, write_stage_process_log
from .common import load_config, register_artifact, write_json

_PROCESS_LOG_REL_PATH = "logs/outlining_log.private.json"


def run(
    paths: PaperRunPaths,
    manifest: PaperManifest,
    *,
    agent: OutlineAgent | None = None,
) -> None:
    config = load_config(paths)
    outline_agent = agent or OutlineAgent()
    events: list[dict[str, Any]] = []
    previous_sink = getattr(outline_agent, "event_sink", None)
    started_at = datetime.now(UTC)
    status = "failed"
    error_payload: dict[str, str] | None = None

    def sink(event: dict[str, Any]) -> None:
        events.append(event)
        if callable(previous_sink):
            previous_sink(event)

    if hasattr(outline_agent, "event_sink"):
        outline_agent.event_sink = sink
    try:
        outline = outline_agent.generate(OutlineInputs.from_paths(paths, config))
        outline_document = OutlineDocument.model_validate(outline)
        write_json(paths.outline_json, outline_document.model_dump(mode="json"))
        register_artifact(
            manifest,
            "drafts/outline.json",
            label="Outline",
            content_type="application/json",
        )
        status = "completed"
    except Exception as exc:
        error_payload = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if hasattr(outline_agent, "event_sink"):
            outline_agent.event_sink = previous_sink
        write_stage_process_log(
            paths,
            _PROCESS_LOG_REL_PATH,
            stage="outlining",
            status=status,
            started_at=started_at,
            events=events,
            error=error_payload,
        )
        register_private_log_artifact(
            manifest,
            _PROCESS_LOG_REL_PATH,
            label="Outlining process log",
        )
