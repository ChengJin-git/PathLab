"""Registry for orchestrator-owned data preparation skills."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)
_DATA_SKILLS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class DataSkill:
    name: str
    kind: str
    description: str
    trigger: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    supported_label_types: list[str] = field(default_factory=list)
    planned_label_types: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "DataSkill":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            name=str(data.get("name") or ""),
            kind=str(data.get("kind") or "data_preparation"),
            description=str(data.get("description") or ""),
            trigger=dict(data.get("trigger") or {}),
            inputs=dict(data.get("inputs") or {}),
            outputs=dict(data.get("outputs") or {}),
            supported_label_types=list(data.get("supported_label_types") or []),
            planned_label_types=list(data.get("planned_label_types") or []),
            constraints=list(data.get("constraints") or []),
        )


class DataSkillRegistry:
    def __init__(self):
        self._skills: dict[str, DataSkill] = {}
        self._loaded = False

    def load_all(self) -> int:
        if self._loaded:
            return len(self._skills)
        for yaml_file in sorted(_DATA_SKILLS_DIR.glob("*.yaml")):
            try:
                skill = DataSkill.from_yaml(yaml_file)
                if skill.name:
                    self._skills[skill.name] = skill
            except Exception as e:
                logger.warning("[data_skills] Failed to load %s: %s", yaml_file.name, e)
        self._loaded = True
        return len(self._skills)

    def get(self, name: str) -> DataSkill:
        self._ensure_loaded()
        if name not in self._skills:
            raise KeyError(f"Data skill not found: {name!r}")
        return self._skills[name]

    def list_available(self) -> list[str]:
        self._ensure_loaded()
        return list(self._skills)

    def list_skills(self) -> list[DataSkill]:
        self._ensure_loaded()
        return list(self._skills.values())

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load_all()


registry = DataSkillRegistry()

__all__ = ["DataSkill", "DataSkillRegistry", "registry"]
