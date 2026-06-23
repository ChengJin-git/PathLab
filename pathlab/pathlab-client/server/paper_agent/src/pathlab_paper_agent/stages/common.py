"""Shared helpers for deterministic paper-agent stages."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..bootstrap import ensure_server_on_path

ensure_server_on_path()

from pathlab_paper_agent.schemas import PaperConfig, PaperManifest  # noqa: E402
from pathlab_paper_agent.storage import PaperRunPaths  # noqa: E402

SECTION_ORDER = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)


def json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"Cannot serialize {type(obj).__name__}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact(
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: Optional[str] = None,
    content_type: Optional[str] = None,
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


def register_artifact(
    manifest: PaperManifest,
    rel_path: str,
    *,
    status: str = "ready",
    visibility: str = "public",
    downloadable: bool = True,
    label: Optional[str] = None,
    content_type: Optional[str] = None,
) -> None:
    manifest.artifact_index[rel_path] = artifact(
        status=status,
        visibility=visibility,
        downloadable=downloadable,
        label=label,
        content_type=content_type,
    )


def load_config(paths: PaperRunPaths) -> PaperConfig:
    if not paths.config.exists():
        raise FileNotFoundError(f"config.json not found for {paths.paper_id}")
    return PaperConfig.model_validate(read_json(paths.config))


def source_task_lines(config: PaperConfig) -> str:
    lines = []
    for item in config.source_tasks:
        label = f" ({item.label})" if item.label else ""
        lines.append(f"- {item.task_id}: role={item.role.value}{label}")
    return "\n".join(lines) or "- No source task registered."


def copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
