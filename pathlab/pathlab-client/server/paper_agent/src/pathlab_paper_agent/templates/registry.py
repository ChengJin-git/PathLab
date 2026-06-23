"""Load venue templates bundled with the standalone paper agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TemplateDefinition:
    """A registered venue template and its on-disk assets."""

    template_id: str
    name: str
    directory: Path
    main_template: Path
    style: dict[str, Any]
    asset_paths: tuple[Path, ...]


def _templates_root() -> Path:
    return Path(str(resources.files("pathlab_paper_agent") / "templates"))


@lru_cache(maxsize=1)
def _registry_payload() -> dict[str, Any]:
    registry_path = _templates_root() / "registry.json"
    return json.loads(registry_path.read_text(encoding="utf-8"))


def _asset_paths(directory: Path, relative_paths: list[str]) -> tuple[Path, ...]:
    return tuple(directory / rel for rel in relative_paths)


@lru_cache(maxsize=None)
def get_template(template_id: str) -> TemplateDefinition:
    """Return one template definition by id."""
    for raw in _registry_payload().get("templates", []):
        if raw.get("id") != template_id:
            continue
        directory = _templates_root() / raw["directory"]
        style_path = directory / raw.get("style", "style.json")
        style = json.loads(style_path.read_text(encoding="utf-8"))
        return TemplateDefinition(
            template_id=raw["id"],
            name=raw["name"],
            directory=directory,
            main_template=directory / raw.get("main", "main.tex.j2"),
            style=style,
            asset_paths=_asset_paths(directory, raw.get("assets", [])),
        )
    known = ", ".join(t.get("id", "<unknown>") for t in _registry_payload().get("templates", []))
    raise ValueError(f"Unknown template_id {template_id!r}. Known templates: {known}")


def list_templates() -> list[TemplateDefinition]:
    """Return all templates in registry order."""
    return [get_template(raw["id"]) for raw in _registry_payload().get("templates", [])]
