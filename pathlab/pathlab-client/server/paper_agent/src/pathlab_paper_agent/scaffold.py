"""Lightweight paper-run scaffold shared by Gateway and the CLI."""

from __future__ import annotations

import json
from typing import Any

from pathlab_paper_agent.bootstrap import ensure_server_on_path
from pathlab_paper_agent.schemas import PaperConfig, PaperManifest, PaperRunStage, PaperRunStatus
from pathlab_paper_agent.storage import PaperRunPaths

ensure_server_on_path()

from backend.database.models import utc_now  # noqa: E402


def _serialize(payload: Any) -> str:
    """JSON dump with stable formatting and timezone-aware datetimes."""

    def default(obj: Any) -> Any:
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if hasattr(obj, "value"):
            return obj.value
        raise TypeError(f"Cannot serialize {type(obj).__name__}")

    return json.dumps(payload, indent=2, ensure_ascii=False, default=default)


def _artifact(
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "visibility": visibility,
        "downloadable": downloadable,
    }
    if label is not None:
        payload["label"] = label
    if content_type is not None:
        payload["content_type"] = content_type
    return payload


async def initialize_paper_run(
    db: Any,
    config: PaperConfig,
) -> PaperRunPaths:
    """Create the paper-run scaffold used by Gateway and the standalone CLI."""
    del db  # Filesystem scaffold does not require a DB session.
    paths = PaperRunPaths.for_paper(config.paper_id)
    paths.ensure_dirs()

    paths.config.write_text(
        _serialize(config.model_dump(mode="json")), encoding="utf-8"
    )

    now = utc_now()
    manifest = PaperManifest(
        paper_id=config.paper_id,
        status=PaperRunStatus.pending,
        current_stage=PaperRunStage.created,
        stage_log=[
            {
                "stage": PaperRunStage.created.value,
                "ts": now.isoformat(),
                "message": "Paper run scaffold created.",
            }
        ],
        artifact_index={
            "config.json": _artifact(
                label="Run config",
                content_type="application/json",
            ),
            "manifest.json": _artifact(
                label="Run manifest",
                content_type="application/json",
            ),
        },
        created_at=now,
        updated_at=now,
    )
    paths.manifest.write_text(
        _serialize(manifest.model_dump(mode="json")), encoding="utf-8"
    )
    return paths
